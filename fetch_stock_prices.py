import os
import tushare as ts
import pandas as pd

# 从环境变量获取 token
token = os.environ.get("TUSHARE_TOKEN")
if not token:
    raise ValueError("环境变量 TUSHARE_TOKEN 未设置")

ts.set_token(token)
pro = ts.pro_api()

# 股票列表：名称 -> ts_code
stocks = {
    "贵州茅台": "600519.SH",
    "五粮液": "000858.SZ",
    "广发证券": "000776.SZ",
    "中芯国际": "688981.SH",
}

start_date = "20200101"
end_date = "20260616"

all_data = []

for name, ts_code in stocks.items():
    print(f"正在获取 {name} ({ts_code}) 的数据...")
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    df["股票名称"] = name
    all_data.append(df)

# 合并所有数据
result = pd.concat(all_data, ignore_index=True)

# 按股票代码、时间从小到大排序
result = result.sort_values(by=["ts_code", "trade_date"], ascending=[True, True])

# 重命名列为中文
col_map = {
    "股票名称": "股票名称",
    "ts_code": "股票代码",
    "trade_date": "交易日期",
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "pre_close": "昨收价",
    "change": "涨跌额",
    "pct_chg": "涨跌幅(%)",
    "vol": "成交量(手)",
    "amount": "成交额(千元)",
}
result = result.rename(columns=col_map)

# 调整列顺序
ordered_cols = [
    "股票名称", "股票代码", "交易日期",
    "开盘价", "最高价", "最低价", "收盘价", "昨收价",
    "涨跌额", "涨跌幅(%)", "成交量(手)", "成交额(千元)",
]
result = result[[c for c in ordered_cols if c in result.columns]]

# 保存到 xlsx
output_file = "stock_prices.xlsx"
with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
    result.to_excel(writer, sheet_name="历史价格", index=False)

print(f"数据已保存到 {output_file}，共 {len(result)} 条记录。")
