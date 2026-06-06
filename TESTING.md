# NL2SQL 智能查询系统 — 测试指南

> 从零开始，一步步验证整个系统是否正常工作。

---

## 目录

- [0. 前置条件检查](#0-前置条件检查)
- [1. 启动 MySQL](#1-启动-mysql)
- [2. 启动后端](#2-启动后端)
- [3. API 功能测试（curl）](#3-api-功能测试curl)
- [4. SQL 安全测试](#4-sql-安全测试)
- [5. 启动前端](#5-启动前端)
- [6. 前端界面测试](#6-前端界面测试)
- [7. 端到端场景测试](#7-端到端场景测试)

---

## 0. 前置条件检查

**打开终端，逐条执行以下命令确认环境就绪：**

```bash
# 确认 Docker 可用（MySQL 依赖它）
docker --version
# 预期输出: Docker version 29.x.x

# 确认 Python 虚拟环境存在
ls /Users/xy/PycharmProjects/PythonProject/.venv/bin/python3
# 预期输出: 文件路径（不报错即可）

# 确认 Node.js 可用
node --version
# 预期输出: v26.x.x

# 确认项目文件完整
ls /Users/xy/PycharmProjects/PythonProject/docker-compose.yml
ls /Users/xy/PycharmProjects/PythonProject/backend/main.py
ls /Users/xy/PycharmProjects/PythonProject/frontend/src/App.jsx
# 预期输出: 三个文件路径，都不报错
```

---

## 1. 启动 MySQL

```bash
cd /Users/xy/PycharmProjects/PythonProject

# 启动 MySQL 容器（首次会拉取镜像，约 2 分钟）
docker compose up -d

# 等待 MySQL 就绪（看到 healthy 即可）
docker ps --filter "name=nl2sql-mysql"
# 预期: STATUS 列显示 "(healthy)"

# 验证数据已加载
docker exec nl2sql-mysql mysql -uroot -pSimple@123 \
  -e "USE nl2sql_db; SELECT COUNT(*) FROM orders; SELECT COUNT(*) FROM products;"
# 预期输出:
#   COUNT(*)
#   30
#   COUNT(*)
#   15
```

---

## 2. 启动后端

**新开一个终端窗口**（保持 MySQL 运行）：

```bash
cd /Users/xy/PycharmProjects/PythonProject
source .venv/bin/activate

# 安装依赖（首次执行，约 30 秒）
pip install -r backend/requirements.txt

# 启动后端
DB_PASSWORD=Simple@123 uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**验证后端已启动：** 看到以下输出说明成功：
```
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**再开第二个终端**，验证健康检查：
```bash
curl http://localhost:8000/api/health
# 预期输出: {"status":"healthy","service":"NL2SQL","version":"1.0.0"}
```

---

## 3. API 功能测试（curl）

以下是 4 个核心测试用例，**复制整条命令逐个执行**。

### 测试 1: 分类销售额聚合查询

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "每种商品类别的总销售额是多少？"}' | python3 -m json.tool
```

**预期结果：**
```json
{
  "sql": "SELECT p.category, SUM(o.price * o.sales_volume) AS total_sales ...",
  "columns": ["category", "total_sales"],
  "data": [
    ["水果", ...],
    ["蔬菜", ...],
    ...
  ],
  "row_count": 7
}
```

✅ **通过标准**: `row_count > 0`，`columns` 包含 `category` 和 `total_sales`

---

### 测试 2: 时间序列趋势查询

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "每天的订单总金额是多少？按日期排序"}' | python3 -m json.tool
```

**预期结果：**
```json
{
  "columns": ["order_date", ...],
  "row_count": 10
}
```

✅ **通过标准**: `columns` 包含 `order_date`，数据按日期排列

---

### 测试 3: 用户排名查询

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "哪个用户下单金额最多？列出前5名"}' | python3 -m json.tool
```

**预期结果：** `columns` 包含 `user_id` 和金额列，数据 ≤ 5 行

✅ **通过标准**: `row_count > 0`

---

### 测试 4: 库存查询

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "各商品类别的平均库存是多少？"}' | python3 -m json.tool
```

**预期结果：** `columns` 包含 `category` 和 `avg_stock`

✅ **通过标准**: `row_count > 0`

---

## 4. SQL 安全测试

**这是最关键的测试——验证 SQL 注入和写操作被正确拦截。**

### 测试 5: DELETE 拦截

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "删除所有订单"}' | python3 -m json.tool
```

✅ **通过标准**: 返回 HTTP 403，`detail` 包含 "禁止" 或 "DELETE"

---

### 测试 6: DROP TABLE 拦截

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "把 products 表删掉"}' | python3 -m json.tool
```

✅ **通过标准**: 返回 HTTP 403，`detail` 包含 "禁止"

---

### 测试 7: UPDATE 拦截

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "把所有商品价格改为1元"}' | python3 -m json.tool
```

✅ **通过标准**: 返回 HTTP 400（LLM 拒绝生成）或 HTTP 403（安全层拦截）

---

### 测试 8: 非法问题处理

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "今天天气怎么样？"}' | python3 -m json.tool
```

✅ **通过标准**: 返回 HTTP 400，`detail` 包含 "无法"

---

### 测试 9: 空输入处理

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": ""}' | python3 -m json.tool
```

✅ **通过标准**: 返回 HTTP 400，提示问题不能为空

---

### 验证数据未被篡改

```bash
docker exec nl2sql-mysql mysql -uroot -pSimple@123 \
  -e "USE nl2sql_db; SELECT COUNT(*) AS total FROM orders;"
# 预期: total = 30（数据没有被 DELETE 掉）
```

---

## 5. 启动前端

**再开一个终端窗口**（保持 MySQL 和后端运行）：

```bash
cd /Users/xy/PycharmProjects/PythonProject/frontend

# 安装依赖（首次执行）
npm install

# 启动开发服务器
npm run dev
```

**预期输出：**
```
  VITE vX.X.X  ready in XXX ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

---

## 6. 前端界面测试

在浏览器打开 **http://localhost:5173**。

### 检查清单

| # | 检查项 | 操作 | 通过标准 |
|---|-------|------|---------|
| 1 | 页面加载 | 打开 http://localhost:5173 | 看到标题 "🤖 NL2SQL 智能查询系统" 和搜索框 |
| 2 | 推荐问题 | 查看搜索框下方 | 看到 4 个推荐问题按钮 |
| 3 | 点击推荐 | 点击第一个推荐问题，再点 "🔍 查询" | 看到加载动画 → 柱状图 + 数据表格 |
| 4 | 图表渲染 | 查看查询结果上方 | 柱状图显示各分类的销售数据 |
| 5 | 表格渲染 | 查看图表下方 | 表格包含 category 和 total_sales 列 |
| 6 | SQL 展开 | 点击 "查看生成的 SQL" | 深色代码块显示完整 SQL |
| 7 | 自由输入 | 输入 "每天的订单数" 并查询 | 显示折线图（因为包含 order_date 列） |
| 8 | 错误提示 | 输入 "abc123" 并查询 | 显示错误 Banner（如 LLM 无法转换为 SQL） |

---

## 7. 端到端场景测试

### 场景 A: 销售分析（柱状图）

1. 打开 http://localhost:5173
2. 输入：`每种商品类别的总销售额是多少？`
3. 点击 "🔍 查询"
4. **验证**: 看到柱状图 + 7 行数据表格，每行包含 category 和 total_sales

### 场景 B: 趋势分析（折线图）

1. 输入：`每天的订单总金额趋势`
2. 点击 "🔍 查询"
3. **验证**: 看到折线图（不是柱状图！）+ 按日期排列的数据

### 场景 C: 安全验证

1. 打开终端执行安全测试用例（测试 5-9）
2. **验证**: 所有写操作都被 403 拦截，数据未被篡改

### 场景 D: Swagger 文档

1. 打开 http://localhost:8000/api/docs
2. **验证**: 看到交互式 API 文档
3. 点击 `POST /api/query` → "Try it out"
4. 输入 `{"question": "查看所有商品"}` → Execute
5. **验证**: 直接在 Swagger 中看到查询结果

---

## 快速问题排查

| 问题 | 解决方案 |
|------|---------|
| MySQL 启动失败 | `docker compose down -v && docker compose up -d` |
| 端口 8000 被占用 | `lsof -ti:8000 \| xargs kill` |
| 端口 3306 被占用 | `brew services stop mysql`（如果本地有 MySQL） |
| LLM API 返回 502 | 检查网络 + API Key 是否有效 |
| 前端 404 错误 | 确认后端在 8000 端口运行中 |
| curl 返回空或乱码 | 加上 `-s` 静默模式，用 `python3 -m json.tool` 格式化 |

---

## 测试通过标准总结

全部通过 ✅ 表示系统功能完整：

- [ ] MySQL 容器正常运行，30 条订单 + 15 条商品数据就绪
- [ ] 后端健康检查返回 healthy
- [ ] 4 个功能查询全部返回正确数据
- [ ] SQL 注入/DELETE/DROP/UPDATE 均被拦截（403）
- [ ] 数据未被篡改（仍是 30 条订单）
- [ ] 前端可正常访问并展示图表和表格
- [ ] 柱状图（分类查询）和折线图（时间序列）均能正确渲染
- [ ] Swagger API 文档可访问和交互测试
