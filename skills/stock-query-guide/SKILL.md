---
name: stock-query-guide
description: "股票查询参考问答：年度涨跌幅计算、走势查询、价格预测等 SQL 编写指南"
---

# 股票查询参考问答

在生成 SQL 查询前，请先参考以下计算思路，避免查询过多不必要的数据。

## Q1：年度涨跌幅对比

**关键词**：对比、涨跌幅、走势、年度、全年、表现、收益率、谁涨得多

**注意**："涨跌幅走势"≠"每日涨跌幅数据"。当用户问"涨跌幅走势"时，应计算年度累计涨跌幅（首尾收盘价对比），而非查询每日数据。

**计算思路**：
计算年度涨跌幅时，不需要查询每日数据，只需查询首尾两个交易日的收盘价。

**SQL 思路**：
1. 找到该年第一个交易日的收盘价：`WHERE trade_date = (SELECT MIN(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%')`
2. 找到该年最后一个交易日的收盘价：`WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%')`
3. 涨跌幅计算公式：`(最后一天收盘价 - 第一天收盘价) / 第一天收盘价 * 100%`

**示例 SQL**：
```sql
SELECT stock_name,
  MAX(CASE WHEN trade_date = (SELECT MIN(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%' AND ts_code = t.ts_code) THEN `close` END) AS first_close,
  MAX(CASE WHEN trade_date = (SELECT MAX(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%' AND ts_code = t.ts_code) THEN `close` END) AS last_close,
  ROUND((MAX(CASE WHEN trade_date = (SELECT MAX(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%' AND ts_code = t.ts_code) THEN `close` END)
       - MAX(CASE WHEN trade_date = (SELECT MIN(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%' AND ts_code = t.ts_code) THEN `close` END))
       / MAX(CASE WHEN trade_date = (SELECT MIN(trade_date) FROM stock_daily WHERE trade_date LIKE '2025%' AND ts_code = t.ts_code) THEN `close` END) * 100, 2) AS pct_chg
FROM stock_daily t
WHERE trade_date LIKE '2025%' AND stock_name IN ('贵州茅台', '中芯国际')
GROUP BY stock_name;
```

## Q2：查询走势/趋势

**关键词**：走势、趋势、每日、日线、历史数据

**计算思路**：
查询每日数据时，返回 `trade_date`、`stock_name` 和所需指标列，保留 `stock_name` 列以便图表按股票分组。

## Q3：预测未来价格

**计算思路**：
需要使用 `arima_stock` 工具进行预测，然后回复用户，这里要对股票的未来价格进行解释，比如后续价格是怎样的。
