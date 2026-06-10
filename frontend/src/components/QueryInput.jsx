import { useState } from "react";

/**
 * 自然语言查询输入组件
 *
 * 功能:
 *   - 自由输入自然语言问题
 *   - 点击推荐问题自动填入并提交
 *   - Enter 键快捷提交
 *   - 加载状态下禁用交互
 */
export default function QueryInput({ onQuery, loading, targetTable }) {
  const [question, setQuestion] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || loading) return;
    onQuery(trimmed);
  };

  const handleSuggestionClick = (suggestion) => {
    setQuestion(suggestion);
    // 点击推荐问题自动提交（提升交互效率）
    if (!loading) {
      onQuery(suggestion);
    }
  };

  const suggestions = targetTable
    ? [
        "这个表按月份有什么变化？",
        "哪个类别的数量最多？",
        "为什么销售额下降？",
        "哪些字段缺失比较严重？",
        "这个表里有什么异常数据？",
      ]
    : [
        "本月销售额为什么下降？",
        "哪些地区拖累了整体利润？",
        "哪些渠道 ROI 变差？",
        "哪些商品退款率异常升高？",
      ];

  return (
    <div className="query-section">
      <form onSubmit={handleSubmit} className="query-form">
        <input
          type="text"
          className="query-input"
          placeholder={targetTable ? `针对 ${targetTable} 提问，例如：这个表按月份有什么变化？` : "输入业务问题，例如：本月销售额为什么下降？"}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <button type="submit" className="query-btn" disabled={loading}>
          {loading ? "⏳ 查询中..." : "🔍 查询"}
        </button>
      </form>
      <div className="suggestions">
        <span className="suggestions-label">💡 试试点击：</span>
        {suggestions.map((s, i) => (
          <button
            key={i}
            className="suggestion-chip"
            onClick={() => handleSuggestionClick(s)}
            disabled={loading}
            title={`点击直接查询：「${s}」`}
          >
            {s}
          </button>
        ))}
      </div>
      <p className="input-hint">
        按 <kbd>Enter</kbd> 提交查询，点击推荐问题自动搜索
      </p>
    </div>
  );
}
