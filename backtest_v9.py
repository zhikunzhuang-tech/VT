#!/usr/bin/env python3
"""QMT v9 Strategy Backtest - 改良均线多头+ATR回调"""
import numpy as np
import pandas as pd
import time, os, sys
from datetime import datetime, timedelta

# ===== 策略参数（与QMT版本一致） =====
TOP_N = 15
STOP_LOSS = 0.95
TAKE_PROFIT = 1.10
MAX_HOLD_DAYS = 15
W_MOM = 0.6
W_ATR = 0.4

def calc_indicators(closes, highs, lows):
    """计算策略所需的指标"""
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)

    cur_p = c[-1]
    prev_close = c[-2]
    prev2_close = c[-3]

    ma5 = np.mean(c[-6:-1])
    ma10 = np.mean(c[-11:-1])
    ma20 = np.mean(c[-21:-1])
    ma60 = np.mean(c[-61:-1])

    ret5d = (c[-1] / c[-6] - 1) * 100

    # ATR(14)
    tr_list = []
    for i in range(max(1, len(c) - 16), len(c)):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        tr_list.append(tr)
    if len(tr_list) < 15:
        return None
    atr_prev1 = np.mean(tr_list[-15:-1])
    atr_prev2 = np.mean(tr_list[-16:-2])

    yesterday_down = prev_close < prev2_close

    return {
        'cur_p': cur_p, 'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'ret5d': ret5d, 'atr_p1': atr_prev1, 'atr_p2': atr_prev2,
        'yesterday_down': yesterday_down
    }

# ===== 获取数据 =====
print("=== 获取数据 ===")
import akshare as ak
os.environ['no_proxy'] = '.eastmoney.com,.sina.com.cn,.csindex.com.cn'

# 沪深300成分股
cons = ak.index_stock_cons_csindex("000300")
codes = cons['成分券代码'].astype(str).str.zfill(6).tolist()
full_codes = [c + '.SH' if c.startswith(('6', '9')) else c + '.SZ' for c in codes]
print(f"成分股: {len(full_codes)}只")

# 沪深300指数数据
df_idx = ak.stock_zh_index_daily_em(symbol="sh000300")
df_idx = df_idx.rename(columns={'日期': 'date', '收盘': 'close'})
df_idx['date'] = pd.to_datetime(df_idx['date'])
df_idx = df_idx.sort_values('date').reset_index(drop=True)
df_idx = df_idx[(df_idx['date'] >= '2017-01-01') & (df_idx['date'] <= '2026-05-03')]
print(f"指数数据: {len(df_idx)}天")

idx_dates = df_idx['date'].values
idx_closes = df_idx['close'].values.astype(float)

# 取前100只股票（节省时间，但足够15只持仓）
test_codes = full_codes[:100]
stock_data = {}

for i, code in enumerate(test_codes):
    try:
        raw = code[:6]
        df = ak.stock_zh_a_hist(symbol=raw, start_date='20160101', end_date='20260503')
        if df is None or len(df) < 200:
            continue
        df = df.rename(columns={'日期': 'date', '收盘': 'close', '开盘': 'open',
                                '最高': 'high', '最低': 'low', '成交量': 'volume'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        stock_data[code] = df
    except:
        continue
    if (i+1) % 20 == 0:
        print(f"  已获取 {i+1}/{len(test_codes)}...")

print(f"成功获取 {len(stock_data)} 只股票数据")

# ===== 回测引擎 =====
print("\n=== 开始回测 ===")

initial_cap = 1_000_000
cash = initial_cap
positions = {}  # {code: {'shares': n, 'entry_date': date, 'entry_price': p, 'peak_price': p}}
nav_history = []
trade_log = []

start_idx = 250  # 跳过前250天积累数据
total_days = len(idx_dates)

for di in range(start_idx, total_days):
    date_ts = pd.Timestamp(idx_dates[di])
    date_str = date_ts.strftime('%Y-%m-%d')
    date_dt = date_ts
    idx_close = float(idx_closes[di])

    # 市场择时：沪深300 > MA60
    if di < 61:
        continue
    hs300_ma60 = np.mean(idx_closes[di-60:di+1].astype(float))
    in_bull = idx_close > hs300_ma60

    if not in_bull:
        # 熊市清仓
        for code in list(positions.keys()):
            pos = positions[code]
            # 找最后价格
            df_s = stock_data.get(code)
            if df_s is None:
                continue
            row = df_s[df_s['date'] == date_dt]
            if len(row) == 0:
                row = df_s[df_s['date'] < date_dt].tail(1)
            if len(row) == 0:
                continue
            cur_p = float(row['close'].iloc[0])
            ret = (cur_p / pos['entry_price'] - 1) * 100
            cash += pos['shares'] * cur_p
            trade_log.append({'date': date_str, 'code': code, 'action': 'SELL',
                              'price': cur_p, 'shares': pos['shares'],
                              'return': f'{ret:.1f}%', 'reason': 'BEAR_MK'})
            del positions[code]
        nav = cash + sum(p['shares'] * 0 for p in positions.values())
        nav_history.append({'date': date_str, 'nav': nav, 'positions': len(positions)})
        continue

    # ---- 计算各股票指标 ----
    candidates = []

    for code in stock_data:
        df_s = stock_data[code]
        # 找到当天及之前的数据
        rows = df_s[df_s['date'] <= date_dt]
        if len(rows) < 62:
            continue
        rows = rows.tail(62)

        closes = rows['close'].values.astype(float)
        highs = rows['high'].values.astype(float)
        lows = rows['low'].values.astype(float)

        ind = calc_indicators(closes, highs, lows)
        if ind is None:
            continue

        # 入场条件
        entry_ok = (
            ind['ma5'] > ind['ma10'] > ind['ma20']
            and ind['cur_p'] > ind['ma20'] > ind['ma60']
            and -9.5 < ind['ret5d'] < 10
            and ind['yesterday_down']
            and ind['atr_p1'] > ind['atr_p2']
        )

        if not entry_ok:
            continue

        cur_p_date = float(rows['close'].iloc[-1])
        mom_score = cur_p_date / float(rows['close'].iloc[-21]) - 1
        atr_ratio = ind['atr_p1'] / max(ind['atr_p2'], 0.001) - 1
        score = mom_score * W_MOM + atr_ratio * W_ATR
        candidates.append((code, score, cur_p_date))

    # 排名选前15
    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = candidates[:TOP_N]
    selected_codes = set(s[0] for s in selected)

    # ===== 卖出 =====
    for code in list(positions.keys()):
        pos = positions[code]
        df_s = stock_data.get(code)
        if df_s is None:
            continue
        row = df_s[df_s['date'] == date_dt]
        if len(row) == 0:
            row = df_s[df_s['date'] < date_dt].tail(1)
        if len(row) == 0:
            continue
        cur_p = float(row['close'].iloc[0])

        # 更新最高价（用于移动止盈，暂时不用）
        # if cur_p > pos.get('peak', pos['entry_price']):
        #     pos['peak'] = cur_p

        cost = pos['entry_price']

        reason = None
        if cost > 0 and cur_p / cost < STOP_LOSS:
            reason = "STOP_LOSS"
        elif cost > 0 and cur_p / cost > TAKE_PROFIT:
            reason = "TAKE_PROFIT"
        elif code not in selected_codes:
            reason = "RANK_OUT"
        else:
            hold_days = (date_dt - pd.Timestamp(pos['entry_date'])).days
            if hold_days >= MAX_HOLD_DAYS:
                reason = "TIME_OUT"

        if reason:
            ret = (cur_p / cost - 1) * 100
            cash += pos['shares'] * cur_p
            trade_log.append({'date': date_str, 'code': code, 'action': 'SELL',
                              'price': cur_p, 'shares': pos['shares'],
                              'return': f'{ret:.1f}%', 'reason': reason})
            del positions[code]

    # ===== 买入 =====
    current_count = len(positions)
    slots = TOP_N - current_count
    if slots > 0:
        cap_per = cash * 0.95 / slots
        for code, score, cur_p in selected:
            if code in positions:
                continue
            shares = int(cap_per / (cur_p * 100)) * 100
            if shares >= 100:
                cost = shares * cur_p
                cash -= cost
                positions[code] = {'shares': shares, 'entry_date': date_str,
                                   'entry_price': cur_p}
                trade_log.append({'date': date_str, 'code': code, 'action': 'BUY',
                                  'price': cur_p, 'shares': shares,
                                  'score': f'{score:.4f}'})

    # NAV记录
    total_value = cash
    for code, pos in positions.items():
        df_s = stock_data.get(code)
        if df_s is None:
            continue
        row = df_s[df_s['date'] == date_dt]
        if len(row) == 0:
            row = df_s[df_s['date'] < date_dt].tail(1)
        if len(row) > 0:
            total_value += pos['shares'] * float(row['close'].iloc[0])
    nav_history.append({'date': date_str, 'nav': total_value,
                        'positions': len(positions)})

    if (di - start_idx) % 60 == 0:
        print(f"  {date_str} NAV={total_value/10000:.1f}万 持仓={len(positions)}只")

# ===== 绩效分析 =====
print("\n" + "="*60)
print("            QMT v9 策略回测报告")
print("="*60)

df_nav = pd.DataFrame(nav_history)
trades = pd.DataFrame(trade_log)
sells = trades[trades['action'] == 'SELL']
buys = trades[trades['action'] == 'BUY']
final_nav = df_nav['nav'].iloc[-1]

total_ret = (final_nav / initial_cap - 1) * 100
years = len(df_nav) / 245
annual_ret = (final_nav / initial_cap) ** (1 / years) - 1

# 基准收益
bench_ret = (idx_closes[-1] / idx_closes[start_idx] - 1) * 100

# 最大回撤
df_nav['peak'] = df_nav['nav'].cummax()
df_nav['dd'] = (df_nav['nav'] - df_nav['peak']) / df_nav['peak'] * 100
max_dd = df_nav['dd'].min()

# 夏普
daily_nav = df_nav['nav'].values
daily_rets = np.diff(daily_nav) / daily_nav[:-1]
sharpe = np.mean(daily_rets) / max(np.std(daily_rets), 0.0001) * np.sqrt(245)

# 胜率
if len(sells) > 0:
    extract_ret = lambda s: float(str(s).replace('%','')) if '%' in str(s) else 0
    rets = [extract_ret(r) for r in sells['return']]
    wins = sum(1 for r in rets if r > 0)
    losses = sum(1 for r in rets if r < 0)
    wr = wins / len(rets) * 100 if len(rets) > 0 else 0
    avg_win = np.mean([r for r in rets if r > 0]) if wins > 0 else 0
    avg_loss = abs(np.mean([r for r in rets if r < 0])) if losses > 0 else 0
    pl_ratio = avg_win / max(avg_loss, 0.001)
    total_pnl = sum(rets)
else:
    wr, avg_win, avg_loss, pl_ratio, total_pnl = 0, 0, 0, 0, 0

# 卖出原因分布
if len(sells) > 0:
    reasons = sells['reason'].value_counts()
else:
    reasons = None

print(f"""
【基础参数】
  股票池: 沪深300（前100只）
  持仓数: {TOP_N}只
  回测区间: {df_nav['date'].iloc[0]} → {df_nav['date'].iloc[-1]}
  交易日: {len(df_nav)}天

【收益表现】
  初始资金: 100万
  最终资产: {final_nav/10000:.2f}万
  总收益率: {total_ret:.2f}%
  年化收益: {annual_ret*100:.2f}%
  基准(沪深300)收益: {bench_ret:.2f}%

【风险指标】
  最大回撤: {max_dd:.2f}%
  夏普比率: {sharpe:.3f}

【交易统计】
  总交易: {len(buys)}买 / {len(sells)}卖
  胜率: {wr:.1f}%
  平均盈利: {avg_win:.1f}%  平均亏损: {avg_loss:.1f}%
  盈亏比: {pl_ratio:.2f}
""")

if reasons is not None:
    print("【卖出原因分布】")
    for r, c in reasons.items():
        print(f"  {r}: {c}次")

# 保存结果
df_nav.to_csv(os.path.expanduser('~/VT/v9_nav.csv'), index=False)
trades.to_csv(os.path.expanduser('~/VT/v9_trades.csv'), index=False)

print(f"\n结果已保存到 ~/VT/v9_nav.csv 和 v9_trades.csv")
