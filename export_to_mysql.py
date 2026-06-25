"""
stock_prices.xlsx → MySQL 智能增量导入脚本

逻辑：
  1. 检查数据库是否存在，不存在则创建
  2. 检查表是否存在，不存在则创建并全量导入
  3. 表存在时，校验列结构是否匹配：
     - 结构不匹配 → 备份旧表 → 重建表 → 全量导入
  4. 结构匹配时，查询每只股票已有最大日期，只插入新数据（增量导入）
"""

import os
import sys
from datetime import datetime

import pymysql
import pandas as pd

# ---------- 配置 ----------
HOST = "127.0.0.1"
PORT = 3306
DB_NAME = "stock"
TABLE_NAME = "stock_daily"
XLSX_FILE = "stock_prices.xlsx"

# 期望的表结构（列名 → MySQL 类型定义）
EXPECTED_COLUMNS = {
    "stock_name": "varchar(32)",
    "ts_code":    "varchar(16)",
    "trade_date": "date",
    "open":       "decimal(10,2)",
    "high":       "decimal(10,2)",
    "low":        "decimal(10,2)",
    "close":      "decimal(10,2)",
    "pre_close":  "decimal(10,2)",
    "change":     "decimal(10,2)",
    "pct_chg":    "decimal(8,4)",
    "vol":        "decimal(18,2)",
    "amount":     "decimal(18,2)",
}

DB_COLS = list(EXPECTED_COLUMNS.keys())

CREATE_DB_SQL = (
    f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
    f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
)

CREATE_TABLE_SQL = f"""
CREATE TABLE {TABLE_NAME} (
    id              INT             NOT NULL AUTO_INCREMENT,
    stock_name      VARCHAR(32)     NOT NULL            COMMENT '股票名称',
    ts_code         VARCHAR(16)     NOT NULL            COMMENT '股票代码',
    trade_date      DATE            NOT NULL            COMMENT '交易日期',
    `open`          DECIMAL(10,2)                       COMMENT '开盘价',
    high            DECIMAL(10,2)                       COMMENT '最高价',
    low             DECIMAL(10,2)                       COMMENT '最低价',
    `close`         DECIMAL(10,2)                       COMMENT '收盘价',
    pre_close       DECIMAL(10,2)                       COMMENT '昨收价',
    `change`        DECIMAL(10,2)                       COMMENT '涨跌额',
    pct_chg         DECIMAL(8,4)                        COMMENT '涨跌幅(%)',
    vol             DECIMAL(18,2)                       COMMENT '成交量(手)',
    amount          DECIMAL(18,2)                       COMMENT '成交额(千元)',
    PRIMARY KEY (id),
    UNIQUE KEY uk_code_date (ts_code, trade_date),
    INDEX idx_trade_date (trade_date),
    INDEX idx_ts_code (ts_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股票日线行情';
"""

# Excel 列名 → 数据库列名
COL_MAP = {
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


# ==================== 辅助函数 ====================

def get_env_config():
    """从环境变量获取 MySQL 连接信息"""
    username = os.environ.get("MYSQL_USERNAME")
    password = os.environ.get("MYSQL_PASSWORD")
    if not username or not password:
        raise ValueError("环境变量 MYSQL_USERNAME 和 MYSQL_PASSWORD 必须设置")
    return username, password


def read_and_prepare_excel():
    """读取 Excel 并标准化列名/格式"""
    df = pd.read_excel(XLSX_FILE, sheet_name="历史价格")
    print(f"[读取] 从 {XLSX_FILE} 读取了 {len(df)} 条记录")

    # 日期格式化
    df["交易日期"] = pd.to_datetime(df["交易日期"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

    # 列名映射
    df = df.rename(columns=COL_MAP)
    df = df[[c for c in DB_COLS if c in df.columns]]
    return df


def database_exists(cursor, db_name):
    """检查数据库是否存在"""
    cursor.execute("SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = %s", (db_name,))
    return cursor.fetchone() is not None


def table_exists(cursor, db_name, table_name):
    """检查表是否存在"""
    cursor.execute(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (db_name, table_name),
    )
    return cursor.fetchone() is not None


def get_table_columns(cursor, db_name, table_name):
    """获取表的列名及类型（排除自增主键 id），返回 {col_name: col_type}"""
    cursor.execute(
        "SELECT COLUMN_NAME, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME != 'id' "
        "ORDER BY ORDINAL_POSITION",
        (db_name, table_name),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def columns_match(existing_cols):
    """比较现有列与期望列是否匹配（忽略类型参数中的长度差异，只比较基础类型）"""
    for col, expected_type in EXPECTED_COLUMNS.items():
        if col not in existing_cols:
            return False, f"缺少列: {col}"
        actual = existing_cols[col].lower()
        expected = expected_type.lower()
        # 比较基础类型名（varchar/decimal/date 等），忽略括号内参数
        if actual.split("(")[0] != expected.split("(")[0]:
            return False, f"列 {col} 类型不匹配: 现有 {actual}, 期望 {expected}"
    return True, "OK"


def get_max_dates_per_stock(cursor):
    """查询每只股票在库中的最大交易日期，返回 {ts_code: max_date_str}"""
    cursor.execute(
        f"SELECT ts_code, MAX(trade_date) AS max_date FROM {TABLE_NAME} GROUP BY ts_code"
    )
    return {row[0]: row[1].strftime("%Y-%m-%d") if hasattr(row[1], "strftime") else str(row[1])
            for row in cursor.fetchall()}


def backup_and_rebuild(cursor, conn):
    """备份旧表并重建"""
    backup_name = f"{TABLE_NAME}_bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"[备份] 将旧表重命名为 {backup_name}")
    cursor.execute(f"RENAME TABLE {TABLE_NAME} TO {backup_name}")
    conn.commit()

    print("[重建] 创建新表...")
    cursor.execute(CREATE_TABLE_SQL)
    conn.commit()


def insert_rows(cursor, conn, df):
    """批量插入数据行"""
    if df.empty:
        print("[跳过] 无数据需要插入")
        return 0

    quoted_cols = [f"`{c}`" for c in DB_COLS if c in df.columns]
    placeholders = ", ".join(["%s"] * len(quoted_cols))
    insert_sql = f"INSERT IGNORE INTO {TABLE_NAME} ({', '.join(quoted_cols)}) VALUES ({placeholders})"

    rows = []
    for row in df.itertuples(index=False, name=None):
        rows.append(tuple(None if pd.isna(v) else v for v in row))

    cursor.executemany(insert_sql, rows)
    conn.commit()
    inserted = cursor.rowcount
    return inserted


def get_total_count(cursor):
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    return cursor.fetchone()[0]


# ==================== 主流程 ====================

def main():
    username, password = get_env_config()
    df = read_and_prepare_excel()

    # ---- 第 1 步：确保数据库存在 ----
    print(f"\n{'='*50}")
    print(f"[步骤1] 检查数据库 `{DB_NAME}` ...")
    conn = pymysql.connect(host=HOST, port=PORT, user=username, password=password,
                           charset="utf8mb4", autocommit=False)
    cursor = conn.cursor()

    db_existed = database_exists(cursor, DB_NAME)
    if not db_existed:
        print(f"  → 数据库不存在，创建中...")
        cursor.execute(CREATE_DB_SQL)
        conn.commit()
        print(f"  → 数据库 `{DB_NAME}` 已创建")
    else:
        print(f"  → 数据库已存在 ✓")

    cursor.close()
    conn.close()

    # ---- 第 2 步：连接目标库，检查表 ----
    print(f"\n[步骤2] 检查表 `{TABLE_NAME}` ...")
    conn = pymysql.connect(host=HOST, port=PORT, user=username, password=password,
                           database=DB_NAME, charset="utf8mb4", autocommit=False)
    cursor = conn.cursor()

    tbl_existed = table_exists(cursor, DB_NAME, TABLE_NAME)

    if not tbl_existed:
        # 表不存在 → 创建 + 全量导入
        print("  → 表不存在，创建中...")
        cursor.execute(CREATE_TABLE_SQL)
        conn.commit()
        print("  → 表已创建")

        print(f"\n[步骤3] 全量导入 {len(df)} 条数据...")
        inserted = insert_rows(cursor, conn, df)
        total = get_total_count(cursor)
        print(f"  → 插入 {inserted} 条，表中共 {total} 条记录")

    else:
        # 表存在 → 检查结构
        print("  → 表已存在 ✓")
        existing_cols = get_table_columns(cursor, DB_NAME, TABLE_NAME)
        matched, msg = columns_match(existing_cols)

        if not matched:
            # 结构不匹配 → 备份 + 重建 + 全量导入
            print(f"\n[结构不匹配] {msg}")
            print("  → 将备份旧表并重建...")
            backup_and_rebuild(cursor, conn)

            print(f"\n[步骤3] 全量导入 {len(df)} 条数据...")
            inserted = insert_rows(cursor, conn, df)
            total = get_total_count(cursor)
            print(f"  → 插入 {inserted} 条，表中共 {total} 条记录")

        else:
            # 结构匹配 → 增量导入
            print(f"  → 表结构匹配 ✓")
            max_dates = get_max_dates_per_stock(cursor)
            print(f"\n[步骤3] 增量导入（库中已有 {len(max_dates)} 只股票的数据）...")

            # 按每只股票的最大日期过滤，只保留新数据
            dfs_to_insert = []
            for ts_code, max_date in max_dates.items():
                stock_df = df[df["ts_code"] == ts_code]
                new_rows = stock_df[stock_df["trade_date"] > max_date]
                if not new_rows.empty:
                    dfs_to_insert.append(new_rows)
                    print(f"  → {ts_code}: 库中最新 {max_date}, 新增 {len(new_rows)} 条")

            # 库中完全没有的股票
            existing_codes = set(max_dates.keys())
            for code in df["ts_code"].unique():
                if code not in existing_codes:
                    new_stock_df = df[df["ts_code"] == code]
                    dfs_to_insert.append(new_stock_df)
                    print(f"  → {code}: 新股票, 全量导入 {len(new_stock_df)} 条")

            if dfs_to_insert:
                insert_df = pd.concat(dfs_to_insert, ignore_index=True)
                print(f"\n  共需增量插入 {len(insert_df)} 条新数据...")
                inserted = insert_rows(cursor, conn, insert_df)
                print(f"  → 实际插入 {inserted} 条（其余为已有数据已跳过）")
            else:
                print("  → 无新数据需要插入，所有股票数据已是最新 ✓")

            total = get_total_count(cursor)
            print(f"\n  表中共 {total} 条记录")

    cursor.close()
    conn.close()

    print(f"\n{'='*50}")
    print(f"导入完成！MySQL {HOST}:{PORT}/{DB_NAME}.{TABLE_NAME}")


if __name__ == "__main__":
    main()
