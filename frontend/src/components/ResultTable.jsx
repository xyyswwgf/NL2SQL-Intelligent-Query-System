import { useState } from "react";

/**
 * 表格展示组件
 *
 * 功能:
 *   - 展示查询结果数据表格
 *   - 可展开查看生成的 SQL，支持一键复制
 *   - 自动识别数字列并格式化显示（千分位、小数位）
 *   - 空数据友好提示
 */

// ── 数字格式化 ──
function formatCellValue(value) {
  if (value === null || value === undefined) return "—";

  // 数字类型：添加千分位分隔符
  if (typeof value === "number" && Number.isFinite(value)) {
    // 整数直接千分位
    if (Number.isInteger(value)) {
      return value.toLocaleString("zh-CN");
    }
    // 小数保留原精度，最多 4 位
    return value.toLocaleString("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
  }

  // 字符串数字也格式化
  if (typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value)) {
    const num = parseFloat(value);
    if (!isNaN(num)) {
      return num.toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      });
    }
  }

  return String(value);
}

// ── SQL 复制按钮 ──
function SqlBlock({ sql }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 降级方案：选中文本
      const pre = document.getElementById("sql-code-block");
      if (pre) {
        const range = document.createRange();
        range.selectNode(pre);
        window.getSelection()?.removeAllRanges();
        window.getSelection()?.addRange(range);
      }
    }
  };

  if (!sql) return null;

  return (
    <details className="sql-details">
      <summary>📝 查看生成的 SQL</summary>
      <div className="sql-block-wrapper">
        <pre id="sql-code-block" className="sql-code">{sql}</pre>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? "✅ 已复制" : "📋 复制"}
        </button>
      </div>
    </details>
  );
}

// ── 空状态 ──
function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-icon">📭</div>
      <p>查询未返回任何数据</p>
      <span className="empty-hint">请尝试调整查询条件或换一个问题</span>
    </div>
  );
}

// ── 主组件 ──
export default function ResultTable({ columns, data, sql }) {
  if (!columns || columns.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="result-section">
      <div className="result-header">
        <h3>
          📊 查询结果（共{" "}
          <span className="row-count">{data.length}</span>{" "}
          条记录）
        </h3>
      </div>

      {/* 显示生成的 SQL */}
      <SqlBlock sql={sql} />

      {/* 数据表格 */}
      <div className="table-wrapper">
        <table className="result-table">
          <thead>
            <tr>
              <th className="col-index">#</th>
              {columns.map((col, i) => (
                <th key={i}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, rowIdx) => (
              <tr key={rowIdx}>
                <td className="col-index">{rowIdx + 1}</td>
                {row.map((cell, cellIdx) => (
                  <td key={cellIdx}>{formatCellValue(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
