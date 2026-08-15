# -*- coding: utf-8 -*-
"""
沪深300日线 + RSI 指标计算与绘图
使用 tushare 获取沪深300指数日线数据，计算 RSI(14) 并绘图

注意：需要安装 tushare、pandas、matplotlib，并配置 TUSHARE_TOKEN 环境变量
"""
import os
import pandas as pd
import tushare as ts
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 中文字体（macOS）
plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 参数配置
INDEX_CODE = '000300.SH'  # 沪深300
INDEX_NAME = '沪深300'
DATA_START = '20240101'
DATA_END = '20251231'
RSI_PERIOD = 14


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑法计算 RSI"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def fetch_hs300():
    """下载沪深300日线数据"""
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        raise RuntimeError('未找到环境变量 TUSHARE_TOKEN，请先设置：export TUSHARE_TOKEN=your_token')

    ts.set_token(token)
    pro = ts.pro_api()

    df = pro.index_daily(
        ts_code=INDEX_CODE,
        start_date=DATA_START,
        end_date=DATA_END,
    )
    if df is None or df.empty:
        raise RuntimeError('无法获取沪深300历史数据')

    df = df.rename(columns={'trade_date': 'date', 'vol': 'volume'})
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)
    return df


def plot_price_rsi(df: pd.DataFrame, save_path=None):
    """绘制收盘价 + RSI 双图"""
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True,
        gridspec_kw={'height_ratios': [2, 1]},
    )

    # 上图：收盘价
    ax1.plot(df['date'], df['close'], color='#1f77b4', linewidth=1.2, label='收盘价')
    ax1.set_ylabel('点位')
    ax1.set_title(f'{INDEX_NAME}({INDEX_CODE}) 日线与 RSI({RSI_PERIOD})')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # 下图：RSI
    ax2.plot(df['date'], df['rsi'], color='#d62728', linewidth=1.2, label=f'RSI({RSI_PERIOD})')
    ax2.axhline(70, color='gray', linestyle='--', linewidth=0.8, label='超买 70')
    ax2.axhline(30, color='gray', linestyle=':', linewidth=0.8, label='超卖 30')
    ax2.fill_between(df['date'], 70, 100, color='red', alpha=0.08)
    ax2.fill_between(df['date'], 0, 30, color='green', alpha=0.08)
    ax2.set_ylabel('RSI')
    ax2.set_xlabel('日期')
    ax2.set_ylim(0, 100)
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    fig.autofmt_xdate()
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f'图表已保存：{save_path}')

    plt.show()


def main():
    print(f'下载 {INDEX_NAME}({INDEX_CODE}) 日线：{DATA_START} ~ {DATA_END}')
    df = fetch_hs300()
    print(f'共 {len(df)} 条，区间 {df["date"].iloc[0].date()} ~ {df["date"].iloc[-1].date()}')

    df['rsi'] = calc_rsi(df['close'], RSI_PERIOD)

    # 保存数据
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, '000300_SH_daily_rsi.csv')
    df[['date', 'open', 'high', 'low', 'close', 'volume', 'rsi']].to_csv(
        csv_path, index=False, encoding='utf-8-sig'
    )
    print(f'数据已保存：{csv_path}')
    print('\n最近5日：')
    print(df[['date', 'close', 'rsi']].tail().to_string(index=False))

    img_path = os.path.join(out_dir, '000300_SH_rsi.png')
    plot_price_rsi(df, save_path=img_path)


if __name__ == '__main__':
    main()
