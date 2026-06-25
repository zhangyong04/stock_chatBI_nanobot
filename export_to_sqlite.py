import sqlite3
import pandas as pd

# 读取已有的 Excel 数据
xlsx_file = "stock_prices.xlsx"
df = pd.read_excel(xlsx_file, sheet_name="历史价格")
print(f"从 {xlsx_file} 读取了 {len(df)} 条记录。")

# ---------- 建表 SQL ----------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_daily (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_name      TEXT    NOT NULL,               -- 股票名称
    ts_code         TEXT    NOT NULL,               -- 股票代码
    trade_date      TEXT    NOT NULL,               -- 交易日期 (YYYY-MM-DD, ISO-8601)
    open            REAL,                           -- 开盘价
    high            REAL,                           -- 最高价
    low             REAL,                           -- 最低价
    close           REAL,                           -- 收盘价
    pre_close       REAL,                           -- 昨收价
    change          REAL,                           -- 涨跌额
    pct_chg         REAL,                           -- 涨跌幅(%)
    vol             REAL,                           -- 成交量(手)
    amount          REAL,                           -- 成交额(千元)
    UNIQUE(ts_code, trade_date)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_trade_date ON stock_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_ts_code    ON stock_daily(ts_code);
"""

# ---------- 写入 SQLite ----------
db_file = "stock_prices.db"
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# 建表（先删旧表确保干净）
cursor.execute("DROP TABLE IF EXISTS stock_daily")
cursor.execute(CREATE_TABLE_SQL)
cursor.executescript(CREATE_INDEX_SQL)

# 将 YYYYMMDD 转为 YYYY-MM-DD，便于 SQLite 日期函数运算
df["交易日期"] = pd.to_datetime(df["交易日期"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

# 将中文列名映射回英文字段名，与表结构对应
col_map = {
    "股票名称":    "stock_name",
    "股票代码":    "ts_code",
    "交易日期":    "trade_date",
    "开盘价":      "open",
    "最高价":      "high",
    "最低价":      "low",
    "收盘价":      "close",
    "昨收价":      "pre_close",
    "涨跌额":      "change",
    "涨跌幅(%)":   "pct_chg",
    "成交量(手)":  "vol",
    "成交额(千元)":"amount",
}
df = df.rename(columns=col_map)

# 只保留表中需要的列
db_cols = ["stock_name", "ts_code", "trade_date",
           "open", "high", "low", "close", "pre_close",
           "change", "pct_chg", "vol", "amount"]
df = df[[c for c in db_cols if c in df.columns]]

# 使用 INSERT OR IGNORE 避免重复插入
insert_sql = f"""
INSERT OR IGNORE INTO stock_daily ({', '.join(db_cols)})
VALUES ({', '.join(['?'] * len(db_cols))})
"""
rows = [tuple(row) for row in df.itertuples(index=False, name=None)]
cursor.executemany(insert_sql, rows)
conn.commit()

# 验证
count = cursor.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
print(f"数据已写入 {db_file}，表 stock_daily 当前共 {count} 条记录。")

# 打印建表 SQL 供参考
print("\n===== 建表 SQL =====")
print(CREATE_TABLE_SQL)
print("===== 索引 SQL =====")
print(CREATE_INDEX_SQL)

conn.close()
