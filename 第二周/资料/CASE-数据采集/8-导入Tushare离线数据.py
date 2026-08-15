#!/usr/bin/env python3
"""清洗并导入 /Volumes/拍摄02/沪深A股_Tushare 的离线数据到 wucai_trade。"""
from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path

from db_config import get_connection

ROOT = Path('/Volumes/拍摄02/沪深A股_Tushare')
BATCH = 5000

DDL = [
"""CREATE TABLE IF NOT EXISTS trade_stock_master (
 stock_code VARCHAR(20) PRIMARY KEY, stock_name VARCHAR(100), industry VARCHAR(100),
 list_date DATE, exchange VARCHAR(10), data_source VARCHAR(20) NOT NULL,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS trade_stock_daily_basic (
 stock_code VARCHAR(20) NOT NULL, trade_date DATE NOT NULL, turnover_rate DECIMAL(12,6),
 float_mv DECIMAL(24,4) COMMENT '万元', total_mv DECIMAL(24,4) COMMENT '万元',
 pe DECIMAL(20,6), pb DECIMAL(20,6), is_limit_up TINYINT, is_limit_down TINYINT,
 data_source VARCHAR(20) NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(stock_code, trade_date), KEY idx_daily_basic_date(trade_date)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS trade_stock_adj_factor (
 stock_code VARCHAR(20) NOT NULL, trade_date DATE NOT NULL, adj_factor DECIMAL(24,8) NOT NULL,
 data_source VARCHAR(20) NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(stock_code, trade_date)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
"""CREATE TABLE IF NOT EXISTS trade_market_calendar (
 exchange VARCHAR(10) NOT NULL, cal_date DATE NOT NULL, is_open TINYINT NOT NULL,
 pretrade_date DATE, data_source VARCHAR(20) NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(exchange, cal_date)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

def date8(value):
    value = str(value or '').replace('.0', '').strip()
    if len(value) != 8 or not value.isdigit(): return None
    try: return datetime.strptime(value, '%Y%m%d').date()
    except ValueError: return None

def num(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError): return None

def flag(value):
    return 1 if str(value).strip().lower() in ('1', 'true', 'yes') else 0

def valid_code(code):
    return isinstance(code, str) and code.endswith(('.SH', '.SZ')) and len(code) == 9

def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        yield from csv.DictReader(file)

def write_batches(connection, sql, records):
    cursor = connection.cursor(); count = 0; batch = []
    for record in records:
        batch.append(record)
        if len(batch) >= BATCH:
            cursor.executemany(sql, batch); connection.commit(); count += len(batch); batch.clear()
    if batch:
        cursor.executemany(sql, batch); connection.commit(); count += len(batch)
    cursor.close(); return count

def setup(connection):
    cursor = connection.cursor()
    for sql in DDL: cursor.execute(sql)
    connection.commit(); cursor.close()

def import_master(connection):
    path = ROOT/'01_股票基础清单/沪深A股正常上市清单.csv'
    def clean():
        for row in rows(path):
            code = row['ts_code'].strip()
            listed = date8(row.get('list_date'))
            if valid_code(code) and listed:
                yield (code, row.get('name','').strip()[:100], row.get('industry','').strip()[:100], listed, row.get('exchange','').strip(), 'tushare')
    return write_batches(connection, """INSERT INTO trade_stock_master
      (stock_code,stock_name,industry,list_date,exchange,data_source) VALUES (%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE stock_name=VALUES(stock_name),industry=VALUES(industry),list_date=VALUES(list_date),exchange=VALUES(exchange),data_source=VALUES(data_source)""", clean())

def import_daily(connection):
    files = list((ROOT/'02_前复权日线行情').glob('*日线/*.csv'))
    def clean():
        for path in files:
            for row in rows(path):
                code, day = row.get('ts_code','').strip(), date8(row.get('trade_date'))
                o,h,l,c = (num(row.get(k)) for k in ('open_qfq','high_qfq','low_qfq','close_qfq'))
                vol, amount = num(row.get('vol')), num(row.get('amount'))
                if not (valid_code(code) and day and None not in (o,h,l,c,vol,amount) and 0 < l <= min(o,c) <= max(o,c) <= h and vol >= 0 and amount >= 0): continue
                # Tushare daily 的 vol 单位为手、amount 单位为千元；入库统一为股、元。
                yield (code, day, o,h,l,c, round(vol*100), round(amount*1000,2), None)
    return write_batches(connection, """INSERT INTO trade_stock_daily
      (stock_code,trade_date,open_price,high_price,low_price,close_price,volume,amount,turnover_rate)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE open_price=VALUES(open_price),high_price=VALUES(high_price),low_price=VALUES(low_price),close_price=VALUES(close_price),volume=VALUES(volume),amount=VALUES(amount)""", clean())

def import_daily_basic(connection):
    files = sorted((ROOT/'04_辅助回测指标').glob('daily_basic_*.csv'))
    def clean():
        for path in files:
            for row in rows(path):
                code, day = row.get('ts_code','').strip(), date8(row.get('trade_date'))
                if valid_code(code) and day:
                    yield (code,day,num(row.get('turnover_rate')),num(row.get('float_mv')),num(row.get('total_mv')),num(row.get('pe')),num(row.get('pb')),flag(row.get('is_limit_up')),flag(row.get('is_limit_down')),'tushare')
    return write_batches(connection, """INSERT INTO trade_stock_daily_basic
      (stock_code,trade_date,turnover_rate,float_mv,total_mv,pe,pb,is_limit_up,is_limit_down,data_source)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE turnover_rate=VALUES(turnover_rate),float_mv=VALUES(float_mv),total_mv=VALUES(total_mv),pe=VALUES(pe),pb=VALUES(pb),is_limit_up=VALUES(is_limit_up),is_limit_down=VALUES(is_limit_down),data_source=VALUES(data_source)""", clean())

def import_factors(connection):
    files = sorted((ROOT/'04_辅助回测指标').glob('adj_factor_*.csv'))
    def clean():
        for path in files:
            for row in rows(path):
                code, day, factor = row.get('ts_code','').strip(), date8(row.get('trade_date')), num(row.get('adj_factor'))
                if valid_code(code) and day and factor and factor > 0: yield (code,day,factor,'tushare')
    return write_batches(connection, """INSERT INTO trade_stock_adj_factor (stock_code,trade_date,adj_factor,data_source)
      VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE adj_factor=VALUES(adj_factor),data_source=VALUES(data_source)""", clean())

def import_calendar(connection):
    path = next((ROOT/'04_辅助回测指标').glob('trade_cal_*.csv'))
    def clean():
        for row in rows(path):
            day = date8(row.get('cal_date')); prev = date8(row.get('pretrade_date'))
            if day: yield (row.get('exchange','').strip(), day, flag(row.get('is_open')), prev, 'tushare')
    return write_batches(connection, """INSERT INTO trade_market_calendar (exchange,cal_date,is_open,pretrade_date,data_source)
      VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE is_open=VALUES(is_open),pretrade_date=VALUES(pretrade_date),data_source=VALUES(data_source)""", clean())

def import_indicators(connection):
    path = ROOT/'03_年报财务数据/年报_2025/fina_indicator_筛选1.csv'
    def clean():
        for row in rows(path):
            code, day = row.get('ts_code','').strip(), date8(row.get('end_date'))
            if valid_code(code) and day:
                yield (code,day,num(row.get('roe')),num(row.get('grossprofit_margin')),num(row.get('debt_to_assets')),'tushare')
    return write_batches(connection, """INSERT INTO trade_stock_financial (stock_code,report_date,roe,gross_margin,debt_ratio,data_source)
      VALUES (%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE roe=COALESCE(VALUES(roe),roe),gross_margin=COALESCE(VALUES(gross_margin),gross_margin),debt_ratio=COALESCE(VALUES(debt_ratio),debt_ratio),data_source=VALUES(data_source)""", clean())

def main():
    connection = get_connection()
    try:
        setup(connection)
        jobs = [('股票主数据',import_master),('前复权日线',import_daily),('每日估值与流动性',import_daily_basic),('复权因子',import_factors),('交易日历',import_calendar),('年报指标',import_indicators)]
        for name, job in jobs: print(f'{name}: 写入 {job(connection):,} 条')
    finally: connection.close()

if __name__ == '__main__': main()
