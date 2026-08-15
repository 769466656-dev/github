#!/usr/bin/env python3
"""下载“筛选1”所需的沪深 A 股 2026 年报财务指标。

使用前：
    export TUSHARE_TOKEN='你的 Tushare Token'
    python3 多因子选股-下载Tushare财务指标.py

脚本逐股请求 Tushare 的 fina_indicator 接口。每只股票会先缓存到本地，
网络中断后直接运行相同命令即可续传；Token 不会写进任何文件。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import tushare as ts


PERIOD = "20260807"
ENCODING = "utf-8-sig"
FIELDS = [
    "ts_code", "ann_date", "end_date", "update_flag", "roe",
    "netprofit_yoy", "grossprofit_margin", "debt_to_assets", "ocf_to_or",
]
DEFAULT_OUTPUT = Path(
    "/Volumes/拍摄02/沪深A股_Tushare/03_年报财务数据/年报_2026/fina_indicator_筛选1.csv"
)
DEFAULT_UNIVERSE = Path("/Volumes/拍摄02/沪深A股_Tushare/01_股票基础清单/沪深A股正常上市清单.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="汇总 CSV 输出路径")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE, help="本地沪深 A 股清单 CSV 路径")
    parser.add_argument("--sleep", type=float, default=0.4, help="每次 API 请求后的间隔秒数")
    parser.add_argument("--timeout", type=int, default=20, help="单次 HTTP 请求超时秒数")
    parser.add_argument("--retries", type=int, default=4, help="单只股票最多请求次数")
    parser.add_argument("--limit", type=int, help="仅下载前 N 只股票，用于测试")
    parser.add_argument("--refresh", action="store_true", help="重新请求并覆盖已完成股票的本地缓存")
    return parser.parse_args()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.reindex(columns=FIELDS).to_csv(temporary, index=False, encoding=ENCODING)
    temporary.replace(path)


def write_json(value: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def is_a_share(code: str) -> bool:
    number, exchange = code.split(".")
    return (
        (exchange == "SH" and number.startswith(("600", "601", "603", "605", "688")))
        or (exchange == "SZ" and number.startswith(("000", "001", "002", "003", "300", "301")))
    )


def latest_annual(frame: pd.DataFrame) -> pd.DataFrame:
    """保留同一股票最新披露/修订的 2026 年报记录。"""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FIELDS)
    result = frame.reindex(columns=FIELDS).copy()
    for column in ("ann_date", "end_date"):
        result[column] = result[column].astype("string").str.replace(".0", "", regex=False).str.zfill(8)
    result = result.loc[result["end_date"].eq(PERIOD)].copy()
    if result.empty:
        return pd.DataFrame(columns=FIELDS)
    result["_update"] = pd.to_numeric(result["update_flag"], errors="coerce").fillna(0)
    result = result.sort_values(["ts_code", "ann_date", "_update"], kind="stable")
    return result.drop_duplicates("ts_code", keep="last").drop(columns="_update")


def fetch_one(pro: object, code: str, retries: int, sleep_seconds: float) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            frame = pro.fina_indicator(ts_code=code, period=PERIOD, fields=",".join(FIELDS))
            time.sleep(sleep_seconds)
            return latest_annual(frame)
        except Exception as error:
            last_error = error
            if attempt + 1 < retries:
                time.sleep((2 ** attempt) + random.uniform(0, 0.3))
    raise RuntimeError(str(last_error)) from last_error


def main() -> int:
    args = parse_args()
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("未设置 TUSHARE_TOKEN。先执行：export TUSHARE_TOKEN='你的 Token'")

    cache_dir = args.output.parent / "筛选1_fina_indicator_逐股"
    progress_path = args.output.parent / "筛选1_下载进度.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {"completed": [], "failures": []}
    completed = set(progress.get("completed", []))

    if not args.universe.exists():
        raise SystemExit(f"未找到本地股票清单：{args.universe}")
    universe = pd.read_csv(args.universe, dtype="string", encoding=ENCODING)
    if "ts_code" not in universe.columns:
        raise SystemExit(f"股票清单缺少 ts_code 字段：{args.universe}")
    codes = sorted(code for code in universe["ts_code"].dropna().tolist() if is_a_share(code))
    if args.limit:
        codes = codes[:args.limit]
    print(f"股票池：沪深正常上市 A 股 {len(codes)} 只；目标报告期：{PERIOD}")
    pro = ts.pro_api(token, timeout=args.timeout)

    for index, code in enumerate(codes, start=1):
        cache_path = cache_dir / f"{code}.csv"
        if not args.refresh and code in completed and cache_path.exists():
            continue
        try:
            write_csv(fetch_one(pro, code, args.retries, args.sleep), cache_path)
            completed.add(code)
            progress["completed"] = sorted(completed)
            write_json(progress, progress_path)
        except Exception as error:
            progress.setdefault("failures", []).append(
                {"at": datetime.now().isoformat(timespec="seconds"), "ts_code": code, "error": str(error)}
            )
            write_json(progress, progress_path)
            print(f"失败 {code}: {error}")
        if index % 100 == 0 or index == len(codes):
            print(f"进度：{index}/{len(codes)}；已完成 {len(completed)}", flush=True)

    reports = [pd.read_csv(path, dtype="string", encoding=ENCODING) for path in sorted(cache_dir.glob("*.csv"))]
    financials = pd.concat(reports, ignore_index=True) if reports else pd.DataFrame(columns=FIELDS)
    write_csv(financials, args.output)
    print(f"\n已写入 {len(financials)} 条年报指标：{args.output}")
    if len(completed) < len(codes):
        print(f"尚有 {len(codes) - len(completed)} 只未完成；网络恢复后用同一命令重跑即可续传。")
        return 1
    print("全部下载完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
