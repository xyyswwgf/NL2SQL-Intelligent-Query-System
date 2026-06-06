# NL2SQL 智能查询系统 — 项目计划书

> **版本**: v1.0.0 | **日期**: 2026-06-04 | **状态**: MVP 已完成

---

## 目录

1. [项目概述](#1-项目概述)
2. [业务场景与数据模型](#2-业务场景与数据模型)
3. [系统架构](#3-系统架构)
4. [核心链路详解](#4-核心链路详解)
5. [安全设计](#5-安全设计)
6. [技术选型](#6-技术选型)
7. [项目结构](#7-项目结构)
8. [API 契约](#8-api-契约)
9. [前端交互设计](#9-前端交互设计)
10. [部署与运行](#10-部署与运行)
11. [测试策略](#11-测试策略)
12. [未来迭代方向](#12-未来迭代方向)

---

## 1. 项目概述

### 1.1 一句话描述

**用户输入自然语言 → 大模型结合数据库结构生成 SQL → 后端安全执行 → 前端动态渲染图表。**

### 1.2 解决什么问题

传统企业报表系统的痛点：

| 痛点 | 传统方式 | NL2SQL 方式 |
|------|---------|-------------|
| 非技术人员查数据 | 需要等开发写 SQL / 用复杂的 BI 工具 | 打字提问即可 |
| 临时分析需求 | 提工单 → 排期 → 开发写查询 | 即时提问，秒级返回 |
| SQL 安全风险 | 依赖开发人员自觉 | 系统级正则拦截 + LLM 约束双层防护 |
| 图表选择 | 手动选图表类型 | 系统根据数据"形状"智能判断 |

### 1.3 核心指标

- 自然语言 → SQL 转换成功率：> 90%（对数据相关的明确问题）
- SQL 安全检查拦截率：100%（任何写操作都会被拒绝）
- API 响应时间：< 5 秒（含 LLM 调用）
- 前端首屏渲染：< 2 秒

---

## 2. 业务场景与数据模型

### 2.1 模拟业务场景

本项目模拟**电商农产品销售**场景，兼顾你简历中的电商复购和农产品两条业务线。

### 2.2 数据库 ER 图

```
┌──────────────────────┐        ┌──────────────────────┐
│       orders          │        │      products         │
├──────────────────────┤        ├──────────────────────┤
│ order_id    INT  PK  │───┐    │ product_id   INT  PK  │
│ user_id     INT      │   │    │ product_name VARCHAR  │
│ product_id  INT  FK  │───┘    │ category     VARCHAR  │
│ price       DECIMAL  │        │ stock        INT      │
│ sales_volume INT     │        └──────────────────────┘
│ order_date  DATE     │
└──────────────────────┘
```

### 2.3 表说明

**orders（订单表）** — 30 条模拟数据

| 字段 | 类型 | 说明 |
|------|------|------|
| order_id | INT PK | 订单ID，自增 |
| user_id | INT | 用户ID（101-122） |
| product_id | INT FK | 商品ID，外键关联 products |
| price | DECIMAL(10,2) | 商品单价 |
| sales_volume | INT | 购买数量 |
| order_date | DATE | 下单日期（2026-05-01 ~ 05-14） |

**products（商品表）** — 15 条模拟数据

| 字段 | 类型 | 说明 |
|------|------|------|
| product_id | INT PK | 商品ID |
| product_name | VARCHAR(100) | 商品名称 |
| category | VARCHAR(50) | 商品类别（水果/蔬菜/粮食/粮油/乳制品/肉类/海鲜） |
| stock | INT | 当前库存数量 |

### 2.4 典型查询示例

| 自然语言 | 预期 SQL 特征 | 图表类型 |
|---------|-------------|---------|
| 每种商品类别的总销售额是多少？ | GROUP BY category, SUM(price*volume) | 柱状图 |
| 每天的订单总金额趋势？ | GROUP BY order_date, SUM | 折线图 |
| 哪些用户下单最多，前5名？ | GROUP BY user_id, ORDER BY COUNT DESC LIMIT 5 | 柱状图 |
| 各类别商品的平均库存？ | GROUP BY category, AVG(stock) | 柱状图 |

---

## 3. 系统架构

### 3.1 整体架构图

```
┌──────────────┐     HTTP/JSON      ┌─────────────────┐      Anthropic API      ┌──────────────┐
│              │  ◄──────────────►  │                 │  ◄───────────────────►  │              │
│   React 前端  │   POST /api/query  │  FastAPI 后端    │   Prompt: DDL+问题     │  DeepSeek/   │
│  (Vite+ECharts)│                   │  (Python 3.14)  │   Response: SQL        │  Claude 大模型 │
│  :5173        │                    │  :8000          │                        │              │
└──────────────┘                    └───────┬─────────┘                        └──────────────┘
                                            │
                                            │ PyMySQL
                                            ▼
                                    ┌──────────────┐
                                    │   MySQL 8.0   │
                                    │  (Docker)     │
                                    │  :3306        │
                                    └──────────────┘
```

### 3.2 分层职责

| 层级 | 技术 | 职责 |
|------|------|------|
| **展示层** | React 19 + ECharts 5 | 输入自然语言、展示表格+图表、智能选择图表类型 |
| **网关层** | FastAPI + Pydantic | 路由、CORS、请求日志、错误统一处理 |
| **业务层** | Python | LLM 调用、SQL 安全过滤、数据库交互 |
| **数据层** | MySQL 8.0 (Docker) | 持久化存储、DDL 元数据提供 |

---

## 4. 核心链路详解

### 4.1 完整请求生命周期

```
用户输入 "每种商品类别的总销售额是多少？"
  │
  │  ① 前端 POST /api/query  { question: "..." }
  ▼
┌─────────────────────────────────────────────────────┐
│ Step 1: LLM 生成 SQL  (llm_service.py)              │
│                                                     │
│   输入:                                              │
│     - System Prompt: 包含 all tables' CREATE TABLE  │
│     - User Message: 用户自然语言                      │
│                                                     │
│   输出:                                              │
│     SELECT p.category,                              │
│            SUM(o.price * o.sales_volume) AS total   │
│     FROM orders o                                   │
│     JOIN products p ON o.product_id = p.product_id  │
│     GROUP BY p.category                             │
│     ORDER BY total DESC                             │
│                                                     │
│   耗时: ~2-3s (LLM API 调用)                         │
└────────────────────┬────────────────────────────────┘
                     │
                     │  ② SQL 字符串
                     ▼
┌─────────────────────────────────────────────────────┐
│ Step 2: SQL 安全校验  (sql_guard.py)                 │
│                                                     │
│   检查项:                                            │
│     ✅ 以 SELECT 开头                                │
│     ✅ 不包含 DROP/DELETE/UPDATE/INSERT/ALTER...    │
│     ✅ 分号数量 ≤ 1                                  │
│     ✅ 无注释绕过 (去除 -- 和 /* */ 后再检查)         │
│                                                     │
│   耗时: < 1ms (纯正则)                               │
└────────────────────┬────────────────────────────────┘
                     │
                     │  ③ 安全 SQL
                     ▼
┌─────────────────────────────────────────────────────┐
│ Step 3: 执行查询  (database.py)                      │
│                                                     │
│   MySQL 执行 SELECT → DictCursor 返回结果             │
│   格式化为: { columns: [...], data: [[...], ...] }   │
│                                                     │
│   耗时: < 50ms (本地 MySQL)                          │
└────────────────────┬────────────────────────────────┘
                     │
                     │  ④ JSON Response
                     ▼
┌─────────────────────────────────────────────────────┐
│ 前端接收并渲染                                        │
│                                                     │
│   ① chartDetector.js 分析列名 → line/bar             │
│   ② ResultChart.jsx 用 ECharts 渲染图表              │
│   ③ ResultTable.jsx 渲染数据表格                     │
│   ④ 可展开查看生成的 SQL 语句                         │
└─────────────────────────────────────────────────────┘
```

### 4.2 "元数据外挂"机制

这是整个系统的核心创新：**不让大模型瞎猜数据库结构**。

```
传统做法（❌ 不好）:
  LLM 根据"经验"猜测表名和字段 → 经常生成不存在的列 → SQL 执行失败

我们的做法（✅ 正确）:
  每次查询前:
    1. 执行 SHOW CREATE TABLE orders
    2. 执行 SHOW CREATE TABLE products
    3. 将完整 DDL 注入 System Prompt
    4. LLM 基于真实表结构生成 SQL
  → 生成的 SQL 100% 匹配实际数据库结构
```

---

## 5. 安全设计

### 5.1 纵深防御三层

```
Layer 1: LLM Prompt 约束
  "只生成 SELECT 语句，禁止任何 DROP/DELETE/UPDATE/INSERT/ALTER"
  → 大概率防止模型生成危险 SQL

Layer 2: 后端正则拦截（sql_guard.py）
  正则匹配 18 种危险关键字
  + SELECT 开头校验
  + 注释清理
  + 分号堆叠检测
  → 即使 Layer 1 被绕过，Layer 2 也会拦截

Layer 3: 数据库只读账户（生产环境建议）
  MySQL 创建 read_only_user，仅授予 SELECT 权限
  → 即使 Layer 2 被绕过，数据库层面也无法执行写操作
```

### 5.2 拦截示例

| 输入 | LLM 可能返回 | 安全校验结果 |
|------|------------|------------|
| "删除所有订单" | `DELETE FROM orders` | ❌ 拦截: DELETE |
| "修改商品价格" | `UPDATE products SET price=10` | ❌ 拦截: UPDATE |
| "查看所有商品" | `SELECT * FROM products` | ✅ 通过 |
| "SELECT 1; DROP TABLE orders;" | 同上 | ❌ 拦截: 分号堆叠 + DROP |

---

## 6. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| **数据库** | MySQL 8.0 (Docker) | 企业标准，与简历场景匹配 |
| **后端框架** | FastAPI (Python) | 高性能异步、自动生成 OpenAPI 文档 |
| **LLM 调用** | Anthropic Python SDK | 兼容 DeepSeek / Claude 端点 |
| **大模型** | DeepSeek V4 Pro | 通过 Anthropic 兼容 API 接入 |
| **前端框架** | React 19 (Vite) | 快速开发、HMR 热更新 |
| **图表库** | ECharts 5 (echarts-for-react) | 企业级图表、支持柱状图和折线图 |
| **HTTP 客户端** | Axios | Promise 风格、拦截器支持 |
| **容器化** | Docker Compose | 一键启动 MySQL，环境隔离 |

---

## 7. 项目结构

```
PythonProject/
│
├── PRD.md                         ← 你正在看的项目计划书
├── TESTING.md                     ← 测试指南
├── docker-compose.yml             ← MySQL 8.0 容器定义
│
├── backend/                       ← Python 后端
│   ├── __init__.py                ← 包标记 + 模块说明
│   ├── main.py                    ← FastAPI 入口（路由/中间件/生命周期）
│   ├── config.py                  ← 环境变量配置
│   ├── database.py                ← MySQL 连接、DDL 提取、SQL 执行
│   ├── sql_guard.py               ← SQL 安全过滤器（正则白名单）
│   ├── llm_service.py             ← LLM 调用（NL→SQL 转换核心）
│   ├── init_db.sql                ← 建表 + 测试数据
│   └── requirements.txt           ← Python 依赖
│
├── frontend/                      ← React 前端
│   ├── index.html                 ← HTML 入口
│   ├── vite.config.js             ← Vite 配置
│   ├── package.json               ← Node 依赖
│   └── src/
│       ├── main.jsx               ← React 入口
│       ├── App.jsx                ← 主布局 + 状态管理
│       ├── App.css                ← 全局样式
│       ├── api.js                 ← Axios 封装
│       ├── components/
│       │   ├── QueryInput.jsx     ← 搜索框 + 推荐问题
│       │   ├── ResultTable.jsx    ← 数据表格 + SQL 展开
│       │   └── ResultChart.jsx    ← ECharts 图表渲染
│       └── utils/
│           └── chartDetector.js   ← 图表类型智能推断
│
└── main.py                        ← [保留] PyCharm 初始模板
```

---

## 8. API 契约

### 8.1 POST /api/query

**请求**:
```json
{
  "question": "每种商品类别的总销售额是多少？"
}
```

**成功响应 (200)**:
```json
{
  "sql": "SELECT p.category, SUM(o.price * o.sales_volume) AS total_sales FROM orders o JOIN products p ON o.product_id = p.product_id GROUP BY p.category ORDER BY total_sales DESC",
  "columns": ["category", "total_sales"],
  "data": [
    ["水果", 1500.00],
    ["蔬菜", 800.00]
  ],
  "row_count": 2
}
```

**错误响应**:

| 状态码 | 含义 | 示例 detail |
|--------|------|------------|
| 400 | 问题无效或无法转为 SQL | "您的问题无法转换为 SQL 查询" |
| 403 | SQL 安全校验未通过 | "SQL 包含被禁止的操作: DELETE（删除数据行）" |
| 500 | 数据库执行失败 | "SQL 执行失败: Table 'xxx' doesn't exist" |
| 502 | LLM API 调用失败 | "大模型 API 调用失败: Connection timeout" |

### 8.2 GET /api/health

```json
{
  "status": "healthy",
  "service": "NL2SQL",
  "version": "1.0.0"
}
```

---

## 9. 前端交互设计

### 9.1 组件状态机

```
┌──────────┐   输入问题    ┌──────────┐   收到响应   ┌──────────┐
│  空状态   │ ──────────► │  加载中   │ ──────────► │  结果展示  │
│ (welcome) │             │ (spinner) │             │ (chart+table)
└──────────┘              └──────────┘              └──────────┘
                                │                        │
                                │ API 错误               │ 新查询
                                ▼                        │
                           ┌──────────┐                  │
                           │  错误提示  │                  │
                           │ (banner)  │◄─────────────────┘
                           └──────────┘
```

### 9.2 图表智能推断规则

| 数据特征 | 推断图表 | 示例 |
|---------|---------|------|
| 包含日期/时间列 + 数值列 | **折线图** | "每天的订单总金额趋势" |
| 包含分类列 + 数值列 | **柱状图** | "每种商品类别的销售额" |
| 无日期无分类（兜底） | **柱状图** | 任意查询 |

### 9.3 推荐问题

前端预置 4 个推荐问题，覆盖不同的查询模式：
- "每种商品类别的总销售额是多少？" → 聚合 + JOIN + 分组
- "每天的订单总金额趋势？" → 时间序列聚合
- "哪些用户下单最多？" → 排名查询
- "各类别商品的库存情况？" → 跨表查询

---

## 10. 部署与运行

### 10.1 环境要求

- Docker Desktop（运行 MySQL）
- Python 3.11+（后端）
- Node.js 18+（前端）
- DeepSeek API Key（已配置在环境变量 `ANTHROPIC_AUTH_TOKEN`）

### 10.2 启动步骤

```bash
# Step 1: 启动 MySQL
cd /Users/xy/PycharmProjects/PythonProject
docker compose up -d

# Step 2: 安装 Python 依赖
source .venv/bin/activate
pip install -r backend/requirements.txt

# Step 3: 启动后端（端口 8000）
DB_PASSWORD=Simple@123 uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Step 4: 安装前端依赖并启动（端口 5173）
cd frontend
npm install
npm run dev
```

### 10.3 访问地址

| 服务 | 地址 |
|------|------|
| 前端界面 | http://localhost:5173 |
| 后端 API | http://localhost:8000 |
| API 文档 (Swagger) | http://localhost:8000/api/docs |
| API 文档 (ReDoc) | http://localhost:8000/api/redoc |
| 健康检查 | http://localhost:8000/api/health |

---

## 11. 测试策略

详见 [TESTING.md](./TESTING.md)，包含：

1. **功能测试** — 4 个典型查询场景的端到端验证
2. **安全测试** — SQL 注入攻击向量验证
3. **边界测试** — 空输入、超长输入、奇怪问题
4. **API 测试** — curl / Postman / Swagger 三种方式

---

## 12. 未来迭代方向

| 优先级 | 方向 | 描述 |
|--------|------|------|
| P0 | 对话上下文 | 支持追问："那上个月呢？"自动继承上文条件 |
| P0 | 查询缓存 | 相同问题缓存 SQL 和结果，减少 LLM 调用 |
| P1 | 多数据源 | 支持 PostgreSQL、ClickHouse 等 |
| P1 | 图表切换 | 用户可手动切换柱状图/折线图/饼图 |
| P1 | 数据导出 | 支持 CSV / Excel 导出 |
| P2 | 用户认证 | JWT 登录 + 查询权限控制 |
| P2 | 查询历史 | 保存历史查询，支持回看和重跑 |
| P2 | SQL 解释 | 大模型解释生成的 SQL 做了什么 |
| P3 | 定时报表 | 定时执行查询并推送结果 |

---

> **文档维护者**: Claude Code | **最后更新**: 2026-06-04
