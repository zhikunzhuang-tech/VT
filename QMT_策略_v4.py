#encoding:gbk
"""
QMT 量化策略 v4 — 均线多头 + 强势股精选 + ATR跟踪止损
=========================================================
买入条件:
  1. MA5 > MA10 > MA20 (均线多头)
  2. close > MA20 and MA20 > MA60 (价格位置)
  3. -9.5% < 5日涨幅 < 10%
  4. 前日阴线 OR 当日 < 前日收盘
  5. 成交量 > 20日均量
  6. 沪深300 > MA60 (市场择时)
  7. 个股20日涨幅 > 沪深300 20日涨幅 (相对强度)

卖出条件:
  1. MA5 < MA10 (死叉)
  2. ATR 3倍跟踪止损 (从最高点回落)
  3. -7% 硬止损
  4. 持仓满20日

仓位: 最多10只, 按排名动态分配 12%/10%/8%
"""

import numpy as np
import pandas as pd
import datetime
import os
import json

# ============================================================
# 全局状态
# ============================================================
class G:
    pass
G.ctx = G()


# ============================================================
# 沪深300成分股列表 (300只)
# ============================================================
HS300_CODES = [
    "000001.SZ","000002.SZ","000063.SZ","000100.SZ","000157.SZ","000166.SZ","000301.SZ","000333.SZ","000338.SZ","000408.SZ",
    "000423.SZ","000425.SZ","000538.SZ","000568.SZ","000596.SZ","000617.SZ","000625.SZ","000629.SZ","000651.SZ","000661.SZ",
    "000683.SZ","000708.SZ","000725.SZ","000733.SZ","000768.SZ","000776.SZ","000786.SZ","000792.SZ","000800.SZ","000858.SZ",
    "000876.SZ","000877.SZ","000887.SZ","000895.SZ","000938.SZ","000963.SZ","000977.SZ","000983.SZ","001979.SZ","002001.SZ",
    "002007.SZ","002008.SZ","002027.SZ","002028.SZ","002044.SZ","002049.SZ","002050.SZ","002056.SZ","002074.SZ","002075.SZ",
    "002120.SZ","002129.SZ","002142.SZ","002152.SZ","002155.SZ","002156.SZ","002179.SZ","002180.SZ","002185.SZ","002192.SZ",
    "002202.SZ","002203.SZ","002230.SZ","002236.SZ","002241.SZ","002252.SZ","002262.SZ","002271.SZ","002294.SZ","002304.SZ",
    "002311.SZ","002317.SZ","002318.SZ","002340.SZ","002352.SZ","002371.SZ","002410.SZ","002414.SZ","002415.SZ","002422.SZ",
    "002428.SZ","002432.SZ","002436.SZ","002459.SZ","002460.SZ","002463.SZ","002466.SZ","002475.SZ","002493.SZ","002555.SZ",
    "002557.SZ","002558.SZ","002568.SZ","002572.SZ","002594.SZ","002600.SZ","002601.SZ","002602.SZ","002603.SZ","002607.SZ",
    "002624.SZ","002625.SZ","002648.SZ","002673.SZ","002709.SZ","002714.SZ","002736.SZ","002738.SZ","002747.SZ","002756.SZ",
    "002773.SZ","002791.SZ","002812.SZ","002821.SZ","002841.SZ","002850.SZ","002916.SZ","002920.SZ","002925.SZ","002926.SZ",
    "002936.SZ","002938.SZ","002939.SZ","002945.SZ","002947.SZ","002948.SZ","002955.SZ","002958.SZ","002959.SZ","002960.SZ",
    "002966.SZ","003816.SZ","300002.SZ","300003.SZ","300014.SZ","300015.SZ","300017.SZ","300024.SZ","300033.SZ","300034.SZ",
    "300054.SZ","300059.SZ","300073.SZ","300074.SZ","300115.SZ","300122.SZ","300124.SZ","300136.SZ","300142.SZ","300144.SZ",
    "300146.SZ","300274.SZ","300285.SZ","300294.SZ","300296.SZ","300298.SZ","300308.SZ","300315.SZ","300316.SZ","300319.SZ",
    "300327.SZ","300347.SZ","300357.SZ","300373.SZ","300376.SZ","300394.SZ","300395.SZ","300408.SZ","300413.SZ","300418.SZ",
    "300433.SZ","300438.SZ","300442.SZ","300450.SZ","300454.SZ","300456.SZ","300457.SZ","300474.SZ","300476.SZ","300482.SZ",
    "300496.SZ","300498.SZ","300502.SZ","300504.SZ","300529.SZ","300558.SZ","300567.SZ","300595.SZ","300596.SZ","300601.SZ",
    "300602.SZ","300618.SZ","300624.SZ","300628.SZ","300630.SZ","300633.SZ","300634.SZ","300638.SZ","300639.SZ","300661.SZ",
    "300666.SZ","300674.SZ","300676.SZ","300677.SZ","300679.SZ","300682.SZ","300685.SZ","300699.SZ","300723.SZ","300724.SZ",
    "300725.SZ","300726.SZ","300741.SZ","300750.SZ","300751.SZ","300759.SZ","300760.SZ","300761.SZ","300763.SZ","300765.SZ",
    "300769.SZ","300773.SZ","300775.SZ","300776.SZ","300782.SZ","300803.SZ","300821.SZ","300832.SZ","300833.SZ","300839.SZ",
    "300850.SZ","300861.SZ","300866.SZ","300870.SZ","300871.SZ","300888.SZ","300893.SZ","300894.SZ","300896.SZ","300910.SZ",
    "300913.SZ","300919.SZ","300954.SZ","300957.SZ","300979.SZ","300999.SZ","600000.SH","600004.SH","600006.SH","600007.SH",
    "600008.SH","600009.SH","600010.SH","600011.SH","600012.SH","600015.SH","600016.SH","600018.SH","600019.SH","600021.SH",
    "600023.SH","600025.SH","600026.SH","600027.SH","600028.SH","600029.SH","600030.SH","600031.SH","600033.SH","600036.SH",
    "600037.SH","600038.SH","600039.SH","600048.SH","600050.SH","600053.SH","600055.SH","600061.SH","600062.SH","600063.SH",
    "600064.SH","600066.SH","600068.SH","600070.SH","600071.SH","600072.SH","600073.SH","600074.SH","600075.SH","600076.SH",
    "600077.SH","600078.SH","600079.SH","600080.SH","600081.SH","600082.SH","600083.SH","600084.SH","600085.SH","600086.SH"
]

# ============================================================
# 策略参数
# ============================================================
MAX_POSITIONS = 10
MAX_HOLD_DAYS = 20
STOP_LOSS_PCT = -0.07
ATR_MULTIPLIER = 3.0
PCT_6D_LOW = -9.5
PCT_6D_HIGH = 10.0


def init(C):
    """策略初始化"""
    G.ctx.C = C
    G.ctx.acct = '680000006619'  # 替换为你的实际账号
    G.ctx.acct_type = 'STOCK'
    G.ctx.buy_code = 23 if G.ctx.acct_type == 'STOCK' else 33
    G.ctx.sell_code = 24 if G.ctx.acct_type == 'STOCK' else 34

    # 持仓跟踪: code -> {'entry_date':str, 'entry_price':float, 'highest':float, 'entry_gi':int}
    G.ctx.active = {}

    # 每日信号缓存
    G.ctx.daily_signals = []  # 当日买入候选列表 [(code, rank), ...]
    G.ctx.signals_date = ''   # 信号计算的日期，用于判断是否需重新计算

    # 账户信息
    G.ctx.bench_df = None  # 沪深300数据缓存
    G.ctx.data_cache = {}  # 股票日线数据缓存

    now_dt = datetime.datetime.today().strftime('%Y-%m-%d')
    # 9:00 预计算信号（开盘前）
    C.run_time('pre_market_scan', '1nDay', '{} 09:00:00'.format(now_dt))
    # 交易时段每秒检查
    C.run_time('trading_loop', '1nSecond', '{} 09:30:00'.format(now_dt))
    print('=== QMT v4 策略初始化完成 ===')
    print('股票池: 沪深300, 最大持仓: {}只'.format(MAX_POSITIONS))


def pre_market_scan(C):
    """盘前扫描全市场，计算今日买入信号"""
    print('=== 盘前扫描 ===')

    # 1. 获取沪深300指数数据
    bench_data = _get_benchmark_data(C)
    if bench_data is None or len(bench_data) < 60:
        print('沪深300数据不足，跳过扫描')
        return

    # 2. 检查市场择时条件
    bench_close = bench_data['close'].values
    bench_ma60 = pd.Series(bench_close).rolling(60).mean().values
    market_ok = bench_close[-1] > bench_ma60[-1] if not np.isnan(bench_ma60[-1]) else False
    bench_ret_20d = bench_close[-1] / bench_close[-21] - 1 if len(bench_close) > 21 else 0

    if not market_ok:
        print('市场择时: 沪深300 < MA60, 今日不买入')
        G.ctx.daily_signals = []
        G.ctx.signals_date = datetime.datetime.now().strftime('%Y-%m-%d')
        return

    print('市场择时: 沪深300 > MA60, 允许买入')

    # 3. 扫描所有股票
    candidates = []
    for code in HS300_CODES:
        try:
            df = _get_stock_data(C, code)
            if df is None or len(df) < 60:
                continue

            close = df['close'].values.astype(float)
            high = df['high'].values.astype(float)
            low = df['low'].values.astype(float)
            open_ = df['open'].values.astype(float)
            volume = df['volume'].values.astype(float)
            n = len(close)

            # 均线
            close_s = pd.Series(close)
            ma5 = close_s.rolling(5).mean().values
            ma10 = close_s.rolling(10).mean().values
            ma20 = close_s.rolling(20).mean().values
            ma60 = close_s.rolling(60).mean().values
            vol_ma20 = pd.Series(volume).rolling(20).mean().values

            # 需要最新值
            i = n - 1  # 最新bar索引
            if i < 20:
                continue

            # 条件1: MA5 > MA10 > MA20
            if not (ma5[i] > ma10[i] > ma20[i]):
                continue

            # 条件2: close > MA20 and MA20 > MA60
            if not (close[i] > ma20[i] > ma60[i]):
                continue

            # 条件3: 5日涨跌幅范围
            if i < 6:
                continue
            pct_5d = (close[i-1] / close[i-6] - 1) * 100
            if not (PCT_6D_LOW < pct_5d < PCT_6D_HIGH):
                continue

            # 条件4: 前日阴线 OR 今日低于昨日
            cond4a = close[i-1] < open_[i-1]
            cond4b = close[i] < close[i-1]
            if not (cond4a or cond4b):
                continue

            # 条件5: 成交量 > 20日均量
            if not (volume[i] > vol_ma20[i]):
                continue

            # 条件7: 个股20日涨幅 > 基准20日涨幅
            if i < 20:
                continue
            stock_ret_20d = close[i] / close[i-20] - 1
            if stock_ret_20d <= bench_ret_20d:
                continue

            # 通过所有条件!
            candidates.append((code, stock_ret_20d))

        except Exception as e:
            continue

    # 按相对强度排序
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 动态分配权重: 前3名12%, 中间4名10%, 后3名8%
    weighted = []
    for rank, (code, rs) in enumerate(candidates):
        if rank < 3:
            w = 0.12
        elif rank < 7:
            w = 0.10
        else:
            w = 0.08
        weighted.append((code, w, rs))

    G.ctx.daily_signals = weighted[:MAX_POSITIONS]
    G.ctx.signals_date = datetime.datetime.now().strftime('%Y-%m-%d')
    print('候选信号: {} 只'.format(len(G.ctx.daily_signals)))
    for code, w, rs in G.ctx.daily_signals[:5]:
        print('  {} 权重:{}% 强度:{:.2f}%'.format(code, w*100, rs*100))


def trading_loop(C):
    """每秒执行的交易逻辑"""
    now = datetime.datetime.now()
    now_time = now.strftime('%H%M%S')

    # 只在交易时段执行
    if now_time < '093000' or now_time > '145700':
        return

    today = now.strftime('%Y-%m-%d')

    # ---- 1. 检查持仓卖出 ----
    _check_exits(C, today)

    # ---- 2. 检查买入 ----
    # 只有信号有效时才买入
    if G.ctx.signals_date == today and G.ctx.daily_signals:
        _check_entries(C, today)


def _check_exits(C, today):
    """检查卖出条件"""
    positions = get_trade_detail_data(G.ctx.acct, G.ctx.acct_type, 'POSITION')
    if not positions:
        return

    hold_codes = {}
    for pos in positions:
        code = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        vol = pos.m_nCanUseVolume
        if vol > 0:
            hold_codes[code] = vol

    if not hold_codes:
        return

    # 获取所有持仓的日线数据
    for code, vol in hold_codes.items():
        df = _get_stock_data(C, code)
        if df is None or len(df) < 10:
            continue

        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        n = len(close)

        if n < 6:
            continue

        close_s = pd.Series(close)
        ma5 = close_s.rolling(5).mean().values
        ma10 = close_s.rolling(10).mean().values
        atr14 = _calc_atr(high, low, close, 14)

        i = n - 1
        should_sell = False
        reason = ''

        # 获取持仓记录
        active_info = G.ctx.active.get(code)
        if active_info is None:
            continue

        entry_price = active_info['entry_price']
        highest = active_info.get('highest', close[i])
        entry_day = active_info.get('entry_date', today)

        # 更新最高价
        if close[i] > highest:
            highest = close[i]
            G.ctx.active[code]['highest'] = highest

        hold_days = _days_between(entry_day, today)
        ret = close[i] / entry_price - 1

        # 卖出条件1: MA5 < MA10 死叉
        if not np.isnan(ma5[i]) and not np.isnan(ma10[i]) and ma5[i] < ma10[i]:
            should_sell = True
            reason = '死叉'

        # 卖出条件2: 硬止损 -7%
        elif ret <= STOP_LOSS_PCT:
            should_sell = True
            reason = '止损({:.1f}%)'.format(ret*100)

        # 卖出条件3: ATR跟踪止损
        elif not np.isnan(atr14[i]) and atr14[i] > 0:
            trailing_stop = highest - ATR_MULTIPLIER * atr14[i]
            if close[i] <= trailing_stop:
                should_sell = True
                reason = '跟踪止损'

        # 卖出条件4: 持仓满20日
        elif hold_days >= MAX_HOLD_DAYS:
            should_sell = True
            reason = '到期({}天)'.format(hold_days)

        if should_sell:
            print('{} 卖出 {} 原因:{} 收益:{:.2f}% 持有:{}天'.format(
                today, code, reason, ret*100, hold_days))
            passorder(G.ctx.sell_code, 1101, G.ctx.acct, code, 14, -1, vol,
                     'V4卖出', 1, '{} {} 卖出'.format(code, reason), C)
            if code in G.ctx.active:
                del G.ctx.active[code]


def _check_entries(C, today):
    """检查买入"""
    # 当前持仓数
    positions = get_trade_detail_data(G.ctx.acct, G.ctx.acct_type, 'POSITION')
    current_count = sum(1 for p in positions if p.m_nCanUseVolume > 0) if positions else 0

    if current_count >= MAX_POSITIONS:
        return

    # 已持仓代码
    hold_codes = set()
    if positions:
        for p in positions:
            if p.m_nCanUseVolume > 0:
                hold_codes.add(p.m_strInstrumentID + '.' + p.m_strExchangeID)

    # 可用资金(留10%余量)
    available = get_buying_amount() * 0.9

    vacant = MAX_POSITIONS - current_count
    added = 0

    for code, weight, rs in G.ctx.daily_signals:
        if added >= vacant:
            break
        if code in hold_codes or code in G.ctx.active:
            continue

        # 获取实时行情确认条件6 (当日 < 前日收盘)
        tick = C.get_full_tick([code])
        if not tick or code not in tick:
            continue

        current_price = tick[code].get('lastPrice', 0)
        if current_price <= 0:
            continue

        df = _get_stock_data(C, code)
        if df is None:
            continue
        prev_close = float(df['close'].values[-2]) if len(df) > 1 else 0

        if current_price >= prev_close:
            continue  # 当日没有低于前日收盘，等待

        # 计算买入股数
        buy_amount = available * weight / vacant
        buy_shares = int(buy_amount / (current_price * 100)) * 100
        if buy_shares < 100:
            continue

        # 记录持仓
        G.ctx.active[code] = {
            'entry_date': today,
            'entry_price': current_price,
            'highest': current_price
        }

        print('{} {} 买入 价格:{} 股数:{} 权重:{:.0f}%'.format(
            today, code, current_price, buy_shares, weight*100))
        passorder(G.ctx.buy_code, 1101, G.ctx.acct, code, 14, -1, buy_shares,
                 'V4买入', 2, '{} V4信号买入'.format(code), C)
        added += 1


def _get_benchmark_data(C):
    """获取沪深300指数日线"""
    if G.ctx.bench_df is not None and len(G.ctx.bench_df) > 60:
        return G.ctx.bench_df

    try:
        download_history_data('000300.SH', '1d', '20220101', '20991231')
    except:
        pass

    data = C.get_market_data_ex(['close', 'open', 'high', 'low', 'volume'],
                                 ['000300.SH'], period='1d', count=500)

    if data and '000300.SH' in data:
        G.ctx.bench_df = data['000300.SH']
    return G.ctx.bench_df


def _get_stock_data(C, code):
    """获取个股日线数据（带缓存）"""
    if code in G.ctx.data_cache:
        df = G.ctx.data_cache[code]
        if df is not None and len(df) > 60:
            return df

    try:
        download_history_data(code, '1d', '20220101', '20991231')
    except:
        pass

    data = C.get_market_data_ex(['close', 'open', 'high', 'low', 'volume'],
                                 [code], period='1d', count=200)

    if data and code in data:
        G.ctx.data_cache[code] = data[code]
        return data[code]
    return None


def _calc_atr(high, low, close, period=14):
    """计算ATR"""
    tr_list = []
    for i in range(1, len(close)):
        hl = high[i] - low[i]
        hc = abs(close[i-1] - high[i])
        lc = abs(close[i-1] - low[i])
        tr_list.append(max(hl, hc, lc))

    tr_s = pd.Series(tr_list)
    return tr_s.rolling(period).mean().values


def _days_between(d1, d2):
    """计算两个日期字符串之间的天数"""
    try:
        a = datetime.datetime.strptime(d1, '%Y-%m-%d')
        b = datetime.datetime.strptime(d2, '%Y-%m-%d')
        return (b - a).days
    except:
        return 0
