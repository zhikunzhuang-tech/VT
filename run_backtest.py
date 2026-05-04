#!/usr/bin/env python3
"""
回测执行器 v4 - 含市场择时和相对强度
"""
import os, sys, json, time
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/zp/vibe-env/lib/python3.11/site-packages/runs/20260503_131014_47_23a552/code')
from signal_engine import SignalEngine

CACHE_DIR = '/home/zp/VT/.cache_hs300'

print("加载数据...")
codes_file = '/home/zp/VT/hs300_stocks.txt'
with open(codes_file) as f:
    codes = [line.strip() for line in f if line.strip()]

data_map = {}
for code in codes:
    raw_code = code.replace('.SH', '').replace('.SZ', '')
    cache_file = os.path.join(CACHE_DIR, f"{raw_code}.csv")
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        if len(df) > 60:
            data_map[code] = df

# 加载沪深300基准数据
import akshare as ak
bench = ak.stock_zh_index_daily(symbol="sh000300")
bench['date'] = pd.to_datetime(bench['date'])
bench = bench.set_index('date').sort_index()
bench = bench.rename(columns={'open': 'open', 'close': 'close', 'high': 'high', 'low': 'low', 'volume': 'volume'})
bench['bench_ret'] = bench['close'].pct_change()

# 传入信号引擎
data_map['__benchmark__'] = bench[['open', 'close', 'high', 'low', 'volume']]

print(f"个股数: {len(data_map)-1}, 基准天数: {len(bench)}")

print("生成信号...")
t0 = time.time()
engine = SignalEngine()
signals = engine.generate(data_map)
print(f"信号生成: {time.time()-t0:.1f}s")

print("计算收益...")
dates = sorted(set.union(*[set(df.index) for df in data_map.values() if isinstance(df, pd.DataFrame) and len(df.columns) > 3]))
dates = [d for d in dates if d >= pd.Timestamp('2023-01-01')]

pv = 1.0
bv = 1.0
records = []

for i, date in enumerate(dates):
    if i % 200 == 0:
        print(f"  进度: {i}/{len(dates)}")
    
    tw = 0
    wr = 0
    ac = 0
    
    for code in signals:
        sig = signals[code]
        if date in sig.index:
            w = float(sig.loc[date])
            if w > 0:
                ac += 1
                df = data_map[code]
                if date in df.index:
                    pos = df.index.get_loc(date)
                    if pos > 0:
                        ret = df.iloc[pos]['close'] / df.iloc[pos-1]['close'] - 1
                        wr += w * ret
                        tw += w
    
    if tw > 0:
        pv *= (1 + wr)
    
    if date in bench.index:
        br = float(bench.loc[date, 'bench_ret'])
        if not np.isnan(br):
            bv *= (1 + br)
    
    records.append({'date': date, 'nav': pv, 'bench': bv})

nav_df = pd.DataFrame(records).set_index('date')

tr = (nav_df['nav'].iloc[-1] / nav_df['nav'].iloc[0] - 1) * 100
bt = (nav_df['bench'].iloc[-1] / nav_df['bench'].iloc[0] - 1) * 100
days = (nav_df.index[-1] - nav_df.index[0]).days
ar = ((1 + tr/100) ** (365/days) - 1) * 100

cummax = nav_df['nav'].expanding().max()
dd = (nav_df['nav'] - cummax) / cummax
mdd = dd.min() * 100

dr = nav_df['nav'].pct_change().dropna()
sharpe = np.sqrt(252) * dr.mean() / dr.std() if dr.std() > 0 else 0
calmar = ar / abs(mdd) if mdd != 0 else 0
wr_pct = (dr > 0).sum() / len(dr) * 100

print("\n" + "=" * 65)
print("  策略回测结果 v4 (沪深300 | 2023-2026)")
print("=" * 65)
print(f"  总收益率:       {tr:>+9.2f}%")
print(f"  年化收益率:     {ar:>+9.2f}%")
print(f"  基准收益:       {bt:>+9.2f}%")
print(f"  超额收益:       {tr-bt:>+9.2f}%")
print(f"  最大回撤:       {mdd:>9.2f}%")
print(f"  夏普比率:       {sharpe:>9.2f}")
print(f"  卡玛比率:       {calmar:>9.2f}")
print(f"  胜率(日):       {wr_pct:>9.2f}%")
print("=" * 65)

result = {
    'total_return': round(tr, 2), 'annual_return': round(ar, 2),
    'bench_return': round(bt, 2), 'excess_return': round(tr-bt, 2),
    'max_drawdown': round(mdd, 2), 'sharpe_ratio': round(sharpe, 2),
    'calmar_ratio': round(calmar, 2), 'win_rate': round(wr_pct, 2),
    'days': days, 'stocks_used': len(data_map)-1
}
with open('/home/zp/VT/backtest_result.json', 'w') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
nav_df.to_csv('/home/zp/VT/backtest_nav.csv')
print(f"\n结果: /home/zp/VT/backtest_result.json")
