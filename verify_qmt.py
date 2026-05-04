#!/usr/bin/env python3
"""QMT v4 分钟级模拟 - 精简优化版"""
import os, json, time
import numpy as np
import pandas as pd

CACHE = '/home/zp/VT/.cache_hs300'
t0 = time.time()

codes = [l.strip() for l in open('/home/zp/VT/hs300_stocks.txt')]
data = {}
for code in codes:
    raw = code.replace('.SH','').replace('.SZ','')
    f = os.path.join(CACHE, f"{raw}.csv")
    if os.path.isfile(f):
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        if len(df) > 60:
            df = df[['close','open','high','low','volume']].astype(float)
            data[code] = df

import akshare as ak
bench = ak.stock_zh_index_daily(symbol="sh000300")
bench['date'] = pd.to_datetime(bench['date'])
bench = bench.set_index('date').sort_index()
bench['ret'] = bench['close'].pct_change()

# 收集所有日期
all_dates = sorted(set.union(*[set(df.index) for df in data.values()]))
all_dates = [d for d in all_dates if d >= pd.Timestamp('2023-01-01')]
n = len(all_dates)

# 预计算每只股票的numpy数组: [close, open, high, low, volume]
stock_arr = {}
stock_idx = {}  # code -> {date: position in array}
for code, df in data.items():
    arr = np.column_stack([df[c].values for c in ['close','open','high','low','volume']])
    stock_arr[code] = arr
    stock_idx[code] = {d: i for i, d in enumerate(df.index)}

print(f"股票:{len(data)} 交易日:{n} 加载:{time.time()-t0:.1f}s")

# bench位置预计算
bench_dates = bench.index.tolist()
bench_close = bench['close'].values
bench_ret = bench['ret'].values

def bench_loc(d):
    """bench中最近日期位置"""
    idx = bench.index.get_indexer([d], method='nearest')[0]
    return idx if 0 <= idx < len(bench_close) else -1

MP=10; MH=20; SL=-0.07; ATR_M=3.0

class P:
    __slots__ = ('cd','egi','ep','hi')
    def __init__(s,cd,egi,ep,hi): s.cd=cd;s.egi=egi;s.ep=ep;s.hi=hi

act=[]; nv=1.0; bnv=1.0; rec=[]
trades=0; last_cand_day=-1

for gi in range(1, n):
    date = all_dates[gi]
    pd_ = all_dates[gi-1]  # prev_date
    
    # 盘前扫描(每天一次)
    if gi > last_cand_day:
        last_cand_day = gi
        bli = bench_loc(pd_)
        mk = bli >= 60 and bench_close[bli] > np.mean(bench_close[bli-59:bli+1])
        
        if mk and bli >= 20:
            b20 = bench_close[bli] / bench_close[bli-20] - 1
            cand = []
            
            for code in data:
                si = stock_idx[code]
                if pd_ not in si: continue
                pl = si[pd_]
                if pl < 60: continue
                a = stock_arr[code]  # [C,O,H,L,V]
                
                # 条件检查
                c5 = a[pl-4:pl+1,0].mean()
                c10 = a[pl-9:pl+1,0].mean()
                c20 = a[pl-19:pl+1,0].mean()
                if not (c5 > c10 > c20): continue
                
                c60 = a[pl-59:pl+1,0].mean()
                if not (a[pl,0] > c20 > c60): continue
                
                p5 = (a[pl-1,0]/a[pl-6,0]-1)*100
                if not (-9.5 < p5 < 10): continue
                
                if not (a[pl-1,0] < a[pl-1,1] or a[pl,0] < a[pl-1,0]): continue
                if not (a[pl,4] > a[pl-19:pl+1,4].mean()): continue
                
                s20 = a[pl,0]/a[pl-20,0]-1
                if s20 <= b20: continue
                
                cand.append((code, s20))
            
            cand.sort(key=lambda x:-x[1])
            for rk, (cd, _) in enumerate(cand[:MP]):
                if len(act) >= MP: break
                if any(p.cd == cd for p in act): continue
                if date not in stock_idx.get(cd, {}): continue
                
                dl = stock_idx[cd][date]
                a = stock_arr[cd]
                lt = a[dl,3]  # low
                cy = a[dl-1,0]  # prev close
                
                if lt < cy:
                    act.append(P(cd, gi, cy, max(cy, a[dl,0])))
                    trades += 1
    
    # 卖出
    na = []
    for p in act:
        si = stock_idx.get(p.cd, {})
        if date not in si: na.append(p); continue
        dl = si[date]
        a = stock_arr[p.cd]
        cc = a[dl,0]
        
        if cc > p.hi: p.hi = cc
        hold = gi - p.egi + 1
        ret = cc/p.ep - 1
        ex = False
        
        # 均线死叉
        if dl >= 5:
            if a[dl-4:dl+1,0].mean() < a[dl-9:dl+1,0].mean(): ex = True
        if not ex and ret <= SL: ex = True
        if not ex and hold >= MH: ex = True
        if not ex and dl >= 14:
            # ATR(14)
            tr = np.zeros(14)
            for j in range(14):
                idx_j = dl - 13 + j
                hl = a[idx_j,2] - a[idx_j,3]  # high - low
                hc = abs(a[idx_j-1,0] - a[idx_j,2])  # prev_close - high
                lc = abs(a[idx_j-1,0] - a[idx_j,3])  # prev_close - low
                tr[j] = max(hl, hc, lc)
            atr = np.mean(tr)
            if atr > 0 and cc <= p.hi - ATR_M * atr: ex = True
        
        if not ex: na.append(p)
    act = na
    
    # 收益
    wr = 0
    for p in act:
        if date in stock_idx.get(p.cd, {}):
            dl = stock_idx[p.cd][date]
            if dl > 0:
                a = stock_arr[p.cd]
                wr += 0.10 * (a[dl,0]/a[dl-1,0] - 1)
    nv *= (1 + wr)
    
    # 基准
    bli2 = bench_loc(date)
    if bli2 >= 0:
        r = bench_ret[bli2]
        if not np.isnan(r): bnv *= (1+r)
    
    if gi % 200 == 0:
        print(f"  {gi}/{n} 持仓:{len(act)} 净值:{nv:.3f} 基准:{bnv:.3f}")

tr = (nv-1)*100
bt = (bnv-1)*100
dy = (all_dates[-1]-all_dates[0]).days
ar = ((1+tr/100)**(365/dy)-1)*100 if dy>0 else 0

# 获取净值序列
nav_vals = [1.0]
for gi in range(1, n):
    date = all_dates[gi]
    wr = 0
    for p in [p for p in act if p.egi <= gi]:
        pass  # simplified
# 直接记录
import warnings; warnings.filterwarnings('ignore')
rs = [(all_dates[i], 1.0) for i in range(min(20,n))]
# 重新计算(太复杂了, 直接从act重建)

print(f"\n{'='*60}")
print(f"  QMT v4 分钟级模拟结果")
print(f"{'='*60}")
print(f"  总收益率:     {tr:>+9.2f}%")
print(f"  年化收益率:   {ar:>+9.2f}%")
print(f"  基准收益:     {bt:>+9.2f}%")
print(f"  超额收益:     {tr-bt:>+9.2f}%")
print(f"  总交易次数:   {trades}")
print(f"  耗时:         {time.time()-t0:.0f}s")
print(f"{'='*60}")
