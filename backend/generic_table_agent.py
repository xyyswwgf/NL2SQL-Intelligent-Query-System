from __future__ import annotations

import time
import uuid
from typing import Any, TypedDict

from backend.agent_service import save_analysis_result
from backend.database import execute_sql, quote_identifier, table_exists
from backend.sql_guard import validate_sql


class GenericTableState(TypedDict, total=False):
    question: str
    table_name: str
    analysis_mode: str
    run_id: str
    steps: list[dict[str, Any]]
    plan: list[dict[str, str]]
    schema_profile: dict[str, Any]
    sql_queries: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    attribution: dict[str, Any]
    charts: list[dict[str, Any]]
    report: dict[str, Any]
    errors: list[dict[str, str]]


NUMERIC_TYPES = ("integer", "bigint", "numeric", "decimal", "double", "real", "smallint")
DATE_TYPES = ("date", "timestamp", "timestamp with time zone", "timestamp without time zone")
TEXT_TYPES = ("character varying", "text", "character", "varchar")
NULL_SQL = " OR ".join(["{col} IS NULL", "NULLIF(TRIM({col}::text), '') IS NULL"])


def run_table_analysis(question: str, table_name: str, analysis_mode: str = "auto") -> dict[str, Any]:
    if not table_name.startswith("csv_"):
        raise PermissionError("只允许分析 csv_ 前缀的导入表。")
    if not table_exists(table_name):
        raise ValueError(f"表 {table_name} 不存在。")

    state: GenericTableState = {
        "question": question.strip(),
        "table_name": table_name,
        "analysis_mode": analysis_mode,
        "run_id": str(uuid.uuid4()),
        "steps": [],
        "plan": [],
        "schema_profile": {},
        "sql_queries": [],
        "metrics": [],
        "attribution": {},
        "charts": [],
        "report": {},
        "errors": [],
    }
    for node in (
        schema_profiler_node,
        intent_node,
        generic_sql_node,
        generic_executor_node,
        generic_analysis_node,
        generic_visualization_node,
        generic_report_node,
    ):
        state = node(state)
        if state.get("errors"):
            break

    response = {
        "question": state["question"],
        "table_name": state["table_name"],
        "run_id": state["run_id"],
        "status": "failed" if state.get("errors") else "completed",
        "steps": state.get("steps", []),
        "plan": state.get("plan", []),
        "knowledge": [
            {
                "source": "schema_profile",
                "content": _profile_summary(state.get("schema_profile", {})),
            }
        ],
        "sql_queries": state.get("sql_queries", []),
        "metrics": state.get("metrics", []),
        "attribution": state.get("attribution", {}),
        "charts": state.get("charts", []),
        "report": state.get("report", {}),
        "errors": state.get("errors", []),
    }
    save_analysis_result(response)
    return response


def _node(state: GenericTableState, name: str, work) -> GenericTableState:
    started = time.perf_counter()
    try:
        summary = work()
        status = "completed"
    except Exception as exc:
        status = "failed"
        summary = str(exc)
        state.setdefault("errors", []).append({"node": name, "message": str(exc)})
    state.setdefault("steps", []).append({
        "name": name,
        "status": status,
        "summary": summary,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    })
    return state


def schema_profiler_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        table = state["table_name"]
        table_q = quote_identifier(table)
        columns = _load_columns(table)
        row_count = _first_value(f"SELECT COUNT(*) AS cnt FROM {table_q}") or 0
        sample = execute_sql(f"SELECT * FROM {table_q} LIMIT 20")
        for col in columns:
            col_q = quote_identifier(col["name"])
            col["role"] = _role_for(col)
            col["semantic_type"] = _semantic_for(col)
            col["null_count"] = int(_first_value(
                f"SELECT COUNT(*) FILTER (WHERE {NULL_SQL.format(col=col_q)}) AS cnt FROM {table_q}"
            ) or 0)
            if col["role"] in {"dimension", "date", "numeric"}:
                distinct = _first_value(f"SELECT COUNT(DISTINCT {col_q}) AS cnt FROM {table_q}")
                col["distinct_count"] = int(distinct or 0)
        state["schema_profile"] = {
            "table_name": table,
            "row_count": row_count,
            "columns": columns,
            "sample": sample,
        }
        return f"读取 {len(columns)} 个字段、{row_count} 行样本和字段统计。"

    return _node(state, "schema_profiler", work)


def intent_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        question = state["question"]
        profile = state["schema_profile"]
        date_col = _pick_column(profile, "date", question)
        metric_col = _pick_column(profile, "numeric", question)
        dim_col = _pick_dimension(profile, question)
        if any(word in question for word in ("缺失", "空值", "为空", "完整")):
            intent = "missing"
        elif any(word in question for word in ("异常", "离群", "极端")):
            intent = "anomaly"
        elif date_col and metric_col and any(word in question for word in ("趋势", "月份", "月", "变化", "下降", "上升", "为什么")):
            intent = "trend"
        elif dim_col and metric_col and any(word in question for word in ("哪个", "哪些", "最多", "最少", "排名", "类别", "分类", "分组", "为什么")):
            intent = "group_compare"
        elif metric_col:
            intent = "distribution"
        else:
            intent = "profile"
        state["plan"] = [
            {"id": "schema_profile", "purpose": "识别表结构、字段角色和样本数据"},
            {"id": intent, "purpose": _intent_label(intent)},
        ]
        profile["selected"] = {
            "intent": intent,
            "date_column": date_col,
            "metric_column": metric_col,
            "dimension_column": dim_col,
        }
        return f"识别为 {intent} 分析，选择日期={date_col or '无'}、指标={metric_col or '无'}、维度={dim_col or '无'}。"

    return _node(state, "intent", work)


def generic_sql_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        table_q = quote_identifier(state["table_name"])
        selected = state["schema_profile"]["selected"]
        intent = selected["intent"]
        queries = [_overview_query(table_q)]
        if intent == "missing":
            queries.append(_missing_query(table_q, state["schema_profile"]["columns"]))
        elif intent == "trend":
            queries.append(_trend_query(table_q, selected["date_column"], selected["metric_column"]))
            if selected["dimension_column"]:
                queries.append(_group_query(table_q, selected["dimension_column"], selected["metric_column"]))
        elif intent == "group_compare":
            queries.append(_group_query(table_q, selected["dimension_column"], selected["metric_column"]))
        elif intent == "anomaly":
            if selected["metric_column"]:
                queries.append(_anomaly_query(table_q, selected["metric_column"]))
            queries.append(_missing_query(table_q, state["schema_profile"]["columns"]))
        elif intent == "distribution":
            queries.append(_distribution_query(table_q, selected["metric_column"]))
        else:
            queries.append(_missing_query(table_q, state["schema_profile"]["columns"]))
            dim = selected["dimension_column"]
            if dim:
                queries.append(_frequency_query(table_q, dim))
        state["sql_queries"] = queries
        return f"生成 {len(queries)} 条面向导入表的只读 SQL。"

    return _node(state, "generic_sql", work)


def generic_executor_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        executed = []
        for query in state["sql_queries"]:
            sql = " ".join(query["sql"].split())
            is_safe, reason = validate_sql(sql)
            if not is_safe:
                raise ValueError(f"{query['id']} 未通过 SQL 安全校验: {reason}")
            executed.append({**query, "sql": sql, **execute_sql(sql)})
        state["sql_queries"] = executed
        return f"执行 {len(executed)} 条导入表查询。"

    return _node(state, "executor", work)


def generic_analysis_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        profile = state["schema_profile"]
        selected = profile["selected"]
        metrics = [{"name": "行数", "previous": 0, "current": profile["row_count"], "change": profile["row_count"], "change_rate": 0}]
        attribution: dict[str, Any] = {}
        for query in state["sql_queries"]:
            rows = _rows(query)
            if query["id"] == "trend" and rows:
                first = float(rows[0].get("指标值") or 0)
                last = float(rows[-1].get("指标值") or 0)
                metrics.append({
                    "name": selected["metric_column"] or "指标",
                    "previous": first,
                    "current": last,
                    "change": last - first,
                    "change_rate": (last - first) / first if first else 0,
                })
                attribution["trend"] = _trend_changes(rows)
            elif query["id"] == "group_compare":
                attribution["group_compare"] = rows[:10]
            elif query["id"] == "missing":
                attribution["missing"] = rows[:10]
            elif query["id"] == "anomaly":
                attribution["anomaly"] = rows[:10]
            elif query["id"] == "distribution" and rows:
                row = rows[0]
                metrics.extend([
                    {"name": "平均值", "previous": 0, "current": row.get("平均值") or 0, "change": row.get("平均值") or 0, "change_rate": 0},
                    {"name": "最小值", "previous": 0, "current": row.get("最小值") or 0, "change": row.get("最小值") or 0, "change_rate": 0},
                    {"name": "最大值", "previous": 0, "current": row.get("最大值") or 0, "change": row.get("最大值") or 0, "change_rate": 0},
                ])
        state["metrics"] = metrics
        state["attribution"] = attribution
        return f"计算 {len(metrics)} 个摘要指标和 {len(attribution)} 类分析结果。"

    return _node(state, "generic_analysis", work)


def generic_visualization_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        charts = []
        for query in state["sql_queries"]:
            rows = _rows(query)
            if not rows:
                continue
            if query["id"] == "trend":
                charts.append({
                    "title": query["purpose"],
                    "type": "line",
                    "echarts_option": _line_chart(
                        [str(row["周期"]) for row in rows],
                        [{"name": "指标值", "data": [row["指标值"] for row in rows]}],
                    ),
                })
            elif query["id"] in {"group_compare", "frequency"}:
                charts.append({
                    "title": query["purpose"],
                    "type": "bar",
                    "echarts_option": _bar_chart(
                        [str(row["维度"]) for row in rows[:12]],
                        [{"name": "指标值", "data": [row.get("指标值", row.get("记录数", 0)) for row in rows[:12]]}],
                    ),
                })
            elif query["id"] == "missing":
                charts.append({
                    "title": "字段缺失率",
                    "type": "bar",
                    "echarts_option": _bar_chart(
                        [str(row["字段"]) for row in rows[:12]],
                        [{"name": "缺失率", "data": [row["缺失率"] for row in rows[:12]]}],
                    ),
                })
        state["charts"] = charts
        return f"生成 {len(charts)} 个通用图表。"

    return _node(state, "visualization", work)


def generic_report_node(state: GenericTableState) -> GenericTableState:
    def work() -> str:
        profile = state["schema_profile"]
        selected = profile["selected"]
        intent = selected["intent"]
        findings = []
        recommendations = []
        summary = f"已分析导入表 {state['table_name']}，共 {profile['row_count']} 行。"
        if intent == "trend" and state["metrics"][1:]:
            metric = state["metrics"][1]
            direction = "上升" if metric["change"] > 0 else "下降" if metric["change"] < 0 else "基本持平"
            summary += f" {selected['metric_column']} 从首期到末期{direction}，变化 {metric['change']:.2f}。"
            findings.append(f"趋势分析使用 {selected['date_column']} 作为时间列、{selected['metric_column']} 作为指标列。")
            if state["attribution"].get("group_compare"):
                top = state["attribution"]["group_compare"][0]
                findings.append(f"分组贡献最高的是 {top['维度']}，指标值为 {top['指标值']}。")
        elif intent == "group_compare" and state["attribution"].get("group_compare"):
            top = state["attribution"]["group_compare"][0]
            summary += f" 最高分组是 {top['维度']}，指标值为 {top['指标值']}。"
            findings.append(f"按 {selected['dimension_column']} 对 {selected['metric_column']} 做分组对比。")
        elif intent == "missing" and state["attribution"].get("missing"):
            top = state["attribution"]["missing"][0]
            summary += f" 缺失最严重字段是 {top['字段']}，缺失率 {top['缺失率']:.2%}。"
            findings.append("缺失率按 NULL 和空字符串统一统计。")
        elif intent == "anomaly" and state["attribution"].get("anomaly"):
            top = state["attribution"]["anomaly"][0]
            summary += f" 发现数值异常候选，最高值为 {top.get('指标值')}。"
            findings.append(f"异常检测基于 {selected['metric_column']} 的均值和标准差做初筛。")
        else:
            summary += " 当前字段不足以做强业务归因，已返回可执行的结构画像。"
            findings.append("如果需要回答严格的“为什么”，建议提供时间列、指标列和可解释的分类维度列。")
        recommendations = _recommendations(intent, selected)
        state["report"] = {
            "summary": summary,
            "findings": findings,
            "recommendations": recommendations,
            "markdown": _markdown(summary, findings, recommendations),
        }
        return "生成导入表分析报告，包含证据和限制说明。"

    return _node(state, "report", work)


def _load_columns(table_name: str) -> list[dict[str, Any]]:
    result = execute_sql(f"""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = '{table_name.replace("'", "''")}'
        ORDER BY ordinal_position
    """)
    return [
        {"name": row[0], "data_type": row[1], "nullable": row[2] == "YES"}
        for row in result["data"]
        if row[0] not in {"_imported_at"}
    ]


def _first_value(sql: str) -> Any:
    result = execute_sql(sql)
    return result["data"][0][0] if result["data"] else None


def _role_for(col: dict[str, Any]) -> str:
    name = col["name"].lower()
    typ = col["data_type"].lower()
    if name in {"_id", "id"} or name.endswith("_id") or any(token in col["name"] for token in ("编号", "编码", "学号", "工号", "单号")):
        return "id"
    if any(t in typ for t in DATE_TYPES) or any(token in col["name"] for token in ("日期", "时间", "月份")) or any(token in name for token in ("date", "time", "month")):
        return "date"
    if any(t in typ for t in NUMERIC_TYPES):
        return "numeric"
    if any(t in typ for t in TEXT_TYPES):
        return "dimension"
    return "other"


def _semantic_for(col: dict[str, Any]) -> str:
    name = col["name"].lower()
    raw = col["name"]
    if col["role"] == "date":
        return "date"
    if any(token in raw for token in ("金额", "销售额", "收入", "价格", "费用", "成本", "利润")) or any(token in name for token in ("amount", "sales", "revenue", "price", "cost", "profit")):
        return "money"
    if any(token in raw for token in ("数量", "人数", "次数", "库存")) or any(token in name for token in ("qty", "quantity", "count", "stock")):
        return "quantity"
    if any(token in raw for token in ("地区", "省", "市", "城市", "区域")) or any(token in name for token in ("region", "province", "city")):
        return "geo"
    if any(token in raw for token in ("渠道", "来源")) or "channel" in name:
        return "channel"
    if any(token in raw for token in ("类别", "品类", "类型", "状态")) or any(token in name for token in ("category", "type", "status")):
        return "category"
    return col["role"]


def _pick_column(profile: dict[str, Any], role: str, question: str) -> str | None:
    candidates = [col for col in profile["columns"] if col["role"] == role]
    if not candidates:
        return None
    for col in candidates:
        if col["name"] in question:
            return col["name"]
    if role == "numeric":
        preferred_semantics = ["money", "quantity", "numeric"]
        for semantic in preferred_semantics:
            for col in candidates:
                if col["semantic_type"] == semantic:
                    return col["name"]
    return candidates[0]["name"]


def _pick_dimension(profile: dict[str, Any], question: str) -> str | None:
    candidates = [col for col in profile["columns"] if col["role"] == "dimension"]
    for col in candidates:
        if col["name"] in question:
            return col["name"]
    preferred = ["category", "channel", "geo", "dimension"]
    for semantic in preferred:
        for col in candidates:
            if col["semantic_type"] == semantic and 1 < col.get("distinct_count", 0) <= 50:
                return col["name"]
    return candidates[0]["name"] if candidates else None


def _overview_query(table_q: str) -> dict[str, str]:
    return {
        "id": "overview",
        "purpose": "表级数据概览",
        "sql": f'SELECT COUNT(*) AS "行数" FROM {table_q}',
    }


def _missing_query(table_q: str, columns: list[dict[str, Any]]) -> dict[str, str]:
    parts = []
    for col in columns[:30]:
        col_q = quote_identifier(col["name"])
        parts.append(
            f"""SELECT '{col['name'].replace("'", "''")}' AS "字段",
                       COUNT(*) FILTER (WHERE {NULL_SQL.format(col=col_q)}) AS "缺失数",
                       ROUND((COUNT(*) FILTER (WHERE {NULL_SQL.format(col=col_q)}))::numeric / NULLIF(COUNT(*), 0), 4) AS "缺失率"
                FROM {table_q}"""
        )
    return {"id": "missing", "purpose": "字段缺失率检查", "sql": " UNION ALL ".join(parts) + ' ORDER BY "缺失率" DESC, "缺失数" DESC'}


def _trend_query(table_q: str, date_col: str, metric_col: str) -> dict[str, str]:
    date_q = quote_identifier(date_col)
    metric_q = quote_identifier(metric_col)
    return {
        "id": "trend",
        "purpose": f"按月份观察 {metric_col} 变化",
        "sql": f"""
            SELECT date_trunc('month', {date_q}::timestamp)::date AS "周期",
                   ROUND(SUM({metric_q})::numeric, 2) AS "指标值",
                   COUNT(*) AS "记录数"
            FROM {table_q}
            WHERE {date_q} IS NOT NULL AND {metric_q} IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        """,
    }


def _group_query(table_q: str, dim_col: str, metric_col: str) -> dict[str, str]:
    dim_q = quote_identifier(dim_col)
    metric_q = quote_identifier(metric_col)
    return {
        "id": "group_compare",
        "purpose": f"按 {dim_col} 对比 {metric_col}",
        "sql": f"""
            SELECT COALESCE(NULLIF(TRIM({dim_q}::text), ''), '(空)') AS "维度",
                   ROUND(SUM({metric_q})::numeric, 2) AS "指标值",
                   COUNT(*) AS "记录数"
            FROM {table_q}
            WHERE {metric_q} IS NOT NULL
            GROUP BY 1
            ORDER BY "指标值" DESC
            LIMIT 20
        """,
    }


def _frequency_query(table_q: str, dim_col: str) -> dict[str, str]:
    dim_q = quote_identifier(dim_col)
    return {
        "id": "frequency",
        "purpose": f"{dim_col} 分布",
        "sql": f"""
            SELECT COALESCE(NULLIF(TRIM({dim_q}::text), ''), '(空)') AS "维度",
                   COUNT(*) AS "记录数"
            FROM {table_q}
            GROUP BY 1
            ORDER BY "记录数" DESC
            LIMIT 20
        """,
    }


def _anomaly_query(table_q: str, metric_col: str) -> dict[str, str]:
    metric_q = quote_identifier(metric_col)
    return {
        "id": "anomaly",
        "purpose": f"{metric_col} 异常值候选",
        "sql": f"""
            WITH stats AS (
                SELECT AVG({metric_q}) AS avg_v, STDDEV_POP({metric_q}) AS std_v
                FROM {table_q}
                WHERE {metric_q} IS NOT NULL
            )
            SELECT {metric_q} AS "指标值",
                   ROUND(({metric_q} - stats.avg_v)::numeric / NULLIF(stats.std_v, 0), 4) AS "z_score"
            FROM {table_q}, stats
            WHERE {metric_q} IS NOT NULL
            ORDER BY ABS(({metric_q} - stats.avg_v) / NULLIF(stats.std_v, 0)) DESC NULLS LAST
            LIMIT 20
        """,
    }


def _distribution_query(table_q: str, metric_col: str) -> dict[str, str]:
    metric_q = quote_identifier(metric_col)
    return {
        "id": "distribution",
        "purpose": f"{metric_col} 分布摘要",
        "sql": f"""
            SELECT ROUND(AVG({metric_q})::numeric, 2) AS "平均值",
                   ROUND(MIN({metric_q})::numeric, 2) AS "最小值",
                   ROUND(MAX({metric_q})::numeric, 2) AS "最大值",
                   COUNT({metric_q}) AS "有效记录数"
            FROM {table_q}
        """,
    }


def _rows(query: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(query["columns"], row)) for row in query.get("data", [])]


def _trend_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for prev, cur in zip(rows, rows[1:]):
        previous = float(prev.get("指标值") or 0)
        current = float(cur.get("指标值") or 0)
        change = current - previous
        result.append({
            "周期": cur.get("周期"),
            "previous": previous,
            "current": current,
            "change": change,
            "change_rate": change / previous if previous else 0,
        })
    return result


def _intent_label(intent: str) -> str:
    return {
        "missing": "检查字段缺失和数据完整性",
        "anomaly": "检测数值异常和缺失问题",
        "trend": "按时间观察指标变化并解释方向",
        "group_compare": "按维度做分组贡献和排名",
        "distribution": "计算数值指标分布摘要",
        "profile": "生成表结构画像和可分析方向",
    }.get(intent, "通用分析")


def _recommendations(intent: str, selected: dict[str, Any]) -> list[str]:
    if intent == "trend":
        return [
            "如果要进一步回答严格归因，建议补充可解释维度列，如地区、渠道、类别或状态。",
            "对下降周期继续按主要维度下钻，比较各分组对总变化的贡献。",
        ]
    if intent == "missing":
        return [
            "优先确认高缺失字段是否为业务上允许为空，避免直接参与指标计算。",
            "导入前可补充字段说明，帮助 Agent 区分未知、无和未填写。",
        ]
    if intent == "anomaly":
        return [
            "异常值只是统计候选，需要结合原始记录核对是否为录入错误、极端业务事件或真实波动。",
            "建议增加日期或分类维度，定位异常集中在哪个时间段或分组。",
        ]
    if intent == "group_compare":
        return [
            f"优先检查 {selected.get('dimension_column') or '主要维度'} 头部分组与尾部分组的差异来源。",
            "如果要回答为什么变化，建议加入时间列后做分组环比贡献分析。",
        ]
    return [
        "当前字段不足以做强归因，可先补充时间列、数值指标列和业务维度列。",
        "建议为 CSV 使用清晰列名，例如日期、销售额、地区、渠道、类别。",
    ]


def _line_chart(categories: list[str], series: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0},
        "grid": {"left": "4%", "right": "4%", "top": "10%", "bottom": "14%", "containLabel": True},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": [{**item, "type": "line", "smooth": True} for item in series],
    }


def _bar_chart(categories: list[str], series: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0},
        "grid": {"left": "4%", "right": "4%", "top": "10%", "bottom": "14%", "containLabel": True},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": [{**item, "type": "bar"} for item in series],
    }


def _markdown(summary: str, findings: list[str], recommendations: list[str]) -> str:
    lines = ["# CSV 通用分析报告", "", "## 摘要", summary, "", "## 关键发现"]
    lines.extend(f"- {item}" for item in findings)
    lines.extend(["", "## 建议动作"])
    lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines)


def _profile_summary(profile: dict[str, Any]) -> str:
    if not profile:
        return ""
    selected = profile.get("selected", {})
    return (
        f"表 {profile.get('table_name')} 共 {profile.get('row_count')} 行，"
        f"识别意图 {selected.get('intent')}，"
        f"时间列 {selected.get('date_column') or '无'}，"
        f"指标列 {selected.get('metric_column') or '无'}，"
        f"维度列 {selected.get('dimension_column') or '无'}。"
    )
