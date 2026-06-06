"""
=============================================================================
SQL 安全过滤器 — 纵深防御的第二道防线
=============================================================================

安全哲学:
  永远不要信任 LLM 的输出。虽然我们通过 System Prompt 要求模型只生成
  SELECT 语句，但大模型可能被 prompt injection 诱导而输出危险 SQL。
  因此，所有 LLM 生成的 SQL 必须经过本模块的二次校验。

防护层级:
  Layer 1: LLM System Prompt 约束（"只生成 SELECT"）
  Layer 2: 本模块正则白名单校验（"只放行 SELECT"）
  Layer 3: 数据库只读账户（可选，生产环境建议配置）

拦截范围:
  - DDL: DROP, ALTER, CREATE, TRUNCATE, RENAME
  - DML: DELETE, UPDATE, INSERT, REPLACE, MERGE
  - DCL: GRANT, REVOKE
  - 其他: LOAD_FILE, INTO OUTFILE, EXEC, SLEEP, BENCHMARK
  - 语句堆叠: 检测多个分号
=============================================================================
"""

import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """SQL 安全校验结果"""

    is_safe: bool
    reason: str


# ---------------------------------------------------------------------------
# 危险关键字模式库
# ---------------------------------------------------------------------------
# 每个元素是正则表达式，\b 确保匹配完整单词而非子串
# 例如 \bDROP\b 会匹配 "DROP TABLE" 但不会匹配 "DROPDOWN"

_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # ── DDL（数据定义语言）— 结构变更 ──
    (r"\bDROP\b", "DROP（删除表/库/索引）"),
    (r"\bALTER\b", "ALTER（修改表结构）"),
    (r"\bCREATE\b", "CREATE（创建表/库）"),
    (r"\bTRUNCATE\b", "TRUNCATE（清空表数据）"),
    (r"\bRENAME\b", "RENAME（重命名）"),
    # ── DML（数据操作语言）— 数据变更 ──
    (r"\bDELETE\b", "DELETE（删除数据行）"),
    (r"\bUPDATE\b", "UPDATE（更新数据）"),
    (r"\bINSERT\b", "INSERT（插入数据）"),
    (r"\bREPLACE\b", "REPLACE（替换数据）"),
    (r"\bMERGE\b", "MERGE（合并数据）"),
    # ── DCL（数据控制语言）— 权限变更 ──
    (r"\bGRANT\b", "GRANT（授权）"),
    (r"\bREVOKE\b", "REVOKE（撤销权限）"),
    # ── 危险函数 / 文件操作 ──
    (r"\bLOAD\b", "LOAD（加载数据/文件）"),
    (r"\bINTO\s+(OUTFILE|DUMPFILE)\b", "INTO OUTFILE/DUMPFILE（写入文件）"),
    (r"\bEXEC\b", "EXEC（执行命令）"),
    (r"\bEXECUTE\b", "EXECUTE（执行命令）"),
    (r"\bSLEEP\b", "SLEEP（延时函数，常用于盲注）"),
    (r"\bBENCHMARK\b", "BENCHMARK（性能测试函数，常用于盲注）"),
]

# SELECT 语句特征模式 — 允许 WITH（CTE）和 EXPLAIN 前缀
_SELECT_HEAD_PATTERN = re.compile(
    r"^(WITH\s+|EXPLAIN\s+)?SELECT\b",
    re.IGNORECASE,
)

# 注释清理模式
_COMMENT_SINGLE_LINE = re.compile(r"--[^\n]*")
_COMMENT_MULTI_LINE = re.compile(r"/\*.*?\*/", re.DOTALL)


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    校验 SQL 语句是否安全（只允许 SELECT）。

    参数:
        sql: 待校验的 SQL 字符串

    返回:
        (is_safe, reason) 二元组
        - is_safe=True  表示通过校验，可以执行
        - is_safe=False 表示被拦截，reason 说明原因

    示例:
        >>> validate_sql("SELECT * FROM orders")
        (True, 'OK')

        >>> validate_sql("DROP TABLE orders")
        (False, 'SQL 包含被禁止的操作: DROP（删除表/库/索引）')

        >>> validate_sql("SELECT 1; DROP TABLE orders;")
        (False, 'SQL 包含多个分号，可能存在语句堆叠注入')
    """
    # ── 空值检查 ──
    if not sql or not sql.strip():
        return False, "SQL 语句为空"

    stripped = sql.strip()

    # ── 注释清理 ──
    # 去除 SQL 注释后再做安全检查，防止攻击者用注释绕过
    # 例如: SELECT/*comment*/1 仍是合法的 SELECT
    cleaned = _COMMENT_SINGLE_LINE.sub("", stripped)
    cleaned = _COMMENT_MULTI_LINE.sub("", cleaned)
    cleaned = cleaned.strip()

    # ── 校验 1: 必须以 SELECT 开头 ──
    if not _SELECT_HEAD_PATTERN.match(cleaned):
        return (
            False,
            "只允许执行 SELECT 查询语句。"
            "检测到非 SELECT 开头（可能包含 WITH/EXPLAIN 以外的前缀）。",
        )

    # ── 校验 2: 禁止危险关键字 ──
    upper_sql = cleaned.upper()
    for pattern, description in _DANGEROUS_PATTERNS:
        if re.search(pattern, upper_sql):
            return (
                False,
                f"SQL 包含被禁止的操作: {description}",
            )

    # ── 校验 3: 分号堆叠注入检测 ──
    # 允许末尾一个分号（或无分号），但多个分号可能意味着语句堆叠
    # 例如: SELECT 1; DROP TABLE orders; -- 这是两条语句
    semicolon_count = stripped.count(";")
    if semicolon_count > 1:
        return (
            False,
            f"SQL 包含 {semicolon_count} 个分号，可能存在语句堆叠注入。"
            "只允许末尾一个分号或不带分号。",
        )
    if semicolon_count == 1 and not stripped.rstrip().endswith(";"):
        return (
            False,
            "分号只能出现在 SQL 语句末尾，不允许中间出现分号。",
        )

    return True, "OK"
