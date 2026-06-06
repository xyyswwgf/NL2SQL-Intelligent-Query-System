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
export default function QueryInput({ onQuery, loading }) {
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

  const suggestions = [
    "每种商品类别的总销售额是多少？",
    "每天的订单总金额趋势？",
    "哪些用户下单最多？",
    "各类别商品的库存情况？",
  ];

  return (
    <div className="query-section">
      <form onSubmit={handleSubmit} className="query-form">
        <input
          type="text"
          className="query-input"
          placeholder="输入自然语言问题，例如：每种商品类别的销售额排名？"
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
