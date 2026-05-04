#!/usr/bin/env python3
"""QMT v6最终优化版 Backtest - 10年回测
均线多头精选+ATR移动止盈
"""
import numpy as np
import pandas as pd
import os, sys
from datetime import datetime, timedelta

# ===== 策略参数 =====
MAX_POS = 10
MAX_DAYS = 20
STOP_LOSS = 0.95
ATR_MULT = 1.8

def calc_all(c, h, l, v, o):
    """计算策略所需全部指标"""
    c_arr = np.array(c, dtype=float)
    h_arr = np.array(h, dtype=float)
    l_arr = np.array(l, dtype=float)
    v_arr = np.array(v, dtype=float)
    o_arr = np.array(o, dtype=float)

    # ---- 昨日数据（作为条件判断基准） ----
    y_close = c_arr[-2]    # 前日收盘
    y_open  = o_arr[-2]    # 前日开盘
    y_high  = h_arr[-2]
    y_low   = l_arr[-2]
    
    # ---- 今日数据（用于确认入场触发） ----
    t_low   = l_arr[-1]    # 今日最低
    t_close = c_arr[-1]

    y_ma5  = np.mean(c_arr[-7:-2])   # 昨日的MA5
    y_ma10 = np.mean(c_arr[-12:-2])  # 昨日的MA10
    y_ma20 = np.mean(c_arr[-22:-2])  # 昨日的MA20
    y_ma60 = np.mean(c_arr[-62:-2])  # 昨日的MA60
    y_vol_ma20 = np.mean(v_arr[-22:-2])  # 昨日的20日均量
    y_close_6d = c_arr[-8]  # 6天前的收盘（昨日的视角）

    # 昨日的ATR(14)
    tr_list = []
    for i in range(max(1, len(c_arr)-17), len(c_arr)-1):  # 昨日为止的数据
        tr = max(h_arr[i]-l_arr[i], abs(h_arr[i]-c_arr[i-1]), abs(l_arr[i]-c_arr[i-1]))
        tr_list.append(tr)
    if len(tr_list) < 14:
        return None
    y_atr14 = np.mean(tr_list[-14:])

    # 昨日5日涨跌幅（基于昨日收盘价）
    y_pct_6d = (y_close / y_close_6d - 1) * 100

    # ---- 昨日入场条件（用昨日数据判断） ----
    y_cond1 = y_ma5 > y_ma10 > y_ma20
    y_cond2 = y_close > y_ma20 > y_ma60
    y_cond3 = -9.5 <= y_pct_6d <= 10.0
    y_cond4 = y_close < y_open  # 前日收阴
    y_cond5 = v_arr[-2] > y_vol_ma20  # 昨日成交量 > 均量

    # ---- 今日触发条件：最低价跌破前日收盘 ----
    trigger = t_low < y_close

    # 今日的收盘价（用于卖出）
    y_ret_20d = y_close / c_arr[-22] - 1  # 昨日20日收益

    return {
        'entry_ok': y_cond1 and y_cond2 and y_cond3 and y_cond4 and y_cond5 and trigger and y_ret_20d > 0,
        'entry_price': y_close,  # 以前日收盘价买入
        'ret_20d': y_ret_20d,
        'cur_close': t_close,
        'atr14': y_atr14,
        'c_arr': c_arr,  # 存完整数组供卖出使用
    }

print("=== 获取数据 ===")
import akshare as ak
os.environ['no_proxy'] = '.eastmoney.com,.sina.com.cn,.csindex.com.cn'

cons = ak.index_stock_cons_csindex("000300")
codes_raw = cons['成分券代码'].astype(str).str.zfill(6).tolist()
full_codes = [c+'.SH' if c.startswith(('6','9')) else c+'.SZ' for c in codes_raw]
print(f"成分股: {len(full_codes)}只")

df_idx = ak.stock_zh_index_daily_em(symbol="sh000300")
df_idx = df_idx.rename(columns={'日期': 'date', '收盘': 'close'})
df_idx['date'] = pd.to_datetime(df_idx['date'])
df_idx = df_idx.sort_values('date').reset_index(drop=True)
df_idx = df_idx[df_idx['date'] >= '2015-01-01']
print(f"指数数据: {len(df_idx)}天")

idx_dates = df_idx['date'].values
idx_closes = df_idx['close'].values.astype(float)

test_codes = full_codes[:100]
stock_data = {}

for i, code in enumerate(test_codes):
    try:
        raw = code[:6]
        df = ak.stock_zh_a_hist(symbol=raw, start_date='20140101', end_date='20260503')
        if df is None or len(df) < 200:
            continue
        df = df.rename(columns={'日期':'date','收盘':'close','开盘':'open',
                                '最高':'high','最低':'low','成交量':'volume'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        stock_data[code] = df
    except:
        continue
    if (i+1) % 20 == 0:
        print(f"  {i+1}/{len(test_codes)}...")

print(f"成功获取 {len(stock_data)} 只")

print("\n=== 开始回测 ===")

initial_cap = 1_000_000
cash = initial_cap
positions = {}
nav_history = []
trade_log = []

start_idx = 300
total_days = len(idx_dates)

for di in range(start_idx, total_days):
    date_ts = pd.Timestamp(idx_dates[di])
    date_str = date_ts.strftime('%Y-%m-%d')
    date_dt = date_ts
    idx_close = float(idx_closes[di])

    # 市场择时
    if di < 61:
        continue
    hs300_ma60 = np.mean(idx_closes[di-60:di+1].astype(float))
    in_bull = idx_close > hs300_ma60

    if not in_bull:
        for code in list(positions.keys()):
            pos = positions[code]
            df_s = stock_data.get(code)
            if df_s is None: continue
            row = df_s[df_s['date']==date_dt]
            if len(row)==0: row=df_s[df_s['date']<date_dt].tail(1)
            if len(row)==0: continue
            cur_p = float(row['close'].iloc[0])
            ret = (cur_p/pos['entry_price']-1)*100
            cash += pos['shares']*cur_p
            trade_log.append({'date':date_str,'code':code,'action':'SELL',
                              'price':cur_p,'shares':pos['shares'],
                              'return':f'{ret:.1f}%','reason':'BEAR_MK'})
            del positions[code]
        nav = cash
        nav_history.append({'date':date_str,'nav':nav,'pos':len(positions)})
        continue

    # 计算各股票
    candidates = []
    for code in stock_data:
        df_s = stock_data[code]
        rows = df_s[df_s['date']<=date_dt]
        if len(rows) < 62: continue
        rows = rows.tail(62)

        ind = calc_all(
            rows['close'].values, rows['high'].values,
            rows['low'].values, rows['volume'].values,
            rows['open'].values
        )
        if ind is None or not ind['entry_ok']:
            continue
        candidates.append((code, ind['ret_20d'], ind['entry_price'], ind['atr14'], ind['cur_close']))

    candidates.sort(key=lambda x: x[1], reverse=True)

    # 卖出
    for code in list(positions.keys()):
        pos = positions[code]
        df_s = stock_data.get(code)
        if df_s is None: continue
        row = df_s[df_s['date']==date_dt]
        if len(row)==0: row=df_s[df_s['date']<date_dt].tail(1)
        if len(row)==0: continue
        cur_p = float(row['close'].iloc[0])
        ep = pos['entry_price']
        peak = pos.get('peak', ep)
        entry_d = pos['entry_date']

        if cur_p > peak:
            pos['peak'] = cur_p
            peak = cur_p

        if entry_d == date_str:
            continue

        reason = None

        # MA死叉
        rows_full = df_s[df_s['date']<=date_dt].tail(12)
        if len(rows_full) >= 11:
            ca = rows_full['close'].values.astype(float)
            m5n = np.mean(ca[-6:-1])
            m10n = np.mean(ca[-11:-1])
            m5p = np.mean(ca[-7:-1])
            m10p = np.mean(ca[-12:-1])
            if m5n < m10n and m5p >= m10p:
                reason = "MA_DEATH"

        # 止损
        if reason is None and cur_p/ep <= STOP_LOSS:
            reason = "STOP_LOSS"

        # ATR跟踪止盈
        if reason is None:
            atr_v = 0
            for cd,*_,atr,_tc in candidates:
                if cd==code: atr_v=atr; break
            if atr_v == 0:
                rows_a = df_s[df_s['date']<=date_dt].tail(16)
                if len(rows_a)>=16:
                    ca=rows_a['close'].values.astype(float)
                    ha=rows_a['high'].values.astype(float)
                    la=rows_a['low'].values.astype(float)
                    trs=[]
                    for i in range(max(1,len(ca)-16),len(ca)):
                        tr=max(ha[i]-la[i],abs(ha[i]-ca[i-1]),abs(la[i]-ca[i-1]))
                        trs.append(tr)
                    if len(trs)>=14: atr_v=np.mean(trs[-14:])
            if atr_v>0 and cur_p<=peak-ATR_MULT*atr_v:
                reason = "TRAIL_STOP"

        # 时间退出
        if reason is None:
            from datetime import datetime as dt2
            e=dt2.strptime(entry_d,'%Y-%m-%d')
            n=dt2.strptime(date_str,'%Y-%m-%d')
            if (n-e).days>=MAX_DAYS:
                reason = "TIME_OUT"

        if reason:
            ret=(cur_p/ep-1)*100
            cash += pos['shares']*cur_p
            trade_log.append({'date':date_str,'code':code,'action':'SELL',
                              'price':cur_p,'shares':pos['shares'],
                              'return':f'{ret:.1f}%','reason':reason})
            del positions[code]

    # 买入
    current_count = len(positions)
    vacant = MAX_POS - current_count
    if vacant > 0 and candidates:
        for rank, (code, ret_20d, entry_p, _, today_c) in enumerate(candidates[:vacant]):
            if code in positions: continue
            if rank<3: w=0.12
            elif rank<7: w=0.10
            else: w=0.08
            cap_this = cash * w
            shares = int(cap_this/(entry_p*100))*100
            if shares>=100:
                cost=shares*entry_p
                cash-=cost
                positions[code]={'shares':shares,'entry_date':date_str,
                                 'entry_price':entry_p,'peak':entry_p}
                trade_log.append({'date':date_str,'code':code,'action':'BUY',
                                  'price':entry_p,'shares':shares,'ret20d':f'{ret_20d*100:.1f}%'})

    total_v = cash
    for code,pos in positions.items():
        df_s=stock_data.get(code)
        if df_s is None: continue
        row=df_s[df_s['date']==date_dt]
        if len(row)==0: row=df_s[df_s['date']<date_dt].tail(1)
        if len(row)>0: total_v+=pos['shares']*float(row['close'].iloc[0])
    nav_history.append({'date':date_str,'nav':total_v,'pos':len(positions)})

    if (di-start_idx)%120==0:
        print(f"  {date_str} NAV={total_v/10000:.1f}万 持仓={len(positions)}只")

# ===== 绩效分析 =====
print("\n"+"="*60)
print("     QMT v6最终优化版 10年回测报告")
print("="*60)

df_nav=pd.DataFrame(nav_history)
trades=pd.DataFrame(trade_log)
sells=trades[trades['action']=='SELL']
buys=trades[trades['action']=='BUY']
fn=df_nav['nav'].iloc[-1]
tr=(fn/initial_cap-1)*100
yrs=len(df_nav)/245
ar=(fn/initial_cap)**(1/yrs)-1
br=(idx_closes[-1]/idx_closes[start_idx]-1)*100

df_nav['peak']=df_nav['nav'].cummax()
df_nav['dd']=(df_nav['nav']-df_nav['peak'])/df_nav['peak']*100
mdd=df_nav['dd'].min()

dr=np.diff(df_nav['nav'].values)/df_nav['nav'].values[:-1]
sp=np.mean(dr)/max(np.std(dr),0.0001)*np.sqrt(245)

if len(sells)>0:
    er=lambda s:float(str(s).replace('%','')) if '%' in str(s) else 0
    rs=[er(r) for r in sells['return']]
    wins=sum(1 for r in rs if r>0)
    los=sum(1 for r in rs if r<0)
    wr=wins/len(rs)*100 if rs else 0
    aw=np.mean([r for r in rs if r>0]) if wins>0 else 0
    al=abs(np.mean([r for r in rs if r<0])) if los>0 else 0
    pl=aw/max(al,0.001)
else:
    wr,aw,al,pl=0,0,0,0

print(f"""
【基础参数】
  策略: 均线多头精选+ATR移动止盈
  股票池: 沪深300（前100只）
  持仓: 最多{MAX_POS}只，前3名12%/中4名10%/后3名8%
  区间: {df_nav['date'].iloc[0]} → {df_nav['date'].iloc[-1]}
  交易日: {len(df_nav)}天 ({yrs:.1f}年)

【收益表现】
  初始: 100万  →  最终: {fn/10000:.2f}万
  总收益率: {tr:.2f}%
  年化收益: {ar*100:.2f}%
  基准沪深300: {br:.2f}%
  超额收益: {tr-br:.2f}%

【风险指标】
  最大回撤: {mdd:.2f}%
  夏普比率: {sp:.3f}
  卡玛比率: {abs(ar*100/mdd):.2f}

【交易统计】
  总交易: {len(buys)}买 / {len(sells)}卖
  胜率: {wr:.1f}%
  平均盈利: {aw:.1f}%  平均亏损: {al:.1f}%
  盈亏比: {pl:.2f}
""")

if len(sells)>0:
    print("【卖出原因分布】")
    for r,c in sells['reason'].value_counts().items():
        print(f"  {r}: {c}次")

df_nav.to_csv(os.path.expanduser('~/VT/v6_10yr_nav.csv'),index=False)
trades.to_csv(os.path.expanduser('~/VT/v6_10yr_trades.csv'),index=False)
print(f"\n保存到 ~/VT/v6_10yr_nav.csv")
