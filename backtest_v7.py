#!/usr/bin/env python3
"""Vibe-Trading策略回测（多因子动量+趋势跟踪）
回测沪深300成分股，多因子排名选前15只
"""
import numpy as np
import pandas as pd
import json, time, os
from datetime import datetime, timedelta

np.random.seed(42)

# ===== 参数 =====
START_DATE = '20210503'
END_DATE   = '20260503'
TOP_N      = 15
STOP_LOSS  = 0.97
TAKE_PROFIT = 1.08
TRAIL_STOP = 0.975
MAX_HOLD   = 10
W_MOMENTUM = 0.40
W_TREND    = 0.30
W_VOL      = 0.20
W_VOLUME   = 0.10

# ===== 获取数据 =====
print("正在获取沪深300成分股列表...")

# 用akshare获取沪深300成分股（免费，无需token）
import akshare as ak

try:
    df_cons = ak.index_stock_cons_csindex("000300")
    cons_codes = df_cons['成分券代码'].astype(str).str[:6].tolist()
    # 补上交易所后缀
    cons_codes_full = []
    for c in cons_codes:
        if c.startswith('6') or c.startswith('9'):
            cons_codes_full.append(c + '.SH')
        else:
            cons_codes_full.append(c + '.SZ')
    cons_codes = cons_codes_full
except:
    # 备用：从新浪获取300etf持仓
    print("akshare获取失败，使用预设名单...")
    # 沪深300常见前200只
    cons_codes = []  # 后面会从Tushare补充

print(f"获取到 {len(cons_codes)} 只成分股")

# 用akshare获取指数数据
df_idx = ak.stock_zh_index_daily(symbol="sz000300")
df_idx = df_idx.rename(columns={'date': 'trade_date', 'close': 'close'})
df_idx['trade_date'] = pd.to_datetime(df_idx['trade_date']).dt.strftime('%Y%m%d')
df_idx = df_idx.sort_values('trade_date').reset_index(drop=True)
df_idx = df_idx[(df_idx['trade_date'] >= START_DATE) & (df_idx['trade_date'] <= END_DATE)].reset_index(drop=True)
print(f"指数数据: {len(df_idx)} 天")

# 获取前200只股票的数据（节省时间）
codes = cons_codes[:200]
all_data = {}

for i, code in enumerate(codes):
    try:
        # 用akshare获取日线数据
        symbol = code.lower().replace('.sh', 'sh').replace('.sz', 'sz')
        df = ak.stock_zh_a_hist(symbol=code[:6], start_date='20200101', end_date=END_DATE)
        if df is None or len(df) < 100:
            continue
        df = df.rename(columns={'日期': 'trade_date', '收盘': 'close',
                                '开盘': 'open', '最高': 'high', '最低': 'low', '成交量': 'vol'})
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
        df = df.sort_values('trade_date').reset_index(drop=True)
        all_data[code] = df
    except:
        continue
    if (i+1) % 20 == 0:
        print(f"  已获取 {i+1}/{len(codes)} 只股票...")

print(f"成功获取 {len(all_data)} 只股票数据")

# ===== 回测引擎 =====
dates = df_idx['trade_date'].values
idx_close = df_idx['close'].values

portfolios = []  # 每日持仓记录

class Position:
    __slots__ = ('code', 'entry_date', 'entry_price', 'peak_price', 'hold_days', 'shares')
    def __init__(self, code, entry_date, entry_price, shares):
        self.code = code
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.peak_price = entry_price
        self.hold_days = 0
        self.shares = shares

# 找到每天的数据索引
def get_stock_price(code, date_str, field='close'):
    if code not in all_data:
        return None
    df = all_data[code]
    idx = df.index[df['trade_date'] == date_str].tolist()
    if not idx:
        return None
    return float(df.iloc[idx[0]][field])

def get_stock_history(code, date_str, n_days, field='close'):
    """获取某只股票往前N天的价格序列"""
    if code not in all_data:
        return None
    df = all_data[code]
    pos = df.index[df['trade_date'] == date_str].tolist()
    if not pos:
        return None
    pos = pos[0]
    start = max(0, pos - n_days + 1)
    if pos - start + 1 < n_days:
        return None
    return df.iloc[start:pos+1][field].values.astype(float)

initial_capital = 1_000_000
capital = initial_capital
positions = {}  # {code: Position}
trade_log = []
total_days = len(dates)

# 找到数据开始的起点（所有股票都有足够历史数据）
start_idx = 62  # 需要62天数据计算指标

for di in range(start_idx, total_days):
    date_str = dates[di]
    idx_close_today = float(idx_close[di])
    
    # 计算均线
    idx_ma60 = np.mean(idx_close[di-61:di].astype(float))
    market_bull = idx_close_today > idx_ma60
    
    if (di - start_idx) % 20 == 0:
        print(f"回测中: {date_str} ({di-start_idx+1}/{total_days-start_idx})")
    
    if not market_bull:
        # 熊市清仓
        for code in list(positions.keys()):
            pos = positions[code]
            ret = (pos.entry_price - pos.entry_price) / pos.entry_price  # 简化
            trade_log.append({'date': date_str, 'code': code, 'action': 'LIQUIDATE',
                             'price': 0, 'reason': 'MARKET_BEAR'})
            capital += pos.shares * 0  # 简化
        positions.clear()
        portfolios.append({'date': date_str, 'stock_count': 0, 'value': capital})
        continue
    
    # 计算所有股票的因子分数
    scores = {}
    cur_prices = {}
    
    for code in all_data:
        close_arr = get_stock_history(code, date_str, 62)
        if close_arr is None or len(close_arr) < 62:
            continue
        
        cur_p = float(close_arr[-1])
        cur_prices[code] = cur_p
        
        ma20 = np.mean(close_arr[-21:-1])
        ma60 = np.mean(close_arr[-61:-1])
        
        # 基础筛选
        if not (cur_p > ma20 > ma60):
            continue
        
        # 动量
        mom_20d = cur_p / close_arr[-21] - 1
        
        # 趋势强度
        trend_str = cur_p / ma20 - 1
        
        # 低波动
        daily_ret = close_arr[-21:] / np.roll(close_arr[-21:], 1) - 1
        daily_ret = daily_ret[1:]
        vol_20d = np.std(daily_ret)
        vol_score = 1.0 / max(vol_20d, 0.001)
        
        # 成交量
        vol_arr = get_stock_history(code, date_str, 21, 'vol')
        if vol_arr is None or len(vol_arr) < 21:
            continue
        avg_vol = np.mean(vol_arr[:-1])
        vol_ratio = vol_arr[-1] / max(avg_vol, 1)
        
        scores[code] = {
            'momentum': mom_20d, 'trend': trend_str,
            'vol_score': vol_score, 'vol_ratio': vol_ratio
        }
    
    if len(scores) < TOP_N:
        # 记录当前持仓价值
        total_value = capital
        for code, pos in positions.items():
            p = get_stock_price(code, date_str)
            if p:
                total_value += pos.shares * p
        portfolios.append({'date': date_str, 'stock_count': len(positions), 'value': total_value})
        continue
    
    # 因子标准化
    stock_list = list(scores.keys())
    for factor in ['momentum', 'trend', 'vol_score', 'vol_ratio']:
        vals = np.array([scores[s][factor] for s in stock_list])
        v_min, v_max = np.min(vals), np.max(vals)
        rng = v_max - v_min
        if rng > 0:
            normalized = (vals - v_min) / rng
            for i, s in enumerate(stock_list):
                scores[s][factor + '_n'] = normalized[i]
        else:
            for s in stock_list:
                scores[s][factor + '_n'] = 0.5
    
    # 综合得分
    for s in stock_list:
        scores[s]['final'] = (
            scores[s].get('momentum_n', 0) * W_MOMENTUM +
            scores[s].get('trend_n', 0) * W_TREND +
            scores[s].get('vol_score_n', 0) * W_VOL +
            scores[s].get('vol_ratio_n', 0) * W_VOLUME
        )
    
    ranked = sorted(stock_list, key=lambda s: scores[s]['final'], reverse=True)
    selected = set(ranked[:TOP_N])
    
    # 风控检查
    for code in list(positions.keys()):
        pos = positions[code]
        if pos.entry_date == date_str:
            continue  # T+1
        
        p = get_stock_price(code, date_str)
        if p is None:
            continue
        
        pos.hold_days += 1
        if p > pos.peak_price:
            pos.peak_price = p
        
        reason = None
        if p / pos.entry_price < STOP_LOSS:
            reason = 'STOP_LOSS'
        elif p / pos.entry_price > TAKE_PROFIT:
            reason = 'TAKE_PROFIT'
        elif p / pos.peak_price < TRAIL_STOP and pos.peak_price > pos.entry_price * 1.01:
            reason = 'TRAIL_STOP'
        elif pos.hold_days >= MAX_HOLD:
            reason = 'TIME_EXIT'
        
        if reason:
            ret_pct = (p / pos.entry_price - 1) * 100
            trade_log.append({'date': date_str, 'code': code, 'action': 'SELL',
                             'price': round(p, 2), 'shares': pos.shares,
                             'return': f'{ret_pct:.1f}%', 'reason': reason})
            del positions[code]
    
    # 卖出不在选中列表的
    for code in list(positions.keys()):
        pos = positions[code]
        if code not in selected and pos.entry_date != date_str:
            p = get_stock_price(code, date_str)
            if p:
                ret_pct = (p / pos.entry_price - 1) * 100
                trade_log.append({'date': date_str, 'code': code, 'action': 'SELL',
                                 'price': round(p, 2), 'shares': pos.shares,
                                 'return': f'{ret_pct:.1f}%', 'reason': 'REBALANCE'})
                capital += pos.shares * p
                del positions[code]
    
    # 买入新入选的
    cap_per = capital * (1.0 / TOP_N) * 0.95 if len(positions) < TOP_N else 0
    for code in selected:
        if code in positions:
            continue
        if cap_per <= 0:
            break
        p = cur_prices.get(code)
        if p is None:
            continue
        shares = int(cap_per / (p * 100)) * 100
        if shares >= 100:
            cost = shares * p
            capital -= cost
            positions[code] = Position(code, date_str, p, shares)
            trade_log.append({'date': date_str, 'code': code, 'action': 'BUY',
                             'price': round(p, 2), 'shares': shares,
                             'score': round(scores[code]['final'], 3)})
    
    # 记录组合价值
    total_value = capital
    for code, pos in positions.items():
        p = get_stock_price(code, date_str)
        if p:
            total_value += pos.shares * p
    portfolios.append({'date': date_str, 'stock_count': len(positions), 'value': total_value})

# ===== 计算绩效指标 =====
print("\n========== 回测结果 ==========")

pf = pd.DataFrame(portfolios)
pf['return'] = pf['value'].pct_change()

# 基准：等权持有沪深300
benchmark_returns = idx_close[start_idx:len(idx_close)].astype(float)
benchmark_returns = benchmark_returns / benchmark_returns[0]
benchmark_pct = (benchmark_returns[-1] / benchmark_returns[0] - 1) * 100

final_value = pf['value'].iloc[-1]
total_return = (final_value / initial_capital - 1) * 100

# 年化
years = len(pf) / 245
annual_return = (final_value / initial_capital) ** (1 / years) - 1

# 最大回撤
pf['peak'] = pf['value'].cummax()
pf['drawdown'] = (pf['value'] - pf['peak']) / pf['peak'] * 100
max_dd = pf['drawdown'].min()

# 夏普比率
daily_ret = pf['return'].dropna()
sharpe = np.mean(daily_ret) / np.std(daily_ret) * np.sqrt(245) if np.std(daily_ret) > 0 else 0

# 交易统计
trades = pd.DataFrame(trade_log)
buy_trades = trades[trades['action'] == 'BUY']
sell_trades = trades[trades['action'] == 'SELL']
total_trades = len(sell_trades)

if total_trades > 0:
    extract_return = lambda s: float(s.replace('%','')) if isinstance(s, str) and '%' in s else 0
    if 'return' in sell_trades.columns:
        returns_list = [extract_return(r) for r in sell_trades['return']]
        win_trades = sum(1 for r in returns_list if r > 0)
        win_rate = win_trades / total_trades * 100
        avg_return = np.mean(returns_list) if returns_list else 0
    else:
        win_rate = 0
        avg_return = 0
    profit_loss_ratio = avg_return / abs(np.mean([r for r in returns_list if r < 0])) if any(r < 0 for r in returns_list) else 0
else:
    win_rate = 0
    avg_return = 0
    profit_loss_ratio = 0

print(f"""
{'='*50}
       多因子动量+趋势跟踪策略 回测报告
{'='*50}

【基础参数】
  选股范围: 沪深300成分股
  持仓数量: {TOP_N}只
  回测区间: {START_DATE} → {END_DATE} ({years:.1f}年)
  初始资金: {initial_capital/10000:.0f}万

【收益表现】
  最终资产: {final_value/10000:.2f}万
  总收益率: {total_return:.2f}%
  年化收益: {annual_return*100:.2f}%
  基准收益(沪深300等权持有): {benchmark_pct:.2f}%
  超额收益: {total_return - benchmark_pct:.2f}%

【风险指标】
  最大回撤: {max_dd:.2f}%
  夏普比率: {sharpe:.3f}

【交易统计】
  总交易次数: {total_trades}
  胜率: {win_rate:.1f}%
  平均单笔收益率: {avg_return:.2f}%
  盈亏比: {profit_loss_ratio:.2f}
  日均持仓数: {pf['stock_count'].mean():.1f}只
""")

# 保存结果
output = {
    'final_value': round(final_value, 2),
    'total_return': round(total_return, 2),
    'annual_return': round(annual_return*100, 2),
    'max_drawdown': round(max_dd, 2),
    'sharpe': round(sharpe, 3),
    'win_rate': round(win_rate, 1),
    'trade_count': total_trades,
    'benchmark_return': round(benchmark_pct, 2),
    'excess_return': round(total_return - benchmark_pct, 2),
    'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
}

with open(os.path.expanduser('~/VT/backtest_result.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"结果已保存到 ~/VT/backtest_result.json")
print(f"交易日志: {len(trade_log)} 条")
