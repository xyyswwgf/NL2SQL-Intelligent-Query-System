/**
 * =========================================================================
 * 图表类型智能检测器 — Chart Type Detector
 * =========================================================================
 *
 * 职责:
 *   根据 SQL 查询返回的列名和数据特征，自动推断最合适的 ECharts 图表类型。
 *   用户无需手动选择图表——系统根据数据"形状"自动决策。
 *
 * 推断规则（优先级从高到低）:
 *   1. 有日期/时间列 + 数值列 → line  (折线图，展示趋势)
 *   2. 有分类列 + 数值列        → bar   (柱状图，展示对比)
 *   3. 无可用推断              → bar   (默认柱状图)
 *
 * 关于饼图:
 *   饼图适合展示"部分与整体的比例关系"，但信息密度低、对比困难。
 *   当前系统优先选择柱状图/折线图，饼图作为可选的二次渲染类型预留。
 *   如需饼图，可在前端增加切换按钮（未来迭代）。
 * =========================================================================
 */

// ---------------------------------------------------------------------------
// 日期/时间列名识别模式
// ---------------------------------------------------------------------------
// 匹配中英文常见的日期时间字段名
// 注意顺序：更具体的模式放在前面，避免 "updated_at" 被误判为 "date"

const DATE_COLUMN_PATTERNS = [
  /date/i,       // order_date, created_date
  /time/i,       // create_time, update_time
  /日期/,         // 订单日期
  /时间/,         // 创建时间
  /_at$/,        // created_at, updated_at
  /_on$/,        // ordered_on
  /年$/,          // 财年
  /月$/,          // 月份
  /日$/,          // 日期
  /day/i,
  /month/i,
  /year/i,
  /created/i,
  /updated/i,
];

// ---------------------------------------------------------------------------
// 数值列识别
// ---------------------------------------------------------------------------

/**
 * 判断某个单元格值是否为数值类型（可用于 Y 轴）
 *
 * 注意: pymysql 返回的 DECIMAL 字段是 Python Decimal，序列化后变为字符串。
 * 因此需要同时检查 number 和数字格式的 string。
 *
 * @param {string} colName   - 列名（预留，未来可加入语义判断）
 * @param {*}      cellValue - 该列第一行的值（采样）
 * @returns {boolean}
 */
function isNumericValue(colName, cellValue) {
  if (cellValue === undefined || cellValue === null) {
    return false;
  }

  // JavaScript number（包括整数和浮点数）
  if (typeof cellValue === "number" && Number.isFinite(cellValue)) {
    return true;
  }

  // pymysql DECIMAL 类型可能序列化为字符串 "89.00"
  if (typeof cellValue === "string" && /^-?\d+(\.\d+)?$/.test(cellValue)) {
    return true;
  }

  return false;
}

// ---------------------------------------------------------------------------
// 主入口
// ---------------------------------------------------------------------------

/**
 * 根据列名和数据推断最合适的图表类型
 *
 * @param {string[]} columns - SQL 查询结果的列名列表
 * @param {any[][]}   data    - 二维数据数组，data[row][col]
 * @returns {{ chartType: 'bar'|'line', xAxis: string, yAxis: string[] }}
 *
 * @example
 *   // 日期列 + 数值列 → 折线图
 *   detectChartConfig(
 *     ['order_date', 'total_sales'],
 *     [['2026-05-01', 1500], ['2026-05-02', 2000]]
 *   )
 *   // => { chartType: 'line', xAxis: 'order_date', yAxis: ['total_sales'] }
 *
 * @example
 *   // 分类列 + 数值列 → 柱状图
 *   detectChartConfig(
 *     ['category', 'total_sales'],
 *     [['水果', 1500], ['蔬菜', 800]]
 *   )
 *   // => { chartType: 'bar', xAxis: 'category', yAxis: ['total_sales'] }
 */
export function detectChartConfig(columns, data) {
  // ── 边界条件 ──
  if (!columns || columns.length === 0 || !data || data.length === 0) {
    return { chartType: "bar", xAxis: "", yAxis: [] };
  }

  // ── 按类型分桶：日期列 / 数值列 / 文本列 ──
  const dateColumns = [];
  const numericColumns = [];
  const textColumns = [];

  const firstRow = data[0];

  columns.forEach((colName, index) => {
    const sampleValue = firstRow[index];

    if (DATE_COLUMN_PATTERNS.some((pattern) => pattern.test(colName))) {
      dateColumns.push(colName);
    } else if (isNumericValue(colName, sampleValue)) {
      numericColumns.push(colName);
    } else {
      textColumns.push(colName);
    }
  });

  // ── 推断 X 轴 ──
  // 优先级：日期列 > 文本列 > 第一列（兜底）
  const xAxis = dateColumns[0] || textColumns[0] || columns[0];

  // ── 推断 Y 轴 ──
  // 如果有数值列，用所有数值列；否则用最后一列（兜底）
  const yAxis = numericColumns.length > 0 ? numericColumns : [columns[columns.length - 1]];

  // ── 推断图表类型 ──
  // 规则: 有日期列 + 有数值列 → 折线图（展示时间序列趋势）
  if (dateColumns.length > 0 && numericColumns.length > 0) {
    return { chartType: "line", xAxis, yAxis };
  }

  // 默认 → 柱状图（对比不同类别的数值大小）
  return { chartType: "bar", xAxis, yAxis };
}
