"""
=============================================================================
LLM 服务 — 大模型调用层（NL → SQL 转换核心）
=============================================================================

职责:
  将用户的自然语言问题 + 数据库 DDL 元数据打包发送给大模型，
  模型返回对应的 SQL 查询语句。

Prompt 工程策略:
  - System Prompt 中包含所有表的 CREATE TABLE 语句（元数据外挂）
  - 明确约束：只输出 SQL，不要解释，不要 Markdown
  - 温度设为 0，确保结果确定性（同一问题→同一 SQL）

模型配置:
  当前使用 DeepSeek V4 Pro（兼容 Anthropic Messages API）
  可通过 ANTHROPIC_BASE_URL + LLM_MODEL 环境变量切换

异常约定:
  ValueError   — 问题无法转换为 SQL（LLM 返回 UNANSWERABLE）
  RuntimeError — API 网络/认证异常（调用方应返回 502）
=============================================================================
"""

import re
import anthropic
from backend.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, LLM_MODEL
from backend.database import get_ddl

# ---------------------------------------------------------------------------
# API 客户端（模块级单例）
# ---------------------------------------------------------------------------

_client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

# ---------------------------------------------------------------------------
# System Prompt 模板
# ---------------------------------------------------------------------------
# 这是整个系统的"灵魂"——Prompt 工程的核心
# {ddl} 占位符会被替换为实时提取的数据库建表语句

_SYSTEM_PROMPT_TEMPLATE = """你是一个资深的 MySQL SQL 查询专家。你的唯一任务是将用户的自然语言问题转换为**一行可执行的 SELECT 语句**。

## 数据库结构
以下是当前数据库所有表的真实建表语句（DDL），你必须严格依据这些表结构生成 SQL，不能编造不存在的列名或表名：

{ddl}

## 核心规则
1. **只输出一行 SQL**，不要任何解释、注释、分析过程、Markdown 标记（如 ```sql）。
2. **只生成 SELECT**，绝对禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE。
3. 如果问题无法用 SQL 回答（主观问题、与数据无关），只输出一个词：UNANSWERABLE
4. 所有表名和列名用反引号包裹（如 `表名`、`列名`），字符串值用单引号（如 '张三'）。
5. 聚合查询必须加 GROUP BY，排序用 ORDER BY。
6. 日期字段是字符串格式 'YYYY-MM-DD'，精确匹配用 =，范围用 BETWEEN。

---

## SQL 语法全覆盖参考

### 1. 基本查询 — SELECT / AS / DISTINCT
- 「查看所有学生」→ SELECT * FROM `students`
- 「查看学生姓名和学号」→ SELECT `姓名`, `学号` FROM `students`
- 「有哪些院系？」→ SELECT DISTINCT `院系` FROM `students`
- 「每个学生的总分」→ SELECT `姓名`, `语文`+`数学`+`英语` AS `总分` FROM `scores`

### 2. 筛选条件 — WHERE / AND / OR / NOT / <>
- 「成绩大于80」→ WHERE `成绩` > 80
- 「成绩>=80且<90」→ WHERE `成绩` >= 80 AND `成绩` < 90
- 「成绩在80到90之间」→ WHERE `成绩` BETWEEN 80 AND 90
- 「审查结果=有且毕结业结论=毕业」→ WHERE `审查结果` = '有' AND `毕结业结论` = '毕业'
- 「毕业或肄业的学生」→ WHERE `毕结业结论` = '毕业' OR `毕结业结论` = '肄业'
- 「不是计算机学院的」→ WHERE `院系` <> '计算机学院'
- 「院系是计算机或数学的」→ WHERE `院系` IN ('计算机学院', '数学学院')
- 「院系不是计算机也不是数学」→ WHERE `院系` NOT IN ('计算机学院', '数学学院')
- 「张三同学的成绩」→ WHERE `姓名` = '张三'
- 「名字包含"张"的」→ WHERE `姓名` LIKE '%张%'
- 「名字以"张"开头」→ WHERE `姓名` LIKE '张%'

### 3. NULL 值处理 — IS NULL / IS NOT NULL
- 「没有填写备注的学生」→ WHERE `备注` IS NULL
- 「有备注的学生」→ WHERE `备注` IS NOT NULL

### 4. 排序 — ORDER BY ASC / DESC / 多字段
- 「按成绩从高到低」→ ORDER BY `成绩` DESC
- 「按成绩从低到高」→ ORDER BY `成绩` ASC
- 「按院系升序、成绩降序」→ ORDER BY `院系` ASC, `成绩` DESC

### 5. 限制行数 — LIMIT / LIMIT OFFSET
- 「前5名」→ ORDER BY `成绩` DESC LIMIT 5
- 「第6到第10名」→ ORDER BY `成绩` DESC LIMIT 5 OFFSET 5
- 「分数最高的3个学生」→ ORDER BY `成绩` DESC LIMIT 3

### 6. 聚合函数 — COUNT / SUM / AVG / MAX / MIN
- 「总共有多少学生？」→ SELECT COUNT(*) AS `总人数` FROM `students`
- 「有成绩记录的学生数（去重）」→ SELECT COUNT(DISTINCT `学号`) FROM `scores`
- 「总销售额」→ SELECT SUM(`price` * `sales_volume`) AS `总销售额` FROM `orders`
- 「平均分」→ SELECT AVG(`成绩`) AS `平均分` FROM `scores`
- 「最高分/最低分」→ SELECT MAX(`成绩`), MIN(`成绩`) FROM `scores`

### 7. 分组聚合 — GROUP BY
- 「每个院系的学生人数」→ SELECT `院系`, COUNT(*) AS `人数` FROM `students` GROUP BY `院系`
- 「每个学生的平均分」→ SELECT `学号`, AVG(`成绩`) AS `平均分` FROM `scores` GROUP BY `学号`
- 「每个院系的最高分、最低分、平均分」→ SELECT `院系`, MAX(`成绩`), MIN(`成绩`), AVG(`成绩`) FROM `students` JOIN `scores` ON ... GROUP BY `院系`
- 「每天的订单数」→ SELECT `order_date`, COUNT(*) AS `订单数` FROM `orders` GROUP BY `order_date`

### 8. 聚合后筛选 — HAVING
- 「销售额大于1000的商品类别」→ GROUP BY `category` HAVING SUM(`price`*`sales_volume`) > 1000
- 「学生人数超过30的院系」→ GROUP BY `院系` HAVING COUNT(*) > 30
- 「平均分不及格的学生」→ GROUP BY `学号` HAVING AVG(`成绩`) < 60

### 9. 表关联 — JOIN / LEFT JOIN / 多表JOIN
- 「订单对应的商品名」→ FROM `orders` o JOIN `products` p ON o.`product_id` = p.`product_id`
- 「所有商品及其订单（含无订单的商品）」→ FROM `products` p LEFT JOIN `orders` o ON ...
- 「学生+成绩+课程三表关联」→ FROM `students` s JOIN `scores` sc ON s.`学号`=sc.`学号` JOIN `courses` c ON sc.`课程号`=c.`课程号`

### 10. 子查询 — WHERE ... IN (SELECT ...) / 派生表
- 「高于平均分的学生」→ WHERE `成绩` > (SELECT AVG(`成绩`) FROM `scores`)
- 「选了张三也选了的课的学生」→ WHERE `课程号` IN (SELECT `课程号` FROM `scores` WHERE `学号`='张三')
- 「每个院系最高分的学生」→ 使用派生表子查询

### 11. CASE WHEN — 条件分类
- 「成绩>=90为优秀，>=80为良好，>=60为及格，否则不及格」
  → SELECT `姓名`, CASE WHEN `成绩`>=90 THEN '优秀' WHEN `成绩`>=80 THEN '良好' WHEN `成绩`>=60 THEN '及格' ELSE '不及格' END AS `等级` FROM `scores`

### 12. 日期函数 — YEAR / MONTH / DATE_FORMAT
- 「按月统计订单数」→ SELECT DATE_FORMAT(`order_date`,'%Y-%m') AS `月份`, COUNT(*) FROM `orders` GROUP BY DATE_FORMAT(`order_date`,'%Y-%m')
- 「2026年的订单」→ WHERE YEAR(`order_date`) = 2026
- 「5月的订单」→ WHERE MONTH(`order_date`) = 5

### 13. 字符串函数 — CONCAT / SUBSTRING
- 「姓和名拼接」→ SELECT CONCAT(`姓`, `名`) AS `全名` FROM `students`
- 「取日期前7位（年月）」→ SELECT SUBSTRING(`order_date`, 1, 7) FROM `orders`

### 14. 数值函数 — ROUND / FLOOR / CEIL
- 「平均分保留2位小数」→ SELECT ROUND(AVG(`成绩`), 2) AS `平均分` FROM `scores`

### 15. 序号/排名 — ROW_NUMBER / RANK（MySQL 8.0窗口函数）
- 「每个院系按成绩排名」→ SELECT `院系`,`姓名`,`成绩`, ROW_NUMBER() OVER (PARTITION BY `院系` ORDER BY `成绩` DESC) AS `排名` FROM ...
- 「成绩排名（并列）」→ SELECT `姓名`,`成绩`, RANK() OVER (ORDER BY `成绩` DESC) AS `排名` FROM `scores`

### 16. UNION 合并
- 「2025和2026两年都有记录的学生」→ SELECT `学号` FROM `scores_2025` UNION SELECT `学号` FROM `scores_2026`

---

## 记住
- 用户用中文描述 → 你输出一行纯SQL
- 不确定时参考上面最接近的语法模式
- 列名和表名必须来自上面给出的真实DDL
- 不要自创列名，不要使用DDL中不存在的表名

## 当前问题
"""


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

# 匹配 LLM 可能包裹的 Markdown 代码块
_MARKDOWN_CODE_PATTERN = re.compile(
    r"```(?:\w+)?\s*\n?(.*?)\n?```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_sql_from_response(raw_text: str) -> str:
    """
    从 LLM 原始输出中提取纯净的 SQL 语句

    处理以下情况:
      - 裸 SQL: "SELECT * FROM orders"
      - Markdown 包裹: "```sql\nSELECT * FROM orders\n```"
      - 多行: "```\nSELECT ...\n```"
    """
    text = raw_text.strip()

    # 尝试匹配 Markdown 代码块
    match = _MARKDOWN_CODE_PATTERN.search(text)
    if match:
        return match.group(1).strip()

    # 没有代码块标记，直接返回
    return text


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def generate_sql(question: str) -> str:
    """
    将自然语言问题转换为 SQL 语句

    这是整个 NL2SQL 链路的核心——输入自然语言，输出可执行的 SQL。

    参数:
        question: 用户的自然语言问题
                  示例: "每种商品类别的总销售额是多少？"
                  示例: "2026年5月销量最高的5个商品是哪些？"

    返回:
        生成的 SQL 字符串
        示例: "SELECT p.category, SUM(o.price * o.sales_volume) AS total_sales ..."

    异常:
        ValueError:
          - 问题无法用 SQL 回答（LLM 返回 UNANSWERABLE）
          - 可能原因：问的是主观问题、与数据无关、或无法映射到表结构
        RuntimeError:
          - API 网络请求失败、认证失败、超时等
    """
    # 1. 动态获取最新的数据库 DDL（元数据外挂）
    ddl = get_ddl()

    # 2. 组装 System Prompt
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(ddl=ddl)

    # 3. 调用大模型
    try:
        response = _client.messages.create(
            model=LLM_MODEL,
            max_tokens=2048,
            temperature=0,  # 温度为 0 保证相同问题输出相同 SQL
            system=system_prompt,
            messages=[
                {"role": "user", "content": question},
            ],
            # 禁用 thinking 模式 — 我们只需要直接的SQL输出，不需要推理过程
            thinking={"type": "disabled"},
        )
    except Exception as exc:
        raise RuntimeError(
            f"大模型 API 调用失败: {str(exc)}。请检查 API Key 和网络连接。"
        ) from exc

    # 4. 提取纯净 SQL
    # response.content 是 ContentBlock 列表，可能有：
    #   - TextBlock (type="text"): 模型的文本输出
    #   - ThinkingBlock (type="thinking"): 推理过程（已禁用，但做容错）
    #   - ToolUseBlock (type="tool_use"): 工具调用（本项目不使用）
    text_blocks = [
        block.text
        for block in response.content
        if getattr(block, "type", "unknown") == "text"
    ]

    # 如果没找到 text block，尝试从 thinking block 中提取（容错处理）
    if not text_blocks:
        thinking_blocks = [
            block.thinking
            for block in response.content
            if getattr(block, "type", "unknown") == "thinking"
        ]
        if thinking_blocks:
            # thinking 内容可能包含最终SQL，尝试提取
            combined = "\n".join(thinking_blocks)
            sql = _extract_sql_from_response(combined)
            if sql.upper().strip() == "UNANSWERABLE":
                raise ValueError(
                    "您的问题无法转换为 SQL 查询，请尝试更具体的数据分析问题。"
                    "例如：'每种商品类别的销售额' 或 '每天的订单数趋势'。"
                )
            if sql:
                return sql

        # 尝试直接从 response 的字符串表示中提取
        raw_str = str(response)
        # 查找类似 'text': 'SELECT...' 的模式
        text_match = re.search(r"'text':\s*'([^']*SELECT[^']*)'", raw_str, re.IGNORECASE)
        if text_match:
            sql = text_match.group(1)
            return sql

        # 所有尝试失败
        raise RuntimeError(
            "LLM 返回了空的响应内容，请检查模型配置。\n"
            f"响应类型: {[getattr(b, 'type', 'unknown') for b in response.content]}"
        )

    raw_output = "".join(text_blocks)
    sql = _extract_sql_from_response(raw_output)

    # 5. 处理 UNANSWERABLE
    if sql.upper().strip() == "UNANSWERABLE":
        raise ValueError(
            "您的问题无法转换为 SQL 查询，请尝试更具体的数据分析问题。"
            "例如：'每种商品类别的销售额' 或 '每天的订单数趋势'。"
        )

    return sql
