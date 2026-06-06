# NL2SQL 智能查询系统 — 使用指南 & 技术详解

> **版本**: v1.1.0 | **日期**: 2026-06-04 | **作者**: Claude Code

---

## 目录

- [第一部分：使用指南](#第一部分使用指南)
  - [1. 项目简介](#1-项目简介)
  - [2. 文件结构速览](#2-文件结构速览)
  - [3. 文档应该保存到哪里](#3-文档应该保存到哪里)
  - [4. 数据集应该保存到哪里](#4-数据集应该保存到哪里)
  - [5. 如何启动项目](#5-如何启动项目)
  - [6. 如何使用网站](#6-如何使用网站)
  - [7. 如何添加/修改数据](#7-如何添加修改数据)
  - [8. 常见问题排查](#8-常见问题排查)
- [第二部分：专业概念详解](#第二部分专业概念详解)
  - [9. 什么是 NL2SQL](#9-什么是-nl2sql)
  - [10. 大模型（LLM）如何工作](#10-大模型llm如何工作)
  - [11. 元数据外挂机制](#11-元数据外挂机制)
  - [12. Prompt 工程](#12-prompt-工程)
  - [13. SQL 安全纵深防御](#13-sql-安全纵深防御)
  - [14. 图表智能推断](#14-图表智能推断)
- [第三部分：技术栈与工具介绍](#第三部分技术栈与工具介绍)
  - [15. 工具清单与职责](#15-工具清单与职责)
  - [16. 数据流动全景图](#16-数据流动全景图)
  - [17. 为什么选择这些工具](#17-为什么选择这些工具)

---

## 第一部分：使用指南

### 1. 项目简介

这是一个**自然语言转 SQL 的智能查询系统**。你不需要会写 SQL 代码，只需要用中文打字提问（例如"每种商品类别的总销售额是多少？"），系统会自动：

1. 将你的问题发送给大模型（AI）
2. 大模型结合数据库结构生成 SQL 查询语句
3. 后端安全执行这个 SQL
4. 前端用**表格 + 图表**展示结果

**一句话概括**：打字提问 → AI 写 SQL → 数据库查数据 → 图表可视化。

---

### 2. 文件结构速览

```
PythonProject/                          ← 📁 项目根目录（你在这里）
│
├── 📄 PRD.md                           ← 项目计划书（架构设计、API契约）
├── 📄 TESTING.md                       ← 测试指南（如何验证系统）
├── 📄 USER_GUIDE.md                    ← 📍 你正在看的文档（使用指南）
├── 📄 docker-compose.yml               ← MySQL 容器配置
│
├── 📁 backend/                         ← 🐍 Python 后端代码
│   ├── main.py                         ←   FastAPI 入口（路由/接口）
│   ├── config.py                       ←   配置（数据库密码、API Key等）
│   ├── database.py                     ←   数据库连接与操作
│   ├── sql_guard.py                    ←   SQL 安全过滤器
│   ├── llm_service.py                  ←   大模型调用（NL→SQL核心）
│   ├── init_db.sql                     ←   📊 数据库初始化脚本（建表+数据）
│   └── requirements.txt                ←   Python 依赖清单
│
├── 📁 frontend/                        ← ⚛️ React 前端代码
│   ├── index.html                      ←   HTML 入口
│   ├── vite.config.js                  ←   Vite 构建配置
│   ├── package.json                    ←   Node.js 依赖清单
│   └── src/
│       ├── main.jsx                    ←   React 入口
│       ├── App.jsx                     ←   主组件（状态管理+布局）
│       ├── App.css                     ←   全局样式
│       ├── api.js                      ←   后端 API 通信
│       ├── components/
│       │   ├── QueryInput.jsx          ←   搜索框+推荐问题
│       │   ├── ResultTable.jsx         ←   数据表格+SQL展示
│       │   └── ResultChart.jsx         ←   ECharts 图表
│       └── utils/
│           └── chartDetector.js        ←   图表类型智能推断
│
└── 📁 .venv/                           ← Python 虚拟环境（自动管理，不要手动改）
```

---

### 3. 文档应该保存到哪里

| 文档类型 | 保存位置 | 说明 |
|----------|----------|------|
| **项目计划/架构设计** | `PythonProject/PRD.md` | 产品需求文档，描述系统设计 |
| **测试指南** | `PythonProject/TESTING.md` | 如何验证系统功能 |
| **使用指南** | `PythonProject/USER_GUIDE.md` | 本文档，如何使用系统 |
| **新功能设计文档** | `PythonProject/docs/` | 建议创建此目录存放新的设计文档 |
| **API 文档（自动生成）** | 启动后访问 `http://localhost:8000/api/docs` | FastAPI 自动生成的 Swagger 文档 |

**建议规则**：
- 所有 `.md` 文档放在项目根目录 `PythonProject/`
- 截图、设计图可以新建 `PythonProject/docs/images/` 目录存放
- API 变更后 **不需要** 手动更新文档，Swagger 会自动同步

---

### 4. 数据集应该保存到哪里

**当前数据存储方式**：MySQL 数据库（Docker 容器内）

| 数据相关文件 | 位置 | 说明 |
|-------------|------|------|
| **建表+初始化数据** | `backend/init_db.sql` | ⭐ **这是你修改数据的主要入口** |
| **MySQL 持久化存储** | Docker Volume `mysql_data` | 容器删除后数据不丢失 |
| **数据库备份** | 建议存到 `PythonProject/backups/` | 执行 `mysqldump` 导出的 `.sql` 文件 |

#### 如何修改初始数据

编辑 `backend/init_db.sql` 文件：

```sql
-- 例如：新增一个商品
INSERT INTO products (product_id, product_name, category, stock) VALUES
(16, '云南普洱茶', '茶叶', 200);   -- ← 添加这行

-- 例如：新增一个订单
INSERT INTO orders (order_id, user_id, product_id, price, sales_volume, order_date) VALUES
(31, 101, 16, 88.00, 3, '2026-06-01');
```

**⚠️ 注意**：修改 `init_db.sql` 后需要重建容器才能生效：

```bash
docker compose down -v    # 删除旧容器+数据卷
docker compose up -d      # 重建，自动执行 init_db.sql
```

#### 如何备份当前数据

```bash
# 导出整个数据库到文件
docker exec nl2sql-mysql mysqldump -uroot -pSimple@123 nl2sql_db > backups/nl2sql_backup_$(date +%Y%m%d).sql

# 恢复数据
docker exec -i nl2sql-mysql mysql -uroot -pSimple@123 nl2sql_db < backups/nl2sql_backup_20260604.sql
```

---

### 5. 如何启动项目

#### 前置条件

- **Docker Desktop**（运行 MySQL）→ [下载地址](https://www.docker.com/products/docker-desktop/)
- **Python 3.11+** → 已安装在 `.venv/` 虚拟环境中
- **Node.js 18+** → 用于前端开发服务器

#### 启动三步走

**终端 1：启动 MySQL 数据库**

```bash
cd /Users/xy/PycharmProjects/PythonProject
docker compose up -d

# 等待 MySQL 就绪（看到 healthy 即可）
docker ps --filter "name=nl2sql-mysql"
```

**终端 2：启动后端 API 服务**

```bash
cd /Users/xy/PycharmProjects/PythonProject
source .venv/bin/activate
DB_PASSWORD=Simple@123 uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

看到以下输出说明启动成功：
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

**终端 3：启动前端开发服务器**

```bash
cd /Users/xy/PycharmProjects/PythonProject/frontend
npm install          # 仅首次需要
npm run dev
```

看到以下输出说明启动成功：
```
VITE v8.0.16  ready in xxx ms
➜  Local:   http://localhost:5173/
```

#### 访问地址

| 服务 | 地址 | 用途 |
|------|------|------|
| 🖥️ 前端界面 | http://localhost:5173 | 用户使用的网页 |
| 🔌 后端 API | http://localhost:8000 | 前端调用 |
| 📖 API 文档 | http://localhost:8000/api/docs | 交互式 API 调试 |

---

### 6. 如何使用网站

#### 方式一：点击推荐问题（最简单）

1. 打开 http://localhost:5173
2. 在搜索框下方有 4 个推荐问题按钮
3. **点击**任意一个（会自动提交查询）
4. 等待 2-3 秒，看到柱状图/折线图 + 数据表格
5. 点击「📝 查看生成的 SQL」可以看到 AI 生成的 SQL 语句

#### 方式二：自由输入问题

1. 在搜索框输入你的问题（例如："乳制品卖了多少？"）
2. 按 **Enter** 键或点击「🔍 查询」按钮
3. 查看结果

#### 方式三：通过 API 文档调试

1. 打开 http://localhost:8000/api/docs
2. 找到 `POST /api/query` → 点击「Try it out」
3. 输入 `{"question": "查看所有商品"}`
4. 点击「Execute」直接在浏览器中看到 JSON 返回结果

#### 支持的查询类型

| 查询类型 | 示例问题 | 图表类型 |
|----------|---------|---------|
| 分类聚合 | "每种商品类别的总销售额？" | 📊 柱状图 |
| 时间趋势 | "每天的订单总金额趋势？" | 📈 折线图 |
| 排名查询 | "哪些用户下单最多？前5名" | 📊 柱状图 |
| 跨表关联 | "各类别商品的库存情况？" | 📊 柱状图 |
| 条件筛选 | "水果类商品的总销售额？" | 📊 柱状图 |
| 统计计算 | "订单的平均金额是多少？" | 📊 柱状图 |

#### 小技巧

- **复制 SQL**：展开 SQL 后点击「📋 复制」按钮，一键复制到剪贴板
- **查看表格行号**：表格第一列 `#` 是自动生成的行号
- **数字自动格式化**：金额、数量等数值会自动添加千分位分隔符

---

### 7. 如何添加/修改数据

#### 场景 1：新增商品

编辑 `backend/init_db.sql`，在 `INSERT INTO products` 末尾添加：

```sql
(16, '云南普洱茶', '茶叶', 200);
```

然后重建数据库：
```bash
docker compose down -v && docker compose up -d
```

#### 场景 2：新增订单

编辑 `backend/init_db.sql`，在 `INSERT INTO orders` 末尾添加：

```sql
(31, 101, 16, 88.00, 3, '2026-06-01');
```

#### 场景 3：新增一个表

例如新增 `users` 用户表：

1. 在 `backend/init_db.sql` 中添加建表语句：

```sql
CREATE TABLE users (
    user_id  INT          NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '用户ID',
    username VARCHAR(50)  NOT NULL                  COMMENT '用户名',
    city     VARCHAR(50)  NOT NULL                  COMMENT '城市',
    vip_level INT         NOT NULL DEFAULT 0        COMMENT 'VIP等级'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

INSERT INTO users (user_id, username, city, vip_level) VALUES
(101, '张三', '北京', 3),
(102, '李四', '上海', 2);
```

2. 重建数据库后，系统会自动识别新表（DDL 动态提取机制），LLM 就能回答关于用户表的问题

#### 场景 4：清空数据重新开始

```bash
docker compose down -v    # 完全删除容器+数据
docker compose up -d      # 重新创建，执行 init_db.sql
```

---

### 8. 常见问题排查

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| 前端页面空白 | 后端未启动 | 检查终端2是否正常运行 |
| 查询报错 502 | LLM API 不通 | 检查网络 + API Key 是否有效 |
| MySQL 启动失败 | 端口 3306 被占用 | `brew services stop mysql` 停掉本地 MySQL |
| 端口 8000 被占用 | 上次后端未关闭 | `lsof -ti:8000 \| xargs kill` |
| 端口 5173 被占用 | 上次前端未关闭 | `lsof -ti:5173 \| xargs kill` |
| 表中没有新数据 | 改了 init_db.sql 但没重建 | 执行 `docker compose down -v && docker compose up -d` |
| 中文乱码 | 字符集问题 | 确认 init_db.sql 中有 `SET NAMES utf8mb4` |

---

## 第二部分：专业概念详解

### 9. 什么是 NL2SQL

**NL2SQL** = **N**atural **L**anguage **to** **SQL**

就是把人类自然语言（中文、英文）自动转换成数据库查询语言（SQL）的技术。

```
传统方式（需要会写代码）:
  用户想要「每种商品类别的总销售额」
    → 用户自己写: SELECT p.category, SUM(o.price * o.sales_volume) ...
    → 需要懂 SQL 语法、表名、字段名、JOIN 关系

NL2SQL 方式（打字就行）:
  用户打字：「每种商品类别的总销售额是多少？」
    → AI 自动生成 SQL → 数据库执行 → 返回图表
    → 不需要任何 SQL 知识
```

**为什么有价值？**

在一个公司里，销售、运营、管理层通常不会写 SQL。他们想看数据时只能：
- 等开发排期写查询（可能等好几天）
- 用复杂的 BI 工具（学习成本高）

NL2SQL 让他们可以**直接打字提问，秒级获取答案**。

---

### 10. 大模型（LLM）如何工作

**LLM** = **L**arge **L**anguage **M**odel（大语言模型）

可以理解为：一个读了几万亿字文本的 AI，它学会了「理解语言」和「生成语言」。

#### 在这个项目中的角色

```
你的问题：「每种商品类别的总销售额？」
       │
       ▼
┌──────────────────────────────────────┐
│            DeepSeek V4 Pro           │
│                                      │
│  系统告诉它：                          │
│    - 数据库有哪些表（orders, products） │
│    - 每个表有什么字段（order_id, price...│
│    - 字段类型是什么（INT, DECIMAL...）  │
│                                      │
│  它思考后输出：                         │
│    SELECT p.category,                │
│           SUM(o.price * o.sales_volume│
│    FROM orders o                     │
│    JOIN products p ...               │
│    GROUP BY p.category               │
└──────────────────────────────────────┘
```

#### 为什么需要"元数据外挂"

如果直接问大模型：「销售额怎么查？」，它会根据「经验」猜测表名，很可能猜错（比如猜成 `sales` 表、`amount` 字段——但你的数据库里根本没有这些）。

所以我们需要把**真实的数据库结构**（DDL）告诉它——这就是下一节要讲的「元数据外挂」。

---

### 11. 元数据外挂机制

这是本项目**最核心的创新设计**。

#### 什么是 DDL

**DDL** = **D**ata **D**efinition **L**anguage（数据定义语言）

就是建表语句，描述了数据库的「骨架」：

```sql
CREATE TABLE `orders` (
  `order_id`     INT            NOT NULL AUTO_INCREMENT,  -- 订单ID，整数，自增
  `user_id`      INT            NOT NULL,                 -- 用户ID
  `product_id`   INT            NOT NULL,                 -- 商品ID（外键）
  `price`        DECIMAL(10,2)  NOT NULL,                 -- 单价，两位小数
  `sales_volume` INT            NOT NULL DEFAULT 1,       -- 购买数量
  `order_date`   DATE           NOT NULL,                 -- 下单日期
  PRIMARY KEY (`order_id`),
  FOREIGN KEY (`product_id`) REFERENCES `products`(`product_id`)
);
```

#### 传统做法 vs 我们的做法

```
❌ 传统做法:
  System Prompt: "你是一个 SQL 专家，请根据用户问题生成 SQL"
  → LLM 瞎猜表名和字段 → 经常生成不存在的列 → 执行失败

✅ 我们的做法（元数据外挂）:
  System Prompt: "你是一个 SQL 专家。以下是数据库的真实结构：
                 [动态注入完整的 CREATE TABLE 语句]
                 请严格依据这些表结构生成 SQL"
  → LLM 基于真实结构生成 → 100% 匹配实际数据库 → 执行成功
```

#### 代码中的实现

```python
# database.py — 每次查询前动态获取最新 DDL
def get_ddl():
    """提取所有表的 CREATE TABLE 语句"""
    cursor.execute("SHOW TABLES")           # 获取所有表名
    for table in tables:
        cursor.execute(f"SHOW CREATE TABLE `{table}`")  # 获取建表语句
    return ddl  # 返回完整 DDL 文本

# llm_service.py — 注入到 System Prompt
system_prompt = f"""...
## 数据库结构
{ddl}           ← 这里动态注入真实表结构
..."""
```

**好处**：即使你修改了数据库结构（新增表、新增字段），系统会自动感知，不需要改任何代码。

---

### 12. Prompt 工程

**Prompt** = 你发送给大模型的指令文本。

**Prompt 工程** = 设计这个指令的方式，让模型输出你想要的格式和内容。

#### 本项目的 System Prompt 设计

```
你是一个资深的 SQL 查询专家。你的任务是将用户的自然语言问题转换为 MySQL SQL 查询。

## 数据库结构                    ← ① 元数据注入
以下是当前数据库所有表的建表语句（DDL），你需要严格依据这些表结构生成 SQL：
{ddl}

## 输出规则                      ← ② 行为约束
1. 只输出一行 SQL 语句，不要包含任何解释
2. 只生成 SELECT 语句，绝对禁止写操作
3. 如果问题无法用 SQL 回答，输出 UNANSWERABLE
4. 聚合查询使用合适的列别名（AS）
5. 日期字段格式是字符串 'YYYY-MM-DD'

## 示例                          ← ③ Few-shot 示例
用户问：每种商品类别的销售额是多少？
你输出：SELECT p.category, SUM(...) ...
```

#### Prompt 工程的核心技巧

| 技巧 | 说明 | 本项目中的应用 |
|------|------|--------------|
| **角色设定** | 告诉模型"你是谁" | "你是一个资深的 SQL 查询专家" |
| **上下文注入** | 给模型外部知识 | 动态注入 DDL（元数据外挂） |
| **输出约束** | 规定格式和边界 | "只输出一行 SQL"，"只生成 SELECT" |
| **Few-shot** | 给1-3个示例 | 示例：问题→期望的SQL输出 |
| **兜底机制** | 不可回答时怎么办 | 输出 UNANSWERABLE，后端捕获返回400 |
| **温度控制** | temperature=0 | 相同问题始终输出相同 SQL（确定性） |

---

### 13. SQL 安全纵深防御

**核心问题**：大模型可能被诱导输出危险的 SQL（如 `DROP TABLE orders`），如果直接执行会删库。

**解决方案**：三道防线层层拦截。

```
用户输入 "删除所有订单"
        │
        ▼
┌─────────────────────────────────────────┐
│ 第一道防线：LLM Prompt 约束              │
│ "绝对禁止生成 INSERT/UPDATE/DELETE/DROP" │
│ → LLM 大概率拒绝，输出 UNANSWERABLE      │
└──────────────────┬──────────────────────┘
                   │ 万一被绕过 ↓
                   ▼
┌─────────────────────────────────────────┐
│ 第二道防线：后端正则拦截（sql_guard.py）  │
│ - 必须 SELECT 开头                       │
│ - 禁止 18 种危险关键字（DROP/DELETE...） │
│ - 检测分号堆叠注入（SELECT; DROP TABLE） │
│ - 去除注释防止绕过（/* 危险 */）         │
│ → 100% 拦截所有非 SELECT 语句            │
└──────────────────┬──────────────────────┘
                   │ 万一被绕过 ↓
                   ▼
┌─────────────────────────────────────────┐
│ 第三道防线：数据库只读账户（建议）        │
│ MySQL 用户只授予 SELECT 权限             │
│ → 即使前两道被绕过，数据库层也无法写入    │
└─────────────────────────────────────────┘
```

#### 拦截示例

```python
# sql_guard.py 中的危险关键字列表
_DANGEROUS_PATTERNS = [
    (r"\bDROP\b",     "DROP（删除表/库/索引）"),
    (r"\bDELETE\b",   "DELETE（删除数据行）"),
    (r"\bUPDATE\b",   "UPDATE（更新数据）"),
    (r"\bINSERT\b",   "INSERT（插入数据）"),
    (r"\bALTER\b",    "ALTER（修改表结构）"),
    # ... 共 18 种
]
```

---

### 14. 图表智能推断

前端不只是展示原始数据，还会**根据数据的"形状"自动选择合适的图表类型**。

#### 推断规则

```
查询结果包含什么列？
        │
        ├── 有日期列（order_date）+ 数值列
        │     → 📈 折线图（适合展示时间趋势）
        │
        ├── 有分类列（category, user_id）+ 数值列
        │     → 📊 柱状图（适合对比不同类别）
        │
        └── 其他情况
              → 📊 柱状图（默认兜底）
```

#### 日期列识别

代码通过正则表达式识别日期列名（`chartDetector.js`）：

```javascript
const DATE_COLUMN_PATTERNS = [
  /date/i,       // order_date, created_date
  /time/i,       // create_time
  /日期/,         // 订单日期
  /_at$/,        // created_at, updated_at
  /年$/, /月$/, /日$/,
  // ...
];
```

**也就是说**：只要你的列名包含 `date`、`time`、`日期`、`_at` 等关键词，系统会自动识别为时间列并选择折线图。

---

## 第三部分：技术栈与工具介绍

### 15. 工具清单与职责

#### 后端工具

| 工具 | 一句话介绍 | 在项目中的角色 |
|------|-----------|--------------|
| **Python 3.14** | 编程语言 | 后端开发语言 |
| **FastAPI** | Python Web 框架 | 提供 REST API 接口、自动生成文档 |
| **Uvicorn** | ASGI 服务器 | 运行 FastAPI 应用 |
| **PyMySQL** | MySQL 数据库驱动 | Python 连接和操作 MySQL |
| **Anthropic SDK** | 大模型 API 客户端 | 调用 DeepSeek/Claude 大模型 |
| **Pydantic** | 数据校验库 | 自动校验请求参数格式 |

#### 前端工具

| 工具 | 一句话介绍 | 在项目中的角色 |
|------|-----------|--------------|
| **React 19** | 前端 UI 框架 | 构建用户界面组件 |
| **Vite** | 前端构建工具 | 开发服务器+热更新+打包 |
| **ECharts 5** | 数据可视化库 | 渲染柱状图、折线图 |
| **echarts-for-react** | ECharts 的 React 封装 | 在 React 组件中使用 ECharts |
| **Axios** | HTTP 请求库 | 前端调用后端 API |

#### 基础设施

| 工具 | 一句话介绍 | 在项目中的角色 |
|------|-----------|--------------|
| **Docker** | 容器化平台 | 运行 MySQL 数据库容器 |
| **MySQL 8.0** | 关系型数据库 | 存储商品、订单数据 |
| **DeepSeek V4 Pro** | 大语言模型 | 将自然语言转换为 SQL |

---

### 16. 数据流动全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                        数据流动全过程                              │
└──────────────────────────────────────────────────────────────────┘

  浏览器（用户）                    后端服务器                      AI 大脑
  ────────────                    ──────────                      ──────

  ┌──────────┐    ① 打字提问      ┌──────────┐    ② 带数据库结构   ┌──────────┐
  │          │ ────────────────► │          │ ────────────────► │          │
  │  React   │  POST /api/query  │  FastAPI │  Prompt + DDL    │ DeepSeek │
  │  前端    │                   │  后端    │                   │  大模型   │
  │          │ ◄──────────────── │          │ ◄──────────────── │          │
  └──────────┘  ⑤ JSON响应       └────┬─────┘  ③ 生成的SQL      └──────────┘
       │         {sql, columns,       │
       │          data, row_count}    │ ④ 执行SQL
       ▼                              ▼
  ┌──────────┐                   ┌──────────┐
  │ ECharts  │                   │  MySQL   │
  │ 图表渲染 │                   │ 数据库   │
  │+ 表格    │                   │ (Docker) │
  └──────────┘                   └──────────┘

完整链路耗时：
  ①→② 网络传输:       < 5ms   (本机)
  ②→③ LLM 推理:       ~2-3秒  (DeepSeek API)
  ③→④ SQL 安全校验:   < 1ms   (纯正则)
  ④ 数据库查询:        < 50ms  (本地MySQL)
  ④→⑤ 结果序列化:     < 5ms
  ─────────────────────────────────────
  总计:                ~2-4秒
```

---

### 17. 为什么选择这些工具

#### 为什么用 FastAPI 而不是 Flask？

| 对比维度 | FastAPI | Flask |
|---------|---------|-------|
| 性能 | 异步，接近 Node.js 速度 | 同步，较慢 |
| API 文档 | **自动生成** Swagger/ReDoc | 需要手动写或装插件 |
| 数据校验 | Pydantic 自动校验 | 需要手动写校验逻辑 |
| 类型提示 | 原生支持 Python type hints | 不支持 |
| 适合场景 | API 服务 | 全栈 Web 应用 |

#### 为什么用 ECharts 而不是 Chart.js？

| 对比维度 | ECharts | Chart.js |
|---------|---------|----------|
| 中文支持 | ✅ 原生完美支持 | ⚠️ 需要额外配置 |
| 图表种类 | 丰富（柱状/折线/饼图/地图...） | 基础 |
| 大数据量 | 性能优秀 | 一般 |
| 移动端 | 支持良好 | 一般 |

#### 为什么用 Docker 运行 MySQL？

- **环境隔离**：不和系统其他 MySQL 冲突
- **一键启动**：`docker compose up -d` 就搞定
- **数据持久化**：通过 Volume 保存数据，容器删除数据不丢
- **可复现**：任何机器上都能用相同环境运行

#### 为什么用 DeepSeek V4 Pro？

- **性价比高**：相比 Claude/OpenAI 便宜很多
- **兼容 Anthropic API**：可以用 Anthropic SDK 调用
- **中英文能力强**：对中文查询理解好
- **支持 thinking 模式**：模型的推理过程与输出分离

---

## 附录

### A. 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DB_HOST` | `127.0.0.1` | MySQL 地址 |
| `DB_PORT` | `3306` | MySQL 端口 |
| `DB_USER` | `root` | 数据库用户名 |
| `DB_PASSWORD` | （必填） | 数据库密码 |
| `DB_NAME` | `nl2sql_db` | 数据库名称 |
| `ANTHROPIC_AUTH_TOKEN` | （必填） | DeepSeek API Key |
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` | LLM API 地址 |
| `LLM_MODEL` | `deepseek-v4-pro` | 模型名称 |

### B. 有用链接

| 资源 | 链接 |
|------|------|
| FastAPI 官方文档 | https://fastapi.tiangolo.com/zh/ |
| React 官方文档 | https://react.dev/ |
| ECharts 官方示例 | https://echarts.apache.org/examples/zh/index.html |
| Docker 入门教程 | https://docs.docker.com/get-started/ |
| DeepSeek 平台 | https://platform.deepseek.com/ |
| Anthropic SDK 文档 | https://docs.anthropic.com/en/docs/ |

---

> **文档维护者**: Claude Code | **最后更新**: 2026-06-04
> 如有疑问，请在项目中新建 Issue 或查看 [PRD.md](./PRD.md) 和 [TESTING.md](./TESTING.md)
