"""
=============================================================================
数据库连接管理 — MySQL 交互层
=============================================================================

职责:
  1. get_ddl()      — 提取所有表的建表语句，作为 LLM Prompt 的元数据上下文
  2. execute_sql()  — 执行已通过安全校验的 SELECT 语句，返回结构化数据

设计说明:
  - 每次查询创建新连接（短连接模式），避免连接池在低负载下的维护成本
  - 使用 DictCursor，查询结果直接为 dict 而非 tuple，便于提取列名
  - 生产环境建议改为 SQLAlchemy 连接池 + 环境变量配置
=============================================================================
"""

import pymysql
from contextlib import contextmanager
from backend.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------


def _create_connection() -> pymysql.Connection:
    """
    创建到 MySQL 的新连接

    使用 DictCursor 以便查询结果包含列名信息，
    execute_sql() 依赖此特性来提取 columns 列表
    """
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    # 显式设置连接字符集，与数据库端 utf8mb4 保持一致
    with conn.cursor() as cur:
        cur.execute("SET NAMES utf8mb4")
    return conn


@contextmanager
def get_connection():
    """
    数据库连接上下文管理器

    用法:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT ...")

    退出上下文时自动关闭连接，即使发生异常也会保证关闭
    """
    conn = _create_connection()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DDL 元数据提取 — 整个系统的"外挂知识库"
# ---------------------------------------------------------------------------


def get_ddl() -> str:
    """
    提取当前数据库中所有用户表的 CREATE TABLE 语句

    这是系统的核心"元数据外挂"机制:
    - 大模型不知道你的数据库长什么样
    - 每次查询前动态获取 DDL 注入 Prompt
    - 模型根据真实表结构生成 SQL，不会瞎猜字段名

    返回:
        所有表的 CREATE TABLE 语句，用空行分隔
        示例:
            CREATE TABLE `orders` (
              `order_id` int NOT NULL AUTO_INCREMENT,
              ...
            )

            CREATE TABLE `products` (
              `product_id` int NOT NULL AUTO_INCREMENT,
              ...
            )
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # 获取当前库中所有用户表名
            cursor.execute("SHOW TABLES")
            table_key = f"Tables_in_{DB_NAME}"
            tables = [row[table_key] for row in cursor.fetchall()]

            ddl_parts: list[str] = []
            for table_name in tables:
                cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
                row = cursor.fetchone()
                ddl_parts.append(row["Create Table"])
                ddl_parts.append("")  # 空行分隔不同表的 DDL

            return "\n".join(ddl_parts).strip()


# ---------------------------------------------------------------------------
# SQL 执行 — 只执行已校验的 SELECT
# ---------------------------------------------------------------------------


def execute_sql(sql: str) -> dict:
    """
    执行已通过安全校验的 SELECT 语句

    参数:
        sql: 已校验的 SELECT SQL 语句

    返回:
        {
            "columns":   ["category", "total_sales"],   # 列名列表
            "data":      [["水果", 1500], ["蔬菜", 800]], # 数据行
            "row_count": 2                                # 行数
        }

    注意:
        此函数假定 SQL 已经通过 sql_guard.validate_sql() 校验，
        调用方应确保先校验再执行
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

            # 无结果时返回空结构
            if not rows:
                return {
                    "columns": [],
                    "data": [],
                    "row_count": 0,
                }

            # DictCursor 返回的每行是 dict，keys() 就是列名
            columns = list(rows[0].keys())

            # 将 dict 列表转为二维数组（前端更喜欢数组格式）
            data = [[row[col] for col in columns] for row in rows]

            return {
                "columns": columns,
                "data": data,
                "row_count": len(data),
            }


# ---------------------------------------------------------------------------
# DDL / 写操作 — CSV 导入专用（不经过 sql_guard，SQL由服务端构造）
# ---------------------------------------------------------------------------


def execute_ddl(sql: str) -> None:
    """
    执行 DDL 语句（CREATE TABLE / DROP TABLE 等）

    ⚠️ 仅用于 CSV 导入流程，SQL 由 csv_importer 模块在服务端构造，
    不经过 sql_guard 校验。调用方必须确保 SQL 安全。

    参数:
        sql: DDL SQL 语句
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            conn.commit()


def execute_insert(sql: str, rows: list[tuple]) -> int:
    """
    批量执行参数化 INSERT 语句

    使用 PyMySQL 的 executemany + 参数化查询，
    值从不拼接到 SQL 字符串中，防止注入。

    参数:
        sql:  INSERT SQL 语句（包含 %s 占位符）
        rows: 参数元组列表

    返回:
        插入的总行数
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)
            conn.commit()
            return cursor.rowcount


def table_exists(table_name: str) -> bool:
    """
    检查指定表是否存在于当前数据库中

    参数:
        table_name: 表名

    返回:
        True 如果表存在
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE %s", (table_name,))
            return cursor.fetchone() is not None


def drop_table(table_name: str) -> None:
    """
    删除指定的表

    安全限制：仅允许删除 csv_ 前缀的表（导入表），
    防止误删原始数据表（orders / products）。

    参数:
        table_name: 表名

    异常:
        ValueError: 尝试删除非 csv_ 前缀的表
    """
    if not table_name.startswith("csv_"):
        raise ValueError(
            f"安全限制：不允许删除非导入表 '{table_name}'。"
            "只有 csv_ 前缀的导入表可以被删除。"
        )
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
            conn.commit()
