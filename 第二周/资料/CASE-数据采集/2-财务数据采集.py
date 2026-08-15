# -*- coding: utf-8 -*-
"""财务数据采集：使用 Tushare Pro 下载沪深 A 股财报并写入 MySQL。

数据源：Tushare Pro 的 stock_basic、fina_indicator、income、balancesheet、cashflow。
运行前在终端设置 Token：
    export TUSHARE_TOKEN='你的 Tushare Token'
    python3 2-财务数据采集.py

Tushare 的财务接口通常需要相应积分权限（常见为 2000 积分）。脚本逐只处理，
请求失败不会中止全量任务；再次运行会跳过已由 Tushare 成功写入的股票。
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date

import pandas as pd
import tushare as ts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_config import execute_query, get_connection


# ============================================================
# 配置
# ============================================================
TEST_MODE = False
TEST_STOCK = "600519.SH"
DATA_START = "20150101"
DATA_END = date.today().strftime("%Y%m%d")
SLEEP_SECONDS = 0.4
RETRIES = 3
HTTP_TIMEOUT = 20

INSERT_SQL = """
    INSERT INTO trade_stock_financial
    (stock_code, report_date, revenue, net_profit, eps, roe, roa,
     gross_margin, net_margin, debt_ratio, current_ratio,
     operating_cashflow, total_assets, total_equity, data_source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    revenue=VALUES(revenue), net_profit=VALUES(net_profit), eps=VALUES(eps),
    roe=VALUES(roe), roa=VALUES(roa), gross_margin=VALUES(gross_margin),
    net_margin=VALUES(net_margin), debt_ratio=VALUES(debt_ratio),
    current_ratio=VALUES(current_ratio), operating_cashflow=VALUES(operating_cashflow),
    total_assets=VALUES(total_assets), total_equity=VALUES(total_equity),
    data_source=VALUES(data_source)
"""


def safe_float(value):
    if value is None or pd.isna(value):
        return None
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def safe_divide(numerator, denominator, pct=False):
    numerator, denominator = safe_float(numerator), safe_float(denominator)
    if numerator is None or denominator in (None, 0):
        return None
    result = numerator / denominator * (100 if pct else 1)
    return max(min(round(result, 4), 999999.9999), -999999.9999)


def get_pro():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("未设置 TUSHARE_TOKEN。先执行：export TUSHARE_TOKEN='你的 Token'")
    return ts.pro_api(token, timeout=HTTP_TIMEOUT)


def is_a_share(code: str) -> bool:
    """仅保留上交所/深交所正常 A 股，排除 B 股、北交所和指数。"""
    if not isinstance(code, str) or "." not in code:
        return False
    number, exchange = code.split(".", 1)
    return (
        exchange == "SH" and number.startswith(("600", "601", "603", "605", "688"))
    ) or (
        exchange == "SZ" and number.startswith(("000", "001", "002", "003", "300", "301"))
    )


def request_with_retry(request, label: str) -> pd.DataFrame:
    last_error = None
    for attempt in range(RETRIES):
        try:
            frame = request()
            time.sleep(SLEEP_SECONDS)
            return frame if frame is not None else pd.DataFrame()
        except Exception as error:
            last_error = error
            if attempt + 1 < RETRIES:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{label}: {last_error}") from last_error


def latest_by_period(frame: pd.DataFrame) -> pd.DataFrame:
    """每个报告期只保留最新公告/修订版，索引为 YYYYMMDD。"""
    if frame is None or frame.empty or "end_date" not in frame.columns:
        return pd.DataFrame()
    result = frame.copy()
    for column in ("end_date", "ann_date", "f_ann_date"):
        if column in result:
            result[column] = result[column].astype("string").str.replace(".0", "", regex=False).str.zfill(8)
    sort_columns = [column for column in ("end_date", "ann_date", "f_ann_date") if column in result]
    result = result.sort_values(sort_columns, kind="stable")
    result = result.drop_duplicates("end_date", keep="last")
    return result.set_index("end_date", drop=False)


def fetch_stock_frames(pro, stock_code: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    common = {"ts_code": stock_code, "start_date": DATA_START, "end_date": DATA_END}
    indicator = request_with_retry(
        lambda: pro.fina_indicator(
            **common,
            fields="ts_code,ann_date,end_date,eps,roe,roa,grossprofit_margin,netprofit_margin,debt_to_assets,current_ratio",
        ),
        f"fina_indicator {stock_code}",
    )
    income = request_with_retry(
        lambda: pro.income(
            **common,
            fields="ts_code,ann_date,f_ann_date,end_date,revenue,total_revenue,n_income,n_income_attr_p",
        ),
        f"income {stock_code}",
    )
    balance = request_with_retry(
        lambda: pro.balancesheet(
            **common,
            fields="ts_code,ann_date,f_ann_date,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int",
        ),
        f"balancesheet {stock_code}",
    )
    cashflow = request_with_retry(
        lambda: pro.cashflow(
            **common,
            fields="ts_code,ann_date,f_ann_date,end_date,n_cashflow_act",
        ),
        f"cashflow {stock_code}",
    )
    return tuple(latest_by_period(frame) for frame in (indicator, income, balance, cashflow))


def value_at(frame: pd.DataFrame, period: str, *columns: str):
    if frame.empty or period not in frame.index:
        return None
    row = frame.loc[period]
    for column in columns:
        if column in row.index and pd.notna(row[column]):
            return row[column]
    return None


def build_records(stock_code: str, frames) -> list[dict]:
    indicator, income, balance, cashflow = frames
    periods = sorted(set().union(*(set(frame.index) for frame in frames if not frame.empty)))
    records = []
    for period in periods:
        revenue = value_at(income, period, "revenue", "total_revenue")
        net_profit = value_at(income, period, "n_income_attr_p", "n_income")
        total_assets = value_at(balance, period, "total_assets")
        total_liab = value_at(balance, period, "total_liab")
        total_equity = value_at(balance, period, "total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int")
        operating_cashflow = value_at(cashflow, period, "n_cashflow_act")
        roe = value_at(indicator, period, "roe") or safe_divide(net_profit, total_equity, pct=True)
        gross_margin = value_at(indicator, period, "grossprofit_margin")
        net_margin = value_at(indicator, period, "netprofit_margin") or safe_divide(net_profit, revenue, pct=True)
        debt_ratio = value_at(indicator, period, "debt_to_assets") or safe_divide(total_liab, total_assets, pct=True)
        records.append({
            "stock_code": stock_code,
            "report_date": period,
            "revenue": safe_float(revenue),
            "net_profit": safe_float(net_profit),
            "eps": safe_float(value_at(indicator, period, "eps")),
            "roe": safe_float(roe),
            "roa": safe_float(value_at(indicator, period, "roa")),
            "gross_margin": safe_float(gross_margin),
            "net_margin": safe_float(net_margin),
            "debt_ratio": safe_float(debt_ratio),
            "current_ratio": safe_float(value_at(indicator, period, "current_ratio")),
            "operating_cashflow": safe_float(operating_cashflow),
            "total_assets": safe_float(total_assets),
            "total_equity": safe_float(total_equity),
        })
    return records


def get_pending_stocks(pro) -> list[str]:
    if TEST_MODE:
        return [TEST_STOCK]
    universe = request_with_retry(
        lambda: pro.stock_basic(exchange="", list_status="L", fields="ts_code"),
        "stock_basic",
    )
    all_codes = sorted(code for code in universe["ts_code"].dropna().tolist() if is_a_share(code))
    # 只跳过已由 Tushare 写入的股票；旧 QMT 记录会由本次数据覆盖。
    existing = execute_query("SELECT DISTINCT stock_code FROM trade_stock_financial WHERE data_source = 'tushare'")
    existing_codes = {row["stock_code"] for row in existing}
    return [code for code in all_codes if code not in existing_codes]


def write_records(records: list[dict]) -> int:
    if not records:
        return 0
    rows = [
        (
            record["stock_code"],
            f"{record['report_date'][:4]}-{record['report_date'][4:6]}-{record['report_date'][6:8]}",
            record["revenue"], record["net_profit"], record["eps"], record["roe"], record["roa"],
            record["gross_margin"], record["net_margin"], record["debt_ratio"], record["current_ratio"],
            record["operating_cashflow"], record["total_assets"], record["total_equity"], "tushare",
        )
        for record in records
    ]
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.executemany(INSERT_SQL, rows)
        connection.commit()
    finally:
        connection.close()
    return len(rows)


def print_summary():
    summary = execute_query("""
        SELECT COUNT(DISTINCT stock_code) AS stock_cnt, COUNT(*) AS row_cnt,
               MIN(report_date) AS min_date, MAX(report_date) AS max_date
        FROM trade_stock_financial WHERE data_source = 'tushare'
    """)
    row = summary[0]
    print(f"Tushare 数据概况：{row['stock_cnt']} 只股票，{row['row_cnt']:,} 条记录，"
          f"报告期 {row['min_date']} ~ {row['max_date']}")


def main() -> int:
    print("=" * 60)
    print("财务数据采集（Tushare Pro -> MySQL）")
    print(f"报告期范围：{DATA_START} ~ {DATA_END}")
    print("=" * 60)
    pro = get_pro()
    pending = get_pending_stocks(pro)
    print(f"待采集：{len(pending)} 只股票" + ("（测试模式）" if TEST_MODE else ""))
    if not pending:
        print_summary()
        return 0

    total_rows = 0
    successful = 0
    failures = []
    for index, stock_code in enumerate(pending, start=1):
        try:
            total_rows += write_records(build_records(stock_code, fetch_stock_frames(pro, stock_code)))
            successful += 1
        except Exception as error:
            failures.append((stock_code, str(error)))
            print(f"\n失败 {stock_code}: {error}")
        if index % 20 == 0 or index == len(pending):
            print(f"进度：{index}/{len(pending)}；成功 {successful}；写入 {total_rows:,} 条", flush=True)

    print(f"\n完成：成功 {successful}/{len(pending)} 只，写入 {total_rows:,} 条。")
    if failures:
        print(f"失败 {len(failures)} 只；直接重跑会继续处理未成功的股票。")
    print_summary()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
