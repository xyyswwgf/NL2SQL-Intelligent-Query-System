import { useState, useEffect, useCallback } from "react";
import ReactECharts from "echarts-for-react";
import QueryInput from "./components/QueryInput";
import ResultTable from "./components/ResultTable";
import ResultChart from "./components/ResultChart";
import CsvUploader from "./components/CsvUploader";
import { detectChartConfig } from "./utils/chartDetector";
import {
  queryNL,
  analyzeQuestion,
  analyzeTableQuestion,
  getAnalysisHistory,
  getAnalysisDetail,
  apiClient,
} from "./api";
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

function MetricGrid({ metrics }) {
  if (!metrics?.length) return null;
  return (
    <section className="metric-grid">
      {metrics.map((metric) => (
        <div className="metric-card" key={metric.name}>
          <span className="metric-name">{metric.name}</span>
          <strong>{formatMetric(metric.current, metric.name)}</strong>
          <small className={metric.change >= 0 ? "metric-up" : "metric-down"}>
            环比 {formatPercent(metric.change_rate)}
          </small>
        </div>
      ))}
    </section>
  );
}

function AgentSteps({ steps }) {
  if (!steps?.length) return null;
  return (
    <section className="agent-panel">
      <h3>Agent 执行步骤</h3>
      <div className="step-timeline">
        {steps.map((step) => (
          <div className="step-item" key={step.name}>
            <span className={`step-dot ${step.status}`} />
            <div>
              <strong>{step.name}</strong>
              <p>{step.summary}</p>
              <small>{step.elapsed_ms}ms</small>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function AgentCharts({ charts }) {
  if (!charts?.length) return null;
  return (
    <section className="agent-charts">
      {charts.map((chart) => (
        <div className="agent-chart" key={chart.title}>
          <h3>{chart.title}</h3>
          <ReactECharts
            option={chart.echarts_option}
            style={{ height: 320, width: "100%" }}
            notMerge
            lazyUpdate
          />
        </div>
      ))}
    </section>
  );
}

function AttributionPanel({ attribution }) {
  if (!attribution || Object.keys(attribution).length === 0) return null;
  const sections = [
    { key: "region", title: "地区 GMV 归因", label: "省份", value: "change" },
    { key: "category", title: "品类 GMV 归因", label: "品类", value: "change" },
    { key: "refund", title: "退款率异常", label: "品类", value: "current", percent: true },
    { key: "roi", title: "渠道 ROI 变化", label: "渠道", value: "change" },
    { key: "conversion_north", title: "华北转化率变化", label: "渠道", value: "change", percent: true },
  ];

  return (
    <section className="attribution-grid">
      {sections.map((section) => {
        const rows = attribution[section.key] || [];
        if (!rows.length) return null;
        return (
          <div className="attribution-card" key={section.key}>
            <h3>{section.title}</h3>
            <table>
              <thead>
                <tr>
                  <th>{section.label}</th>
                  <th>上期</th>
                  <th>本期</th>
                  <th>{section.value === "current" ? "当前值" : "变化"}</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 5).map((row) => (
                  <tr key={row[section.label]}>
                    <td>{row[section.label]}</td>
                    <td>{section.percent ? formatPercent(row.previous) : formatMetric(row.previous)}</td>
                    <td>{section.percent ? formatPercent(row.current) : formatMetric(row.current)}</td>
                    <td className={Number(row[section.value]) >= 0 ? "metric-up" : "metric-down"}>
                      {section.percent ? formatPercent(row[section.value]) : formatMetric(row[section.value])}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}

function AgentReport({ report, knowledge, runId }) {
  if (!report?.summary) return null;
  return (
    <section className="agent-report">
      <div className="report-header">
        <h3>分析报告</h3>
        {runId && (
          <div className="report-actions">
            <a href={`/api/analysis/${runId}/export?format=markdown`}>导出 MD</a>
            <a href={`/api/analysis/${runId}/export?format=html`}>导出 HTML</a>
          </div>
        )}
      </div>
      <p className="report-summary">{report.summary}</p>
      <div className="report-columns">
        <div>
          <h4>关键发现</h4>
          <ul>
            {report.findings?.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>建议动作</h4>
          <ul>
            {report.recommendations?.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
      {knowledge?.length > 0 && (
        <details className="knowledge-details">
          <summary>查看引用的业务知识</summary>
          {knowledge.map((item, index) => (
            <p key={index}>
              <code>{item.source}</code> {item.content}
            </p>
          ))}
        </details>
      )}
    </section>
  );
}

function SqlTrace({ queries }) {
  if (!queries?.length) return null;
  return (
    <section className="agent-panel">
      <h3>SQL 执行记录</h3>
      <div className="sql-trace-list">
        {queries.map((query) => (
          <details key={query.id} className="sql-details">
            <summary>{query.purpose} · {query.row_count} 行</summary>
            <pre className="sql-code">{query.sql}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}

function AgentResult({ result }) {
  if (!result) return null;
  return (
    <div className="agent-result">
      <MetricGrid metrics={result.metrics} />
      <AgentSteps steps={result.steps} />
      <AgentCharts charts={result.charts} />
      <AttributionPanel attribution={result.attribution} />
      <AgentReport report={result.report} knowledge={result.knowledge} runId={result.run_id} />
      <SqlTrace queries={result.sql_queries} />
    </div>
  );
}

function AnalysisHistory({ items, activeRunId, onSelect }) {
  if (!items?.length) return null;
  return (
    <aside className="history-panel">
      <div className="history-header">
        <h3>最近分析</h3>
        <span>{items.length} 条</span>
      </div>
      <div className="history-list">
        {items.map((item) => (
          <button
            type="button"
            key={item.run_id}
            className={item.run_id === activeRunId ? "history-item active" : "history-item"}
            onClick={() => onSelect(item.run_id)}
          >
            <strong>{item.question}</strong>
            <small>{item.summary || item.status}</small>
          </button>
        ))}
      </div>
    </aside>
  );
}

function formatPercent(value) {
  const num = Number(value || 0);
  return `${(num * 100).toFixed(2)}%`;
}

function formatMetric(value, name) {
  const num = Number(value || 0);
  if (name?.includes("率")) return formatPercent(num);
  return num.toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
  });
}

// ── 主 App ──
function App() {
  const [mode, setMode] = useState("agent");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [agentResult, setAgentResult] = useState(null);
  const [historyItems, setHistoryItems] = useState([]);
  const [targetTable, setTargetTable] = useState(null);
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

  const fetchHistory = useCallback(async () => {
    try {
      const res = await getAnalysisHistory();
      setHistoryItems(res.items || []);
    } catch {
      // 分析历史是增强能力，后端未就绪时不阻断主流程
    }
  }, []);

  useEffect(() => {
    fetchInfo();
    fetchHistory();
  }, [fetchInfo, fetchHistory]);

  const handleQuery = async (question, forcedMode = null) => {
    const activeMode = forcedMode || mode;
    setLoading(true);
    setError(null);
    setResult(null);
    setAgentResult(null);

    try {
      if (activeMode === "agent") {
        const data = targetTable
          ? await analyzeTableQuestion(targetTable, question)
          : await analyzeQuestion(question);
        setAgentResult(data);
        fetchHistory();
      } else {
        const data = await queryNL(question);
        setResult({
          ...data,
          chartConfig: detectChartConfig(data.columns, data.data),
        });
      }
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
    setTargetTable(null);
    setMode("query");
    handleQuery(`查看 ${tableName} 表的所有数据`, "query");
  };

  const handleAnalyzeTable = (tableName) => {
    setTargetTable(tableName);
    setMode("agent");
    setResult(null);
    setAgentResult(null);
    setError(null);
  };

  const clearTargetTable = () => {
    setTargetTable(null);
    setAgentResult(null);
    setError(null);
  };

  const handleSelectHistory = async (runId) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setMode("agent");
    try {
      const data = await getAnalysisDetail(runId);
      setAgentResult(data);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      {/* 头部 */}
      <header className="app-header">
        <h1>数据智能 Agent 工作台</h1>
        <p className="subtitle">
          业务问题 → Agent 规划 → PostgreSQL 查询 → 归因分析 → 图表报告
        </p>
      </header>

      <div className="mode-switch">
        <button
          className={mode === "agent" ? "active" : ""}
          onClick={() => setMode("agent")}
          disabled={loading}
        >
          分析 Agent
        </button>
        <button
          className={mode === "query" ? "active" : ""}
          onClick={() => setMode("query")}
          disabled={loading}
        >
          SQL 查询
        </button>
      </div>

      <div className="demo-note">
        {targetTable ? (
          <>
            当前正在分析导入表 <code>{targetTable}</code>。通用 CSV Agent 会根据字段自动识别时间列、指标列和维度列。
            <button type="button" className="inline-action" onClick={clearTargetTable}>切回内置经营 demo</button>
          </>
        ) : (
          "当前为内置经营分析 demo，适合展示完整业务归因；导入 CSV 后可点击表旁的 Agent 分析进入真实数据通用分析。"
        )}
      </div>

      {/* 查询输入 */}
      <QueryInput onQuery={handleQuery} loading={loading} targetTable={targetTable} />

      {/* CSV 导入面板 */}
      <CsvUploader
        onImportComplete={handleImportComplete}
        onQueryTable={handleQueryTable}
        onAnalyzeTable={handleAnalyzeTable}
      />

      <AnalysisHistory
        items={historyItems}
        activeRunId={agentResult?.run_id}
        onSelect={handleSelectHistory}
      />

      {/* 加载状态 */}
      {loading && (
        <div className="loading">
          <div className="spinner" />
          <p>{mode === "agent" ? "Agent 正在规划、查询并生成报告..." : "AI 正在分析问题并生成 SQL..."}</p>
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

      {agentResult && <AgentResult result={agentResult} />}

      {/* 空状态 */}
      {!loading && !error && !result && !agentResult && (
        <div className="welcome">
          <div className="welcome-icon">▣</div>
          <h2>输入经营问题，查看自动分析链路</h2>
          <p>推荐先试：本月销售额为什么下降？</p>
          <div className="feature-tags">
            <span>LangGraph 工作流</span>
            <span>多条 SQL 分析</span>
            <span>归因分析</span>
            <span>ECharts 图表</span>
            <span className="new-tag">CSV 自动识别</span>
          </div>
        </div>
      )}

      {/* 数据来源面板（始终显示在底部） */}
      <DataSourcePanel info={sourceInfo} />
    </div>
  );
}

export default App;
