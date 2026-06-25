# Long-term Memory

## Stock Analysis Context
- User is conducting technical analysis on Chinese A-share stocks
- Primary stocks of interest: 贵州茅台 (600519.SH) and 中芯国际 (688981.SH)
- Analysis date: 2026-06-16/17

## 2025 Annual Performance Comparison
- **中芯国际 (688981.SH)**: +36.54% (89.96元 → 122.83元), 113 up days / 123 down days
- **贵州茅台 (600519.SH)**: -7.45% (1488.0元 → 1377.18元), 115 up days / 127 down days
- Market style shifted from consumer blue chips to tech growth in 2025
- 中芯国际 benefited from domestic substitution and AI chip demand

## ARIMA Prediction - 贵州茅台
- Model: ARIMA(5,1,5), AIC=2096.38
- Historical data: 244 trading days (2025-06-16 to 2026-06-16)
- 10-day forecast (2026-06-17 to 2026-06-30): 1257-1267元 range
- Predicted slight uptrend of ~0.59%
- 95% confidence interval width: ~60-70元

## Bollinger Bands Analysis - 中芯国际 (Past Year)
- Detection period: 2025-06-17 to 2026-06-17 (237 trading days)
- **Overbought signals**: 22 days (9.3%)
  - 5 distinct phases: Jun 2025, Jul 2025, Aug 2025, Dec 2025-Jan 2026, Apr-May 2026
  - Most extreme: 2026-05-25 at 156元 (+9.42% above upper band)
  - Second: 2025-08-28 at 119.22元 (+8.49%)
  - Third: 2025-08-22 at 103.97元 (+6.28%)
- **Oversold signals**: 5 days (2.1%)
  - Concentrated in Feb 2026 (4 consecutive days: Feb 2-5) and Mar 23, 2026
  - Most extreme: 2026-02-05 at 111.8元 (-1.6% below lower band)
- **Key insight**: 22:5 overbought-to-oversold ratio indicates strong uptrend; overbought deviations much larger than oversold (max 9.42% vs 1.6%)
- **Trading implications**: Extreme overbought (>5% deviation) often precedes corrections; oversold areas provide buying opportunities

## Tools Used
- SQL query for historical stock data
- arima_stock for price prediction
- boll_detection for Bollinger Bands anomaly detection