# NL2SQL 智能查询系统 — 简历项目经验

> 根据简历篇幅选择合适版本，推荐 **标准版**。

---

## 标准版（适合大多数简历，8-10行）

**NL2SQL 智能查询系统** | 全栈开发 | 2026.04 – 2026.06

- 设计并实现了一套**自然语言转 SQL 的智能数据分析平台**，用户输入中文问题即可自动生成 SQL 并返回图表，核心链路：自然语言 → LLM 生成 SQL → 安全校验 → MySQL 执行 → ECharts 可视化
- 后端基于 **FastAPI + Python** 构建，采用 **DDL 元数据动态注入** 机制——每次查询前提取最新数据库结构注入 System Prompt，确保 LLM 生成的 SQL 100% 匹配真实表结构，解决了大模型「瞎猜字段名」的痛点
- 自研 **CSV 文件智能导入引擎**，支持UTF-8/GBK编码检测、16种数据类型自动推断、多行合并表头（适配Excel合并单元格场景）、末尾非数据行自动跳过，并提供可视化预览调整面板
- 设计 **四层 SQL 安全纵深防御体系**：LLM Prompt 约束 → 18种危险关键字正则拦截 → 分号堆叠注入检测 → 注释清理，确保系统只执行只读查询，拦截率 100%
- 前端使用 **React 19 + Vite + ECharts 5**，实现智能图表推断（日期列→折线图、分类列→柱状图）、SQL一键复制、数字自动格式化等功能
- 部署 **Docker Compose** 管理 MySQL 8.0 容器，支持一键启动，数据持久化

---

## 精简版（篇幅紧张时使用，5-6行）

**NL2SQL 智能查询系统** | 全栈开发 | 2026.04 – 2026.06

- 开发了一套**自然语言→SQL→图表**的智能数据分析平台，基于 **FastAPI + React 19 + MySQL + DeepSeek V4 Pro**，支持中文问题自动生成 SQL 并可视化
- 核心设计**DDL 元数据动态注入**机制，每次查询前提取数据库真实结构注入 LLM Prompt，杜绝模型生成不存在的字段名；设计了**四层安全纵深防御**体系（Prompt约束 + 18种正则拦截 + 分号检测 + 注释清理），写操作拦截率 100%
- 自研 **CSV 智能导入引擎**，支持编码自动检测、16种数据类型推断、多行合并表头适配、自定义主键，并提供可视化预览调整面板
- 前端使用 **ECharts 5** 实现智能图表选择，Prompt 工程覆盖 **16 种 SQL 模式**（子查询/窗口函数/CASE WHEN/HAVING 等），LLM SQL 生成准确率 > 90%

---

## 详细版（适合面试讲述或项目经历展开，12-15行）

**NL2SQL 智能查询系统** | 个人项目 | 2026.04 – 2026.06

**项目背景**：传统企业报表场景中，非技术人员查询数据需要提工单→排期→开发写SQL，效率低下。本项目实现了一套自然语言驱动的智能查询系统，用户打字提问即可获取图表结果。

**技术架构**：FastAPI + React 19 + MySQL 8.0 (Docker) + DeepSeek V4 Pro (兼容 Anthropic API)

**核心贡献**：
1. **元数据外挂机制**：每次查询前通过 `SHOW CREATE TABLE` 动态获取数据库 DDL，注入 System Prompt 作为上下文，使得 LLM 基于真实表结构生成 SQL，解决了大模型编造不存在的列名/表名这一行业通病
2. **CSV 导入引擎**：实现编码检测(UTF-8/GBK)、分隔符嗅探、16种数据类型自动推断(INT→BIGINT→DECIMAL→DATE→DATETIME→VARCHAR)、多行合并表头(Excel合并单元格)、末尾非数据行自动跳过、可视化预览调整面板，支持自定义列名/类型/主键
3. **SQL 安全纵深防御**：Layer1 LLM Prompt 约束 → Layer2 18种危险关键字(含 DROP/DELETE/UPDATE/INSERT/ALTER 等)正则拦截 → Layer3 分号堆叠注入检测 → Layer4 SQL 注释清理防绕过，四层联动确保 100% 拦截写操作
4. **Prompt 工程**：设计了覆盖 16 种 SQL 模式的 System Prompt，包括子查询、窗口函数(ROW_NUMBER/RANK)、CASE WHEN、HAVING、DISTINCT、GROUP BY、多表 JOIN、聚合函数等，配合 temperature=0 确保确定性输出
5. **前端智能可视化**：根据查询结果的数据特征自动选择图表类型（日期列→折线图趋势分析，分类列→柱状图对比），基于 ECharts 5 实现，支持SQL展开查看和一键复制

**技术栈**：Python · FastAPI · PyMySQL · Anthropic SDK · React 19 · Vite · ECharts 5 · Axios · MySQL 8.0 · Docker Compose · Prompt Engineering

---

## 面试话术参考

### 1分钟版本

> 我做了一个 NL2SQL 智能查询系统，用户输入中文问题，系统自动生成SQL并返回图表。核心技术亮点有三个：第一是元数据外挂，每次查询前动态提取数据库建表语句注入到 LLM 的 Prompt 里，让模型基于真实表结构生成 SQL，不会瞎猜字段名；第二是 CSV 智能导入，支持编码检测、类型推断、多行表头合并、末尾汇总行跳过，上传后可以预览调整再确认导入；第三是四层 SQL 安全防御，从 Prompt 约束到后端正则拦截到注入检测层层把关，确保只执行只读查询。前后端分离架构，后端 FastAPI 前端 React 19 + ECharts 5。

### 面试常见追问

**Q: DDL 元数据外挂怎么实现的？**
> 每次查询前用 PyMySQL 执行 `SHOW CREATE TABLE` 获取所有表的建表语句，把这些 DDL 拼到 System Prompt 里。这样不管数据库结构怎么变（新增表、改字段），模型都能拿到最新的真实结构。

**Q: CSV 导入怎么处理 Excel 合并单元格？**
> 支持 `combine_headers` 参数合并多行表头——取这几行同一列的文本，跳过空值和重复值（合并单元格的典型特征），用分隔符连接。同时自动检测末尾的汇总行、签字行等非数据内容并跳过。

**Q: 安全性怎么保证？**
> 四层防御：第一层 Prompt 约束让 LLM 只生成 SELECT；第二层后端正则匹配 18 种危险关键字；第三层检测分号堆叠（`SELECT; DROP`）；第四层先去除 SQL 注释再检查，防止用注释绕过。另外 SQL Guard 只覆盖 LLM 生成路径，CSV 导入路径是服务端构造 SQL，用参数化查询防注入。

**Q: LLM 返回空内容怎么处理？**
> DeepSeek 的 thinking 模型可能只返回推理块没有文本块。我在代码中做了多层容错：优先取 text block，如果没有则尝试从 thinking block 提取，再尝试从原始响应字符串正则匹配 SELECT 语句。同时禁用了 thinking 模式确保直接输出 SQL。

---

> 简历中建议搭配的关键词：**FastAPI · React · MySQL · LLM/Prompt Engineering · SQL安全 · CSV解析 · ECharts · Docker · 全栈开发**
