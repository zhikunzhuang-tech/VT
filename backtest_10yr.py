#!/usr/bin/env python3
"""QMT v4 十年回测 (2016-2026) + 动态仓位"""
import os, time, numpy as np, pandas as pd
import akshare as ak

t0 = time.time()
CACHE = '/home/zp/VT/.cache_hs300'
codes = [l.strip() for l in open('/home/zp/VT/hs300_stocks.txt')]

data = {}
for code in codes:
    raw = code.replace('.SH','').replace('.SZ','')
    f = os.path.join(CACHE, f'{raw}.csv')
    if os.path.isfile(f):
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        if len(df) > 1500:
            data[code] = df[['close','open','high','low','volume']].astype(float)

bench = ak.stock_zh_index_daily(symbol='sh000300')
bench['date'] = pd.to_datetime(bench['date'])
bench = bench.set_index('date').sort_index()
bench['ret'] = bench['close'].pct_change()

all_dates = sorted(set.union(*[set(df.index) for df in data.values()]))
all_dates = [d for d in all_dates if d >= pd.Timestamp('2016-01-01') and d <= pd.Timestamp('2026-04-30')]
print(f'股票:{len(data)} 交易日:{len(all_dates)} 加载:{time.time()-t0:.1f}s')

# Pre-compute numpy arrays
sa, si = {}, {}
for code, df in data.items():
    a = np.column_stack([df[c].values for c in ['close','open','high','low','volume']])
    sa[code] = a
    si[code] = {d: i for i, d in enumerate(df.index)}

bench_a = bench['close'].values
bench_i = {d: i for i, d in enumerate(bench.index)}
bench_r = bench['ret'].values

# Pre-compute bench MA60 and MA120 for each day
num_days = len(all_dates)
b_ma60 = np.full(num_days, np.nan)
b_ma120 = np.full(num_days, np.nan)
for gi in range(num_days):
    d = all_dates[gi]
    bi = bench_i.get(d, -1)
    if bi >= 59: b_ma60[gi] = np.mean(bench_a[bi-59:bi+1])
    if bi >= 119: b_ma120[gi] = np.mean(bench_a[bi-119:bi+1])

def get_max_pos(gi):
    """动态仓位: 根据沪深300位置决定最大持仓"""
    if gi < 60 or np.isnan(b_ma60[gi]): return 10
    bi = bench_i.get(all_dates[gi], -1)
    if bi < 0: return 10
    bc = bench_a[bi]
    b60 = b_ma60[gi]
    b120 = b_ma120[gi]
    if bc > b60: return 10       # 牛市: 满仓
    if np.isnan(b120) or bc > b120: return 6   # 震荡: 半仓
    return 3  # 熊市: 轻仓

# Parameters
SL = -0.07
ATR_M = 3.0
MH = 20

act = []  # (code, entry_gi, entry_price, highest)
nv = 1.0
bnv = 1.0
trades = 0
nav_vals = np.ones(num_days)
bnav_vals = np.ones(num_days)
pos_count = np.zeros(num_days)

for gi in range(1, num_days):
    date = all_dates[gi]
    pd_ = all_dates[gi-1]
    mp = get_max_pos(gi)

    # === Daily scan ===
    bli = bench_i.get(pd_, -1)
    market_ok = bli >= 60 and bench_a[bli] > np.mean(bench_a[bli-59:bli+1])

    if market_ok and bli >= 20:
        b20 = bench_a[bli] / bench_a[bli-20] - 1
        cand = []
        for code in data:
            sil = si[code]
            if pd_ not in sil: continue
            pl = sil[pd_]
            a = sa[code]
            if pl < 60: continue

            if not (a[pl-4:pl+1,0].mean() > a[pl-9:pl+1,0].mean() > a[pl-19:pl+1,0].mean()): continue
            c20 = a[pl-19:pl+1,0].mean()
            c60 = a[pl-59:pl+1,0].mean()
            if not (a[pl,0] > c20 > c60): continue
            if not (-9.5 < (a[pl-1,0]/a[pl-6,0]-1)*100 < 10): continue
            if not (a[pl-1,0] < a[pl-1,1] or a[pl,0] < a[pl-1,0]): continue
            if not (a[pl,4] > a[pl-19:pl+1,4].mean()): continue
            s20 = a[pl,0] / a[pl-20,0] - 1
            if s20 <= b20: continue
            cand.append((code, s20))

        cand.sort(key=lambda x: -x[1])
        for rk, (cd, _) in enumerate(cand[:mp]):
            if len(act) >= mp: break
            if any(p[0] == cd for p in act): continue
            if date not in si.get(cd, {}): continue
            dl = si[cd][date]
            a = sa[cd]
            if a[dl, 3] < a[dl-1, 0]:  # Low < prev close
                act.append((cd, gi, a[dl-1, 0], max(a[dl-1, 0], a[dl, 0])))
                trades += 1

    # === Exit ===
    na = []
    for cd, egi, ep, hi in act:
        if date not in si.get(cd, {}):
            na.append((cd, egi, ep, hi))
            continue
        dl = si[cd][date]
        a = sa[cd]
        cc = a[dl, 0]
        if cc > hi: hi = cc
        hold = gi - egi + 1
        ret = cc / ep - 1
        ex = False
        # 均线死叉
        if dl >= 5 and a[dl-4:dl+1,0].mean() < a[dl-9:dl+1,0].mean():
            ex = True
        if not ex and ret <= SL: ex = True
        if not ex and hold >= MH: ex = True
        if not ex and dl >= 14:
            hl = a[dl-13:dl+1,2] - a[dl-13:dl+1,3]
            hc = np.abs(a[dl-14:dl,0] - a[dl-13:dl+1,2])
            lc = np.abs(a[dl-14:dl,0] - a[dl-13:dl+1,3])
            tr = np.maximum(np.maximum(hl, hc), lc)
            atr = np.mean(tr)
            if atr > 0 and cc <= hi - ATR_M * atr: ex = True
        if not ex: na.append((cd, egi, ep, hi))
    act = na

    # === P&L ===
    wr = 0
    for cd, egi, ep, hi in act:
        if date in si.get(cd, {}):
            dl = si[cd][date]
            if dl > 0:
                wr += 0.10 * (sa[cd][dl,0] / sa[cd][dl-1,0] - 1)
    nv *= (1 + wr)

    bi2 = bench_i.get(date, -1)
    if bi2 >= 0 and not np.isnan(bench_r[bi2]):
        bnv *= (1 + bench_r[bi2])

    nav_vals[gi] = nv
    bnav_vals[gi] = bnv
    pos_count[gi] = len(act)

    if gi % 500 == 0:
        print(f'  {gi}/{num_days} pos:{len(act)} mp:{mp} nav:{nv:.2f}')

# === Stats ===
tr = (nv - 1) * 100
bt = (bnv - 1) * 100
dy = (all_dates[-1] - all_dates[0]).days
ar = ((1 + tr/100) ** (365/dy) - 1) * 100

peak = np.maximum.accumulate(nav_vals)
dd = (nav_vals - peak) / peak * 100
mdd = np.min(dd)

dr = np.diff(nav_vals[1:]) / nav_vals[1:-1]
sharpe = float(np.sqrt(252) * np.mean(dr) / np.std(dr)) if np.std(dr) > 0 else 0
calmar = ar / abs(mdd) if mdd != 0 else 0
avg_pos = np.mean(pos_count[60:])

sep = '=' * 60
print(f'\n{sep}')
print('  QMT v4 十年回测 (2016-2026) + 动态仓位管理')
print(sep)
print(f'  总收益率:       {tr:>+9.2f}%')
print(f'  年化收益率:     {ar:>+9.2f}%')
print(f'  基准收益:       {bt:>+9.2f}%')
print(f'  超额收益:       {tr-bt:>+9.2f}%')
print(f'  最大回撤:       {mdd:>9.2f}%')
print(f'  夏普比率:       {sharpe:>9.2f}')
print(f'  卡玛比率:       {calmar:>9.2f}')
print(f'  总交易次数:     {trades}')
print(f'  日均持仓:       {avg_pos:>9.1f}')
print(f'  回测天数:       {dy}')
print(f'  耗时:           {time.time()-t0:.0f}s')
print(sep)

# Save results
results = {
    'total_return': round(tr,2), 'annual_return': round(ar,2),
    'bench_return': round(bt,2), 'excess_return': round(tr-bt,2),
    'max_drawdown': round(mdd,2), 'sharpe_ratio': round(sharpe,2),
    'calmar_ratio': round(calmar,2), 'total_trades': trades,
    'avg_positions': round(avg_pos,1), 'days': dy
}
with open('/home/zp/VT/backtest_10yr.json', 'w') as f:
    __import__('json').dump(results, f, ensure_ascii=False, indent=2)
pd.DataFrame({'nav': nav_vals, 'bench': bnav_vals, 'pos': pos_count}, index=all_dates).to_csv('/home/zp/VT/backtest_10yr_nav.csv')
print(f'\n结果: /home/zp/VT/backtest_10yr.json')
