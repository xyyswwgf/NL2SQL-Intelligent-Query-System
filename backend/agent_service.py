from __future__ import annotations

import time
import uuid
from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # LangGraph is optional at runtime; the fallback remains deterministic.
    END = None
    StateGraph = None

from backend.database import execute_sql
from backend.sql_guard import validate_sql


CURRENT_MONTH = "2026-06"
PREVIOUS_MONTH = "2026-05"
ANALYSIS_HISTORY: dict[str, dict[str, Any]] = {}


class AgentState(TypedDict, total=False):
    question: str
    analysis_mode: str
    run_id: str
    steps: list[dict[str, Any]]
    plan: list[dict[str, str]]
    knowledge: list[dict[str, str]]
    sql_queries: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    attribution: dict[str, Any]
    charts: list[dict[str, Any]]
    report: dict[str, Any]
    errors: list[dict[str, str]]


def run_analysis(question: str, analysis_mode: str = "auto") -> dict[str, Any]:
    state: AgentState = {
        "question": question.strip(),
        "analysis_mode": analysis_mode,
        "run_id": str(uuid.uuid4()),
        "steps": [],
        "plan": [],
        "knowledge": [],
        "sql_queries": [],
        "metrics": [],
        "attribution": {},
        "charts": [],
        "report": {},
        "errors": [],
    }

    if StateGraph is not None:
        graph = _build_graph()
        state = graph.invoke(state)
    else:
        for node in (
            planner_node,
            knowledge_node,
            sql_node,
            executor_node,
            analysis_node,
            attribution_node,
            visualization_node,
            report_node,
        ):
            state = node(state)

    response = {
        "question": state["question"],
        "run_id": state["run_id"],
        "status": "failed" if state.get("errors") else "completed",
        "steps": state.get("steps", []),
        "plan": state.get("plan", []),
        "knowledge": state.get("knowledge", []),
        "sql_queries": state.get("sql_queries", []),
        "metrics": state.get("metrics", []),
        "attribution": state.get("attribution", {}),
        "charts": state.get("charts", []),
        "report": state.get("report", {}),
        "errors": state.get("errors", []),
    }
    save_analysis_result(response)
    return response


def save_analysis_result(response: dict[str, Any]) -> None:
    ANALYSIS_HISTORY[response["run_id"]] = response


def list_history() -> list[dict[str, str]]:
    items = list(ANALYSIS_HISTORY.values())[-20:]
    return [
        {
            "run_id": item["run_id"],
            "question": item["question"],
            "status": item["status"],
            "summary": item.get("report", {}).get("summary", ""),
        }
        for item in reversed(items)
    ]


def get_history_detail(run_id: str) -> dict[str, Any] | None:
    return ANALYSIS_HISTORY.get(run_id)


def export_report(run_id: str, export_format: str = "markdown") -> tuple[str, str, str] | None:
    detail = get_history_detail(run_id)
    if not detail:
        return None

    markdown = detail.get("report", {}).get("markdown") or _markdown(
        detail.get("report", {}).get("summary", ""),
        detail.get("report", {}).get("findings", []),
        detail.get("report", {}).get("recommendations", []),
    )
    safe_run_id = run_id.replace("/", "_")
    if export_format == "html":
        html = _html_report(detail, markdown)
        return html, "text/html; charset=utf-8", f"analysis_{safe_run_id}.html"
    return markdown, "text/markdown; charset=utf-8", f"analysis_{safe_run_id}.md"


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("sql", sql_node)
    graph.add_node("executor", executor_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("attribution", attribution_node)
    graph.add_node("visualization", visualization_node)
    graph.add_node("report", report_node)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "knowledge")
    graph.add_edge("knowledge", "sql")
    graph.add_edge("sql", "executor")
    graph.add_edge("executor", "analysis")
    graph.add_edge("analysis", "attribution")
    graph.add_edge("attribution", "visualization")
    graph.add_edge("visualization", "report")
    graph.add_edge("report", END)
    return graph.compile()


def _node(state: AgentState, name: str, work) -> AgentState:
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


def planner_node(state: AgentState) -> AgentState:
    def work() -> str:
        question = state["question"]
        plan = [
            {"id": "monthly_trend", "purpose": "对比 2026-05 与 2026-06 核心经营指标"},
            {"id": "region_attribution", "purpose": "按省份定位 GMV 下降来源"},
            {"id": "category_attribution", "purpose": "按品类拆解销售、成本和退款"},
            {"id": "channel_roi", "purpose": "按渠道计算净销售额、营销花费和 ROI"},
            {"id": "traffic_conversion", "purpose": "检查渠道和大区转化率变化"},
        ]
        if any(word in question for word in ("退款", "售后", "退货")):
            plan.insert(3, {"id": "refund_focus", "purpose": "重点检查退款率异常品类"})
        if any(word in question for word in ("华北", "北京")):
            plan.append({"id": "north_focus", "purpose": "重点检查华北和北京市场"})
        state["plan"] = plan
        return f"生成 {len(plan)} 个分析步骤，覆盖趋势、归因、ROI 和转化。"

    return _node(state, "planner", work)


def knowledge_node(state: AgentState) -> AgentState:
    def work() -> str:
        keywords = [kw for kw in ("GMV", "净销售额", "毛利", "退款", "ROI", "华北", "高价值用户", "销售下降") if kw in state["question"]]
        if not keywords:
            keywords = ["GMV", "销售下降", "ROI", "退款"]
        clauses = " OR ".join([f"keywords ILIKE '%{kw}%'" for kw in keywords])
        result = execute_sql(
            f"SELECT source, content FROM knowledge_chunks WHERE {clauses} ORDER BY chunk_id LIMIT 6"
        )
        state["knowledge"] = [
            {"source": row[0], "content": row[1]}
            for row in result["data"]
        ]
        return f"检索到 {len(state['knowledge'])} 条业务知识。"

    return _node(state, "knowledge", work)


def sql_node(state: AgentState) -> AgentState:
    def work() -> str:
        state["sql_queries"] = [
            {
                "id": "monthly_trend",
                "purpose": "月度核心指标趋势",
                "sql": """
                    SELECT d.month_label AS "月份",
                           ROUND(SUM(o.order_amount), 2) AS "GMV",
                           COUNT(*) AS "订单数",
                           ROUND(AVG(o.order_amount), 2) AS "客单价",
                           ROUND(SUM(o.product_cost), 2) AS "商品成本",
                           ROUND(COALESCE(SUM(r.refund_amount), 0), 2) AS "退款金额",
                           ROUND(SUM(o.order_amount) - COALESCE(SUM(r.refund_amount), 0), 2) AS "净销售额",
                           ROUND((SUM(o.order_amount) - SUM(o.product_cost) - COALESCE(SUM(r.refund_amount), 0)) / NULLIF(SUM(o.order_amount), 0), 4) AS "毛利率"
                    FROM fact_orders o
                    JOIN dim_date d ON d.date_id = o.order_date
                    LEFT JOIN fact_refunds r ON r.order_id = o.order_id
                    WHERE d.month_label IN ('2026-05', '2026-06')
                    GROUP BY d.month_label
                    ORDER BY d.month_label
                """,
            },
            {
                "id": "region_attribution",
                "purpose": "地区 GMV 变化贡献",
                "sql": """
                    SELECT r.region_name AS "大区", r.province AS "省份", d.month_label AS "月份",
                           ROUND(SUM(o.order_amount), 2) AS "GMV"
                    FROM fact_orders o
                    JOIN dim_date d ON d.date_id = o.order_date
                    JOIN dim_region r ON r.region_id = o.region_id
                    WHERE d.month_label IN ('2026-05', '2026-06')
                    GROUP BY r.region_name, r.province, d.month_label
                    ORDER BY r.region_name, r.province, d.month_label
                """,
            },
            {
                "id": "category_attribution",
                "purpose": "品类销售、成本、退款拆解",
                "sql": """
                    SELECT p.category AS "品类", d.month_label AS "月份",
                           ROUND(SUM(o.order_amount), 2) AS "GMV",
                           ROUND(SUM(o.product_cost), 2) AS "商品成本",
                           ROUND(COALESCE(SUM(r.refund_amount), 0), 2) AS "退款金额",
                           ROUND(COALESCE(SUM(r.refund_amount), 0) / NULLIF(SUM(o.order_amount), 0), 4) AS "退款率"
                    FROM fact_orders o
                    JOIN dim_date d ON d.date_id = o.order_date
                    JOIN dim_product p ON p.product_id = o.product_id
                    LEFT JOIN fact_refunds r ON r.order_id = o.order_id
                    WHERE d.month_label IN ('2026-05', '2026-06')
                    GROUP BY p.category, d.month_label
                    ORDER BY p.category, d.month_label
                """,
            },
            {
                "id": "channel_roi",
                "purpose": "渠道 ROI 变化",
                "sql": """
                    WITH sales AS (
                        SELECT o.channel_id, d.month_label,
                               SUM(o.order_amount) AS gmv,
                               COALESCE(SUM(r.refund_amount), 0) AS refunds
                        FROM fact_orders o
                        JOIN dim_date d ON d.date_id = o.order_date
                        LEFT JOIN fact_refunds r ON r.order_id = o.order_id
                        WHERE d.month_label IN ('2026-05', '2026-06')
                        GROUP BY o.channel_id, d.month_label
                    ),
                    spend AS (
                        SELECT ms.channel_id, d.month_label, SUM(ms.spend_amount) AS spend
                        FROM fact_marketing_spend ms
                        JOIN dim_date d ON d.date_id = ms.spend_date
                        WHERE d.month_label IN ('2026-05', '2026-06')
                        GROUP BY ms.channel_id, d.month_label
                    )
                    SELECT c.channel_name AS "渠道", s.month_label AS "月份",
                           ROUND(s.gmv - s.refunds, 2) AS "净销售额",
                           ROUND(sp.spend, 2) AS "营销花费",
                           ROUND((s.gmv - s.refunds) / NULLIF(sp.spend, 0), 4) AS "ROI"
                    FROM sales s
                    JOIN spend sp ON sp.channel_id = s.channel_id AND sp.month_label = s.month_label
                    JOIN dim_channel c ON c.channel_id = s.channel_id
                    ORDER BY c.channel_name, s.month_label
                """,
            },
            {
                "id": "traffic_conversion",
                "purpose": "渠道转化率变化",
                "sql": """
                    SELECT c.channel_name AS "渠道", r.region_name AS "大区", d.month_label AS "月份",
                           SUM(t.visits) AS "访问量",
                           SUM(t.paid_orders) AS "支付订单数",
                           ROUND(SUM(t.paid_orders)::numeric / NULLIF(SUM(t.visits), 0), 4) AS "转化率"
                    FROM fact_daily_traffic t
                    JOIN dim_date d ON d.date_id = t.traffic_date
                    JOIN dim_channel c ON c.channel_id = t.channel_id
                    JOIN dim_region r ON r.region_id = t.region_id
                    WHERE d.month_label IN ('2026-05', '2026-06')
                    GROUP BY c.channel_name, r.region_name, d.month_label
                    ORDER BY c.channel_name, r.region_name, d.month_label
                """,
            },
        ]
        return f"生成 {len(state['sql_queries'])} 条 PostgreSQL 分析 SQL。"

    return _node(state, "sql", work)


def executor_node(state: AgentState) -> AgentState:
    def work() -> str:
        executed = []
        for query in state["sql_queries"]:
            sql = " ".join(query["sql"].split())
            is_safe, reason = validate_sql(sql)
            if not is_safe:
                raise ValueError(f"{query['id']} 未通过 SQL 安全校验: {reason}")
            executed.append({**query, "sql": sql, **execute_sql(sql)})
        state["sql_queries"] = executed
        return f"执行 {len(executed)} 条只读查询。"

    return _node(state, "executor", work)


def analysis_node(state: AgentState) -> AgentState:
    def work() -> str:
        monthly = _rows(_query(state, "monthly_trend"))
        by_month = {row["月份"]: row for row in monthly}
        previous = by_month.get(PREVIOUS_MONTH, {})
        current = by_month.get(CURRENT_MONTH, {})
        metrics = []
        for name in ("GMV", "订单数", "客单价", "商品成本", "退款金额", "净销售额", "毛利率"):
            prev = float(previous.get(name) or 0)
            cur = float(current.get(name) or 0)
            change = cur - prev
            metrics.append({
                "name": name,
                "previous": prev,
                "current": cur,
                "change": change,
                "change_rate": change / prev if prev else 0,
            })
        state["metrics"] = metrics
        return f"计算 {len(metrics)} 个核心指标。"

    return _node(state, "analysis", work)


def attribution_node(state: AgentState) -> AgentState:
    def work() -> str:
        state["attribution"] = {
            "region": _contribution(_rows(_query(state, "region_attribution")), "省份", "GMV"),
            "category": _contribution(_rows(_query(state, "category_attribution")), "品类", "GMV"),
            "refund": _change(_rows(_query(state, "category_attribution")), "品类", "退款率", reverse=True),
            "roi": _change(_rows(_query(state, "channel_roi")), "渠道", "ROI"),
            "conversion_north": _change(
                [row for row in _rows(_query(state, "traffic_conversion")) if row.get("大区") == "华北"],
                "渠道",
                "转化率",
            ),
        }
        return "完成地区、品类、退款率、ROI 和华北转化率归因。"

    return _node(state, "attribution", work)


def visualization_node(state: AgentState) -> AgentState:
    def work() -> str:
        monthly = _rows(_query(state, "monthly_trend"))
        region = state["attribution"]["region"][:8]
        roi = state["attribution"]["roi"]
        state["charts"] = [
            {
                "title": "月度 GMV 与净销售额",
                "type": "line",
                "echarts_option": _line_chart(
                    [row["月份"] for row in monthly],
                    [
                        {"name": "GMV", "data": [row["GMV"] for row in monthly]},
                        {"name": "净销售额", "data": [row["净销售额"] for row in monthly]},
                    ],
                ),
            },
            {
                "title": "省份 GMV 变化贡献",
                "type": "bar",
                "echarts_option": _bar_chart(
                    [row["省份"] for row in region],
                    [{"name": "GMV变化", "data": [round(row["change"], 2) for row in region]}],
                ),
            },
            {
                "title": "渠道 ROI 变化",
                "type": "bar",
                "echarts_option": _bar_chart(
                    [row["渠道"] for row in roi],
                    [{"name": "ROI变化", "data": [round(row["change"], 4) for row in roi]}],
                ),
            },
        ]
        return f"生成 {len(state['charts'])} 个图表配置。"

    return _node(state, "visualization", work)


def report_node(state: AgentState) -> AgentState:
    def work() -> str:
        question = state["question"]
        metrics = {item["name"]: item for item in state["metrics"]}
        attr = state["attribution"]
        top_region = attr["region"][0] if attr["region"] else None
        top_category = attr["category"][0] if attr["category"] else None
        top_refund = attr["refund"][0] if attr["refund"] else None
        top_roi = attr["roi"][0] if attr["roi"] else None

        if any(word in question for word in ("ROI", "roi", "渠道", "投放")) and top_roi:
            summary = (
                f"{CURRENT_MONTH} 渠道分析显示，{top_roi['渠道']} ROI 变化最明显，"
                f"从 {top_roi['previous']:.4f} 到 {top_roi['current']:.4f}，变化 {top_roi['change']:.4f}。"
            )
        elif any(word in question for word in ("退款", "退货", "售后")) and top_refund:
            summary = (
                f"{CURRENT_MONTH} 退款异常主要集中在{top_refund['品类']}，"
                f"退款率从 {top_refund['previous']:.2%} 升至 {top_refund['current']:.2%}。"
            )
        elif any(word in question for word in ("华北", "北京", "高价值用户")) and top_region:
            summary = (
                f"{CURRENT_MONTH} 华北/北京相关分析显示，{top_region['省份']}是主要拖累项，"
                f"GMV 从 {top_region['previous']:.2f} 到 {top_region['current']:.2f}，变化 {top_region['change']:.2f}。"
            )
        else:
            summary = (
                f"{CURRENT_MONTH} GMV 环比 {metrics['GMV']['change_rate']:.2%}，"
                f"净销售额环比 {metrics['净销售额']['change_rate']:.2%}。"
            )
            if top_region:
                summary += f" 最大拖累省份是{top_region['省份']}，GMV变化 {top_region['change']:.2f}。"

        findings = [
            _metric_sentence("GMV", metrics["GMV"]),
            _metric_sentence("净销售额", metrics["净销售额"]),
            _metric_sentence("退款金额", metrics["退款金额"]),
            _metric_sentence("毛利率", metrics["毛利率"], percent_value=True),
        ]
        if top_category:
            findings.append(f"{top_category['品类']}为品类侧最大变化来源，贡献度 {top_category['contribution']:.2%}。")
        if top_refund:
            findings.append(f"{top_refund['品类']}退款率最高，当前为 {top_refund['current']:.2%}。")
        if top_roi:
            findings.append(f"{top_roi['渠道']} ROI 变化最明显，从 {top_roi['previous']:.4f} 到 {top_roi['current']:.4f}。")

        recommendations = _recommendations_for(question, top_region, top_refund, top_roi)
        if not recommendations:
            recommendations = [
                "优先复盘北京/华北市场的商品供给、价格策略和投放转化漏斗。",
                "对退款率高的品类做售后原因拆解，单独监控退款金额对净销售额和毛利率的影响。",
                "将预算从 ROI 下滑渠道阶段性转向官网、天猫等稳定渠道，并按周复盘。",
            ]
        state["report"] = {
            "summary": summary,
            "findings": findings,
            "recommendations": recommendations,
            "markdown": _markdown(summary, findings, recommendations),
        }
        return "生成结构化报告和业务建议。"

    return _node(state, "report", work)


def _query(state: AgentState, query_id: str) -> dict[str, Any]:
    return next(item for item in state["sql_queries"] if item["id"] == query_id)


def _rows(query: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(query["columns"], row)) for row in query["data"]]


def _pivot(rows: list[dict[str, Any]], dimension: str, metric: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        key = str(row[dimension])
        buckets.setdefault(key, {})[str(row["月份"])] = float(row.get(metric) or 0)
    result = []
    for key, values in buckets.items():
        previous = values.get(PREVIOUS_MONTH, 0.0)
        current = values.get(CURRENT_MONTH, 0.0)
        change = current - previous
        result.append({
            dimension: key,
            "previous": previous,
            "current": current,
            "change": change,
            "change_rate": change / previous if previous else 0,
        })
    return result


def _contribution(rows: list[dict[str, Any]], dimension: str, metric: str) -> list[dict[str, Any]]:
    result = _pivot(rows, dimension, metric)
    total_change = sum(item["change"] for item in result)
    for item in result:
        item["contribution"] = item["change"] / total_change if total_change else 0
    return sorted(result, key=lambda item: item["change"])


def _change(rows: list[dict[str, Any]], dimension: str, metric: str, reverse: bool = False) -> list[dict[str, Any]]:
    return sorted(_pivot(rows, dimension, metric), key=lambda item: item["current"] if reverse else item["change"], reverse=reverse)


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


def _metric_sentence(name: str, metric: dict[str, Any], percent_value: bool = False) -> str:
    value_format = "{:.2%}" if percent_value else "{:.2f}"
    return (
        f"{name}从 {value_format.format(metric['previous'])} 变化到 "
        f"{value_format.format(metric['current'])}，环比 {metric['change_rate']:.2%}。"
    )


def _recommendations_for(
    question: str,
    top_region: dict[str, Any] | None,
    top_refund: dict[str, Any] | None,
    top_roi: dict[str, Any] | None,
) -> list[str]:
    if any(word in question for word in ("ROI", "roi", "渠道", "投放")):
        channel = top_roi["渠道"] if top_roi else "ROI 下滑渠道"
        return [
            f"优先复盘{channel}的投放人群、素材和落地页转化，暂停低 ROI 单元继续放量。",
            "用净销售额而不是 GMV 评估渠道效果，把退款影响纳入预算分配。",
            "保留小流量 A/B 测试，按周观察 ROI、转化率和客单价是否同步修复。",
        ]
    if any(word in question for word in ("退款", "退货", "售后")):
        category = top_refund["品类"] if top_refund else "高退款品类"
        return [
            f"对{category}抽样查看退款原因，区分质量、物流、描述不符和价格保护问题。",
            "把退款率、退款金额和毛利率放到同一张周报里，避免只看 GMV。",
            "对异常 SKU 设置售后预警阈值，必要时降低投放或临时下架问题批次。",
        ]
    if any(word in question for word in ("华北", "北京", "高价值用户")):
        province = top_region["省份"] if top_region else "华北重点省份"
        return [
            f"优先检查{province}的高价值用户复购、渠道转化和热销品供给是否同时走弱。",
            "针对华北做分渠道漏斗复盘，定位是访问下降、转化下降还是客单价下降。",
            "对高价值用户做定向召回，不建议先进行全站大额促销。",
        ]
    return []


def _markdown(summary: str, findings: list[str], recommendations: list[str]) -> str:
    lines = ["# 经营分析报告", "", "## 摘要", summary, "", "## 关键发现"]
    lines.extend(f"- {item}" for item in findings)
    lines.extend(["", "## 建议动作"])
    lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines)


def _html_report(detail: dict[str, Any], markdown: str) -> str:
    def esc(value: Any) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    metrics = detail.get("metrics", [])
    metric_rows = "\n".join(
        "<tr>"
        f"<td>{esc(item.get('name'))}</td>"
        f"<td>{esc(round(float(item.get('previous', 0)), 4))}</td>"
        f"<td>{esc(round(float(item.get('current', 0)), 4))}</td>"
        f"<td>{esc(round(float(item.get('change_rate', 0)) * 100, 2))}%</td>"
        "</tr>"
        for item in metrics
    )
    sql_blocks = "\n".join(
        f"<details><summary>{esc(item.get('purpose'))}</summary><pre>{esc(item.get('sql'))}</pre></details>"
        for item in detail.get("sql_queries", [])
    )
    paragraphs = "\n".join(
        f"<p>{esc(line)}</p>" if line and not line.startswith("- ") and not line.startswith("#")
        else f"<li>{esc(line[2:])}</li>" if line.startswith("- ")
        else f"<h2>{esc(line.lstrip('# ').strip())}</h2>" if line.startswith("#")
        else ""
        for line in markdown.splitlines()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>经营分析报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; color: #1f2937; }}
    h1, h2 {{ color: #111827; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    pre {{ white-space: pre-wrap; background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; }}
    details {{ margin: 10px 0; }}
  </style>
</head>
<body>
  <h1>经营分析报告</h1>
  <p><strong>问题：</strong>{esc(detail.get("question", ""))}</p>
  <p><strong>Run ID：</strong>{esc(detail.get("run_id", ""))}</p>
  {paragraphs}
  <h2>核心指标</h2>
  <table>
    <thead><tr><th>指标</th><th>上期</th><th>本期</th><th>环比</th></tr></thead>
    <tbody>{metric_rows}</tbody>
  </table>
  <h2>SQL 执行记录</h2>
  {sql_blocks}
</body>
</html>"""
