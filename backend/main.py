"""
=============================================================================
NL2SQL 智能查询系统 — FastAPI 入口
=============================================================================

核心链路:
  用户自然语言 → POST /api/query
    → llm_service.generate_sql()    # 大模型生成 SQL
    → sql_guard.validate_sql()       # 安全校验（防注入）
    → database.execute_sql()         # 执行查询
    → 返回 {sql, columns, data, row_count}

安全策略:
  - 纵深防御：LLM Prompt 约束 + 后端正则拦截，双重保障
  - 只允许 SELECT 查询，拒绝任何 DDL/DML/DCL 操作
  - 分号堆叠注入检测

启动方式:
  DB_PASSWORD=xxx uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
=============================================================================
"""

import time
import json
import logging
import re
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.llm_service import generate_sql
from backend.sql_guard import validate_sql
from backend.database import (
    execute_sql,
    get_table_names,
    quote_identifier,
    table_exists,
    drop_table,
)
from backend.csv_importer import (
    parse_csv,
    sanitize_column_name,
    infer_column_types,
    profile_import_file,
    create_table,
    insert_rows,
    derive_table_name,
    auto_detect_trailing_rows,
    auto_detect_header_row,
)
from backend.agent_service import run_analysis, list_history, get_history_detail, export_report
from backend.generic_table_agent import run_table_analysis
from backend.config import CSV_MAX_FILE_SIZE_MB, CSV_MAX_ROWS, CSV_BATCH_SIZE, DB_HOST, DB_PORT, DB_NAME

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nl2sql")

# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title="NL2SQL 智能查询系统",
    description="自然语言 → SQL → 数据可视化 | 企业级只读查询网关",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ---------------------------------------------------------------------------
# CORS 中间件 — 允许前端跨域访问
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """自然语言查询请求"""

    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="用户的自然语言问题，例如：'每种商品类别的总销售额？'",
        examples=["每种商品类别的总销售额是多少？"],
    )


class QueryResponse(BaseModel):
    """查询结果响应"""

    sql: str = Field(..., description="大模型生成并已执行的 SQL 语句")
    columns: list[str] = Field(..., description="结果列名列表")
    data: list[list] = Field(..., description="二维数据数组，每行是一个列表")
    row_count: int = Field(..., description="结果行数")


class ImportResponse(BaseModel):
    """CSV 导入结果响应"""

    table_name: str = Field(..., description="创建的数据库表名")
    original_filename: str = Field(..., description="上传的原始文件名")
    columns: list[dict] = Field(..., description="列信息列表 [{name, type, nullable}]")
    row_count: int = Field(..., description="导入的数据行数")
    message: str = Field(..., description="导入结果描述")


class TableInfo(BaseModel):
    """表信息"""

    table_name: str
    row_count: int
    imported: bool
    imported_at: str | None = None


class TableListResponse(BaseModel):
    """表列表响应"""

    tables: list[TableInfo]


class DeleteResponse(BaseModel):
    """删除表响应"""

    deleted: str = Field(..., description="被删除的表名")
    message: str = Field(..., description="操作结果描述")


class AnalyzeRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    analysis_mode: str = Field("auto", description="分析模式，当前默认 auto")


class TableAnalyzeRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    table_name: str = Field(..., min_length=1, max_length=128)
    analysis_mode: str = Field("auto", description="分析模式，当前默认 auto")


def _load_table_details() -> list[dict]:
    """Load table metadata using PostgreSQL-safe identifier quoting."""
    table_details = []
    for table_name in get_table_names():
        quoted_table = quote_identifier(table_name)
        result = execute_sql(f"SELECT COUNT(*) AS cnt FROM {quoted_table}")
        row_count = result["data"][0][0] if result["data"] else 0

        imported = table_name.startswith("csv_")
        imported_at = None
        if imported:
            try:
                time_result = execute_sql(
                    f"SELECT MIN(\"_imported_at\") AS t FROM {quoted_table}"
                )
                raw = time_result["data"][0][0] if time_result["data"] else None
                if raw:
                    imported_at = str(raw)
            except Exception:
                pass

        table_details.append({
            "table_name": table_name,
            "row_count": row_count,
            "imported": imported,
            "imported_at": imported_at,
        })
    return table_details


# ---------------------------------------------------------------------------
# 中间件：请求日志
# ---------------------------------------------------------------------------


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个请求的方法、路径和耗时"""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """
    健康检查接口

    可用于 Docker healthcheck、负载均衡探测、监控告警
    """
    return {
        "status": "healthy",
        "service": "NL2SQL",
        "version": "1.0.0",
    }


@app.get("/api/info")
async def data_source_info():
    """
    数据来源信息 — 告诉前端数据库里有什么、数据从哪来
    """
    return {
        "database": {
            "engine": "PostgreSQL 16",
            "host": f"{DB_HOST}:{DB_PORT}",
            "name": DB_NAME,
            "charset": "UTF8",
        },
        "tables": _load_table_details(),
        "pipeline": [
            {"step": 1, "actor": "用户", "action": "输入自然语言问题"},
            {"step": 2, "actor": "LLM 大模型", "action": "结合数据库 DDL 结构生成 SQL"},
            {"step": 3, "actor": "安全网关", "action": "校验 SQL，拦截危险操作"},
            {"step": 4, "actor": "PostgreSQL", "action": "执行 SELECT 查询"},
            {"step": 5, "actor": "前端", "action": "表格展示 + ECharts 智能图表"},
        ],
    }


@app.post("/api/query", response_model=QueryResponse)
async def natural_language_query(req: QueryRequest):
    """
    核心接口：自然语言 → 数据查询

    ---
    ## 处理流程

    ```
    用户自然语言
      │
      ▼
    ┌─────────────────────────────┐
    │ Step 1: LLM 生成 SQL        │  ← llm_service.generate_sql()
    │   - 提取最新数据库 DDL       │
    │   - 拼接 Prompt 发送给大模型  │
    │   - 从响应中提取纯 SQL       │
    └──────────────┬──────────────┘
                   ▼
    ┌─────────────────────────────┐
    │ Step 2: SQL 安全校验        │  ← sql_guard.validate_sql()
    │   - 必须以 SELECT 开头      │
    │   - 禁止 DROP/DELETE/UPDATE │
    │   - 检测分号堆叠注入        │
    └──────────────┬──────────────┘
                   ▼
    ┌─────────────────────────────┐
    │ Step 3: 执行查询            │  ← database.execute_sql()
    │   - 连接 PostgreSQL         │
    │   - 执行 SELECT             │
    │   - 格式化为 JSON           │
    └──────────────┬──────────────┘
                   ▼
            {sql, columns, data, row_count}
    ```

    ## 错误码

    | HTTP 状态码 | 含义 |
    |------------|------|
    | 200 | 查询成功 |
    | 400 | 问题无效或无法转为 SQL |
    | 403 | SQL 安全校验未通过（疑似注入） |
    | 500 | 数据库执行失败 |
    | 502 | LLM API 调用失败 |
    """
    question = req.question.strip()
    logger.info("收到查询: %s", question)

    # ---------------------------------------------------------------
    # Step 1: 调用 LLM 生成 SQL
    # ---------------------------------------------------------------
    try:
        sql = generate_sql(question)
        logger.info("LLM 生成 SQL: %s", sql[:200])
    except ValueError as exc:
        logger.warning("LLM 无法回答: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.error("LLM API 异常: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # ---------------------------------------------------------------
    # Step 2: SQL 安全校验（纵深防御）
    # ---------------------------------------------------------------
    is_safe, reason = validate_sql(sql)
    if not is_safe:
        logger.warning("SQL 安全拦截: %s — %s", reason, sql[:200])
        raise HTTPException(
            status_code=403,
            detail=f"SQL 安全校验未通过: {reason}。系统只允许 SELECT 查询。",
        )

    # ---------------------------------------------------------------
    # Step 3: 执行查询并返回结果
    # ---------------------------------------------------------------
    try:
        result = execute_sql(sql)
        logger.info("查询成功，返回 %d 行数据", result["row_count"])
    except Exception as exc:
        logger.error("SQL 执行失败: %s — %s", exc, sql[:200])
        raise HTTPException(
            status_code=500,
            detail=f"SQL 执行失败: {str(exc)}",
        )

    return QueryResponse(
        sql=sql,
        columns=result["columns"],
        data=result["data"],
        row_count=result["row_count"],
    )


@app.post("/api/analyze")
async def analyze_business_question(req: AnalyzeRequest):
    """
    数据智能 Agent 分析接口。

    该接口面向经营分析问题，会自动执行规划、知识检索、多条 SQL 查询、
    指标计算、归因分析、图表生成和报告输出。
    """
    question = req.question.strip()
    logger.info("收到 Agent 分析请求: %s", question)
    try:
        return run_analysis(question, req.analysis_mode)
    except Exception as exc:
        logger.error("Agent 分析失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"Agent 分析失败: {str(exc)}")


@app.post("/api/analyze/table")
async def analyze_imported_table(req: TableAnalyzeRequest):
    """
    CSV 导入表通用分析接口。

    该接口只允许分析 csv_ 前缀的导入表，会自动识别字段角色并生成只读 SQL、
    图表和结构化报告。
    """
    question = req.question.strip()
    table_name = req.table_name.strip()
    logger.info("收到 CSV 表 Agent 分析请求: %s / %s", table_name, question)
    try:
        return run_table_analysis(question, table_name, req.analysis_mode)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("CSV 表 Agent 分析失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"CSV 表 Agent 分析失败: {str(exc)}")


@app.get("/api/analysis/history")
async def analysis_history():
    return {"items": list_history()}


@app.get("/api/analysis/{run_id}")
async def analysis_detail(run_id: str):
    detail = get_history_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"分析记录 {run_id} 不存在")
    return detail


@app.get("/api/analysis/{run_id}/export")
async def analysis_export(run_id: str, format: str = Query("markdown", pattern="^(markdown|html)$")):
    exported = export_report(run_id, format)
    if not exported:
        raise HTTPException(status_code=404, detail=f"分析记录 {run_id} 不存在")
    content, media_type, filename = exported
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# CSV 导入相关路由
# ---------------------------------------------------------------------------


@app.post("/api/import/csv/preview")
async def preview_csv(
    file: UploadFile = File(..., description="CSV 文件"),
    header_row: int = Form(0, description="表头所在行号（0=自动检测）"),
    data_start_row: int = Form(0, description="数据起始行号（0=自动）"),
    skip_trailing: int = Form(-1, description="跳过末尾行数（-1=自动检测）"),
    combine_headers: int = Form(1, description="合并表头行数"),
):
    """预览 CSV 文件（不创建表），自动检测表头和尾部"""
    # header_row=0 表示自动检测
    if header_row <= 0:
        header_row = 0  # parse_csv 会触发自动检测
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="仅支持 .csv 格式的文件")

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取文件失败: {str(exc)}")

    file_size_mb = len(file_bytes) / (1024 * 1024)
    if file_size_mb > CSV_MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"文件大小超过限制（最大 {CSV_MAX_FILE_SIZE_MB}MB）")

    # ── 解析 CSV ──
    dsr = data_start_row if data_start_row > 0 else None
    st = skip_trailing if skip_trailing >= 0 else 0
    try:
        headers, rows = parse_csv(file_bytes, has_header=True, header_row=header_row,
                                  data_start_row=dsr, skip_trailing_rows=st,
                                  combine_header_rows=combine_headers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── 自动检测末尾非数据行 ──
    auto_skip = 0
    if skip_trailing < 0:
        auto_skip = auto_detect_trailing_rows(rows)
        if auto_skip > 0:
            rows = rows[:len(rows) - auto_skip]
            logger.info("自动跳过末尾 %d 行非数据内容", auto_skip)

    if len(rows) > CSV_MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"CSV 行数 ({len(rows)}) 超过限制")

    actual_data_start = dsr if dsr else header_row + combine_headers

    # ── 编码检测 ──
    encoding = "utf-8"
    try:
        file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            file_bytes.decode("gbk")
            encoding = "gbk"
        except UnicodeDecodeError:
            encoding = "latin-1"

    # ── 列名清理 + 类型检测 ──
    used_names = set()
    clean_headers = [sanitize_column_name(h, used_names) for h in headers]
    column_types = infer_column_types(clean_headers, rows)
    file_profile = profile_import_file(
        original_filename if "original_filename" in locals() else (file.filename or "unknown.csv"),
        headers,
        clean_headers,
        rows,
        column_types,
        encoding,
        delimiter=",",
    )

    # ── 每列的样本值 ──
    preview_count = min(20, len(rows))
    columns_info = []
    for i, col in enumerate(column_types):
        samples = [rows[j][i] if i < len(rows[j]) else "" for j in range(preview_count)]
        columns_info.append({
            "name": col["name"],
            "original_name": headers[i] if i < len(headers) else col["name"],
            "detected_type": col["type"],
            "sample_values": samples[:5],  # 前5个样本值
        })

    # ── 预览行 ──
    preview_rows = [list(row) for row in rows[:preview_count]]

    return {
        "encoding": encoding,
        "delimiter": ",",
        "total_rows": len(rows),
        "total_cols": len(clean_headers),
        "header_row": header_row,
        "data_start_row": actual_data_start,
        "combine_header_rows": combine_headers,
        "auto_skip_trailing": auto_skip,
        "skip_trailing_rows": st if skip_trailing >= 0 else auto_skip,
        "original_headers": headers,
        "clean_headers": clean_headers,
        "columns": columns_info,
        "preview_rows": preview_rows,
        "file_profile": file_profile,
    }


@app.post("/api/import/csv", response_model=ImportResponse, status_code=201)
async def import_csv(
    file: UploadFile = File(..., description="CSV 文件"),
    overwrite: bool = Form(False, description="是否覆盖同名表"),
    table_name: str | None = Form(None, description="自定义表名（可选）"),
    has_header: bool = Form(True, description="第一行是否为表头"),
    header_row: int = Form(1, description="表头所在行号"),
    data_start_row: int = Form(0, description="数据起始行号（0=自动）"),
    skip_trailing: int = Form(0, description="跳过末尾行数"),
    combine_headers: int = Form(1, description="合并表头行数"),
    column_names: str | None = Form(None, description="自定义列名 JSON数组"),
    column_types_override: str | None = Form(None, description="自定义列类型 JSON对象（可选）"),
    primary_key_column: str | None = Form(None, description="指定主键列名（可选，不指定则自动生成_id）"),
):
    """
    上传 CSV 文件并自动创建数据库表（支持预览后的自定义配置）
    """
    # ── 文件校验 ──
    original_filename = file.filename or "unknown.csv"
    if not original_filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="仅支持 .csv 格式的文件")

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取文件失败: {str(exc)}")

    file_size_mb = len(file_bytes) / (1024 * 1024)
    if file_size_mb > CSV_MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"文件大小超过限制")

    logger.info("收到 CSV 上传: %s (%.2f MB)", original_filename, file_size_mb)

    # ── 解析 CSV ──
    dsr = data_start_row if data_start_row > 0 else None
    try:
        headers, rows = parse_csv(file_bytes, has_header=has_header, header_row=header_row,
                                  data_start_row=dsr, skip_trailing_rows=skip_trailing,
                                  combine_header_rows=combine_headers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if len(rows) > CSV_MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"CSV 行数超过限制")

    # ── 列名处理：支持用户自定义列名 ──
    if column_names:
        try:
            custom_names = json.loads(column_names)
            if isinstance(custom_names, list) and len(custom_names) == len(headers):
                headers = custom_names
        except (json.JSONDecodeError, TypeError):
            pass  # 解析失败则使用原始列名

    used_names = set()
    clean_headers = [sanitize_column_name(h, used_names) for h in headers]

    # ── 类型覆盖 ──
    type_overrides = None
    if column_types_override:
        try:
            type_overrides = json.loads(column_types_override)
        except (json.JSONDecodeError, TypeError):
            pass

    # ── 表名处理 ──
    if table_name:
        clean_table = re.sub(r"[^\w一-鿿]", "_", table_name.strip())
        clean_table = re.sub(r"_+", "_", clean_table).strip("_")
        if not clean_table:
            clean_table = "imported"
        if not clean_table.startswith("csv_"):
            clean_table = "csv_" + clean_table
    else:
        clean_table = derive_table_name(original_filename)

    # ── 表名冲突 ──
    if table_exists(clean_table):
        if overwrite:
            drop_table(clean_table)
        else:
            raise HTTPException(status_code=409, detail={
                "error": "table_exists",
                "table_name": clean_table,
                "message": f"表 '{clean_table}' 已存在。请设置 overwrite=true 覆盖。",
            })

    # ── 类型推断（支持覆盖） ──
    column_types = infer_column_types(clean_headers, rows, type_overrides)

    # ── 建表 ──
    try:
        create_table(clean_table, column_types, primary_key_column)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建数据表失败: {str(exc)}")

    # ── 写入数据 ──
    try:
        inserted = insert_rows(clean_table, clean_headers, rows, CSV_BATCH_SIZE)
    except Exception as exc:
        try:
            drop_table(clean_table)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"写入数据失败: {str(exc)}")

    logger.info("CSV 导入成功: %s → %d 行", clean_table, inserted)
    return ImportResponse(
        table_name=clean_table,
        original_filename=original_filename,
        columns=column_types,
        row_count=inserted,
        message=f"成功导入 {inserted} 行数据到表 {clean_table}",
    )


@app.get("/api/tables", response_model=TableListResponse)
async def list_tables(imported_only: bool = Query(False, description="仅显示导入的表")):
    """
    获取所有表信息（包含导入状态）

    可用于前端展示表列表，区分原始表和导入表。
    """
    table_list = [
        TableInfo(**table)
        for table in _load_table_details()
        if not imported_only or table["imported"]
    ]

    return TableListResponse(tables=table_list)


@app.delete("/api/tables/{table_name}", response_model=DeleteResponse)
async def delete_imported_table(table_name: str):
    """
    删除导入的表

    ---
    安全限制：仅允许删除 csv_ 前缀的导入表。
    原始表（orders、products）不可通过此接口删除。
    """
    if not table_exists(table_name):
        raise HTTPException(
            status_code=404,
            detail=f"表 '{table_name}' 不存在",
        )

    try:
        drop_table(table_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"删除表失败: {str(exc)}",
        )

    logger.info("已删除导入表: %s", table_name)
    return DeleteResponse(
        deleted=table_name,
        message=f"表 {table_name} 已成功删除",
    )


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
