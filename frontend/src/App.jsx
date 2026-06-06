import { useState, useEffect, useCallback } from "react";
import QueryInput from "./components/QueryInput";
import ResultTable from "./components/ResultTable";
import ResultChart from "./components/ResultChart";
import CsvUploader from "./components/CsvUploader";
import { detectChartConfig } from "./utils/chartDetector";
import { queryNL, apiClient } from "./api";
import "./App.css";

// ── 提取友好的错误信息 ──
function extractErrorMessage(err) {
  // 优先使用后端返回的 detail 字段
  const detail = err.response?.data?.detail;
  if (typeof detail === "string") return detail;
  // Pydantic 校验错误是数组格式，提取第一条
  if (Array.isArray(detail) && detail.length > 0) {
    return detail[0].msg || "请求参数校验失败";
  }
  return err.message || "查询失败，请稍后重试";
}

// ── 数据来源面板（底部固定展示） ──
function DataSourcePanel({ info }) {
  if (!info) return null;

  const { database, tables, pipeline } = info;

  return (
    <footer className="datasource-panel">
      <h3>🗄️ 数据来源 & 处理链路</h3>

      {/* 数据库信息 */}
      <div className="datasource-grid">
        <div className="datasource-card">
          <div className="card-icon">🛢️</div>
          <div className="card-content">
            <h4>数据库引擎</h4>
            <p>{database.engine}</p>
            <span className="card-meta">
              {database.host} / {database.name}
            </span>
          </div>
        </div>

        <div className="datasource-card">
          <div className="card-icon">📋</div>
          <div className="card-content">
            <h4>数据表</h4>
            {tables.map((t) => (
              <p key={t.table_name}>
                <code>{t.table_name}</code> — {t.row_count} 行
                {t.imported && <span className="imported-badge">📤 已导入</span>}
              </p>
            ))}
            <span className="card-meta">字符集: {database.charset}</span>
          </div>
        </div>

        <div className="datasource-card">
          <div className="card-icon">⚙️</div>
          <div className="card-content">
            <h4>处理链路</h4>
            <ol className="pipeline-list">
              {pipeline.map((s) => (
                <li key={s.step}>
                  <strong>{s.actor}</strong>：{s.action}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ── 主 App ──
function App() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [sourceInfo, setSourceInfo] = useState(null);

  // 页面加载时获取数据来源信息
  const fetchInfo = useCallback(async () => {
    try {
      const res = await apiClient.get("/api/info");
      setSourceInfo(res.data);
    } catch {
      // 后端未启动时静默失败
    }
  }, []);

  useEffect(() => {
    fetchInfo();
  }, [fetchInfo]);

  const handleQuery = async (question) => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await queryNL(question);
      setResult({
        ...data,
        chartConfig: detectChartConfig(data.columns, data.data),
      });
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  // CSV 导入完成后的回调
  const handleImportComplete = () => {
    fetchInfo(); // 刷新数据来源面板
  };

  // 查询导入的表
  const handleQueryTable = (tableName) => {
    handleQuery(`查看 ${tableName} 表的所有数据`);
  };

  return (
    <div className="app">
      {/* 头部 */}
      <header className="app-header">
        <h1>🤖 NL2SQL 智能查询系统</h1>
        <p className="subtitle">
          自然语言 → SQL → 数据可视化 | Powered by FastAPI + Claude + ECharts
        </p>
      </header>

      {/* 查询输入 */}
      <QueryInput onQuery={handleQuery} loading={loading} />

      {/* CSV 导入面板 */}
      <CsvUploader
        onImportComplete={handleImportComplete}
        onQueryTable={handleQueryTable}
      />

      {/* 加载状态 */}
      {loading && (
        <div className="loading">
          <div className="spinner" />
          <p>AI 正在分析问题并生成 SQL...</p>
        </div>
      )}

      {/* 错误信息 */}
      {error && (
        <div className="error-banner">
          <span className="error-icon">⚠️</span>
          <span>{error}</span>
        </div>
      )}

      {/* 查询结果 */}
      {result && (
        <div className="result-container">
          {result.columns.length > 0 && result.data.length > 0 && (
            <ResultChart
              columns={result.columns}
              data={result.data}
              chartConfig={result.chartConfig}
            />
          )}
          <ResultTable
            columns={result.columns}
            data={result.data}
            sql={result.sql}
          />
        </div>
      )}

      {/* 空状态 */}
      {!loading && !error && !result && (
        <div className="welcome">
          <div className="welcome-icon">💡</div>
          <h2>输入自然语言，探索你的数据</h2>
          <p>支持销售额分析、用户行为、库存查询、趋势分析等</p>
          <div className="feature-tags">
            <span>✅ SQL 安全过滤</span>
            <span>📊 智能图表选择</span>
            <span>🔒 只读查询保护</span>
            <span>⚡ 实时 DDL 注入</span>
            <span className="new-tag">📤 CSV 数据导入</span>
          </div>
        </div>
      )}

      {/* 数据来源面板（始终显示在底部） */}
      <DataSourcePanel info={sourceInfo} />
    </div>
  );
}

export default App;
