#coding:gbk
# Modified by Hermes Agent @ 2026-05-03 22:30
# QMT v6最终优化版 - 均线多头精选+ATR移动止盈
# Entry: MA多头 + 站上均线 + 适中涨幅 + 回调阴线 + 放量 + 市场择时 + 相对强度
# Exit: MA5死叉MA10 / -7%止损 / ATR跟踪止盈(3倍) / 20日时间退出
# 仓位：最多10只，动态分配(12%/10%/8%)

import numpy as np

MAX_POS = 10
MAX_DAYS = 20
STOP_LOSS = 0.93    # -7%
ATR_MULT = 3.0      # ATR跟踪止盈倍数

def init(ContextInfo):
    stocks = ContextInfo.get_stock_list_in_sector('沪深300')
    ContextInfo.set_universe(stocks)
    ContextInfo.stocks = stocks
    ContextInfo.accountID = 'testS'
    ContextInfo.entry_date = {}
    ContextInfo.entry_price = {}
    ContextInfo.peak_close = {}

def get_position_cost(ContextInfo, code):
    r = get_trade_detail_data(ContextInfo.accountID, "STOCK", "POSITION")
    for obj in r:
        k = obj.m_strInstrumentID + "." + obj.m_strExchangeID
        if k == code:
            try: return float(obj.m_dOpenPrice)
            except: return 0.0
    return 0.0

def get_holdings_dict(ContextInfo):
    h = {}
    r = get_trade_detail_data(ContextInfo.accountID, "STOCK", "POSITION")
    for obj in r:
        k = obj.m_strInstrumentID + "." + obj.m_strExchangeID
        v = obj.m_nVolume
        if v > 0: h[k] = v / 100
    return h

def handlebar(ContextInfo):
    d = ContextInfo.barpos
    if d < 62:
        return

    timetag = ContextInfo.get_bar_timetag(d)
    now_date = timetag_to_datetime(timetag, '%Y-%m-%d')

    close_data = ContextInfo.get_history_data(62, '1d', 'close')
    high_data  = ContextInfo.get_history_data(62, '1d', 'high')
    low_data   = ContextInfo.get_history_data(62, '1d', 'low')
    vol_data   = ContextInfo.get_history_data(62, '1d', 'volume')
    open_data  = ContextInfo.get_history_data(62, '1d', 'open')

    # ---- 市场择时：沪深300 > MA60 ----
    market_ok = True
    for idx_c in ['000300.SH', 'SH000300']:
        d_idx = close_data.get(idx_c)
        if d_idx is not None and len(d_idx) >= 62:
            arr = np.array(d_idx, dtype=float)
            ma60 = np.mean(arr[-61:-1])
            market_ok = arr[-1] > ma60
            break

    if not market_ok:
        holdings = get_holdings_dict(ContextInfo)
        for stock, vol in holdings.items():
            if vol <= 0: continue
            cur_p = ContextInfo.get_market_data(['close'], stock_code=[stock])
            if cur_p == -1 or cur_p is None: continue
            cur_p = float(cur_p)
            order_shares(stock, -(vol*100), 'FIX', cur_p, ContextInfo, ContextInfo.accountID)
            for dd in [ContextInfo.entry_date, ContextInfo.entry_price, ContextInfo.peak_close]:
                if stock in dd: del dd[stock]
        return

    # ---- 计算各股票入场条件 ----
    candidates = []
    for stock in ContextInfo.stocks:
        if stock == '600089.SH': continue
        for name in [close_data, high_data, low_data, vol_data, open_data]:
            if stock not in name: continue
        c = close_data.get(stock)
        h = high_data.get(stock)
        l = low_data.get(stock)
        v = vol_data.get(stock)
        o = open_data.get(stock)
        if any(x is None or len(x) < 62 for x in [c, h, l, v, o]):
            continue

        c_arr = np.array(c, dtype=float)
        h_arr = np.array(h, dtype=float)
        l_arr = np.array(l, dtype=float)
        v_arr = np.array(v, dtype=float)
        o_arr = np.array(o, dtype=float)

        cur_close = c_arr[-1]
        cur_open  = o_arr[-1]
        prev_close = c_arr[-2]
        prev_open  = o_arr[-2]
        c_6d = c_arr[-7]  # 6天前的收盘

        ma5  = np.mean(c_arr[-6:-1])
        ma10 = np.mean(c_arr[-11:-1])
        ma20 = np.mean(c_arr[-21:-1])
        ma60 = np.mean(c_arr[-61:-1])
        vol_ma20 = np.mean(v_arr[-21:-1])

        # ATR(14)
        tr_list = []
        for i in range(max(1, len(c_arr)-16), len(c_arr)):
            tr = max(h_arr[i]-l_arr[i], abs(h_arr[i]-c_arr[i-1]), abs(l_arr[i]-c_arr[i-1]))
            tr_list.append(tr)
        if len(tr_list) < 15: continue
        atr14 = np.mean(tr_list[-14:])

        # 5日涨跌幅
        pct_6d = (prev_close / c_6d - 1) * 100

        # 条件1: MA5 > MA10 > MA20
        cond1 = ma5 > ma10 > ma20
        # 条件2: Close > MA20 and MA20 > MA60
        cond2 = cur_close > ma20 > ma60
        # 条件3: 5日涨跌幅范围
        cond3 = -9.5 <= pct_6d <= 10.0
        # 条件4: 前日阴线 OR 今日低于昨日收盘
        cond4 = (prev_close < prev_open) or (cur_close < prev_close)
        # 条件5: 成交量 > 20日均量
        cond5 = v_arr[-1] > vol_ma20
        # 条件7: 相对强度 - 20日收益
        ret_20d = cur_close / c_arr[-21] - 1

        if cond1 and cond2 and cond3 and cond4 and cond5 and ret_20d > 0:
            candidates.append((stock, ret_20d, cur_close, atr14))

    # ---- 按相对强度排序 ----
    candidates.sort(key=lambda x: x[1], reverse=True)

    # ---- 当前持仓 ----
    holdings = get_holdings_dict(ContextInfo)

    # ===== 卖出逻辑 =====
    for stock in list(holdings.keys()):
        vol = float(holdings[stock])
        if vol <= 0: continue

        cur_p = ContextInfo.get_market_data(['close'], stock_code=[stock])
        if cur_p == -1 or cur_p is None: continue
        cur_p = float(cur_p)

        entry_p = ContextInfo.entry_price.get(stock, 0)
        peak_p = ContextInfo.peak_close.get(stock, cur_p)
        entry_d = ContextInfo.entry_date.get(stock)

        # 更新最高价
        if cur_p > peak_p:
            ContextInfo.peak_close[stock] = cur_p
            peak_p = cur_p

        reason = None

        # 检查T+1
        if entry_d == now_date:
            continue

        # 死叉卖出
        if entry_p > 0:
            # 均线死叉检查
            c_s = close_data.get(stock)
            if c_s is not None and len(c_s) >= 11:
                ca = np.array(c_s, dtype=float)
                ma5_now = np.mean(ca[-6:-1])
                ma10_now = np.mean(ca[-11:-1])
                ma5_prev = np.mean(ca[-7:-1])
                ma10_prev = np.mean(ca[-12:-1])
                if ma5_now < ma10_now and ma5_prev >= ma10_prev:
                    reason = "MA_DEATH"

            # 止损 -7%
            if reason is None and cur_p / entry_p <= STOP_LOSS:
                reason = "STOP_LOSS7"

            # ATR跟踪止盈
            if reason is None:
                # 查找该股票的ATR
                atr_val = 0
                for cd, _, _, atr in candidates:
                    if cd == stock:
                        atr_val = atr
                        break
                if atr_val == 0:
                    # 重新计算ATR
                    c_s = close_data.get(stock)
                    h_s = high_data.get(stock)
                    l_s = low_data.get(stock)
                    if c_s and h_s and l_s and len(c_s) >= 16:
                        ca = np.array(c_s, dtype=float)
                        ha = np.array(h_s, dtype=float)
                        la = np.array(l_s, dtype=float)
                        trs = []
                        for i in range(max(1, len(ca)-16), len(ca)):
                            tr = max(ha[i]-la[i], abs(ha[i]-ca[i-1]), abs(la[i]-ca[i-1]))
                            trs.append(tr)
                        if len(trs) >= 14:
                            atr_val = np.mean(trs[-14:])

                if atr_val > 0:
                    trail_stop = peak_p - ATR_MULT * atr_val
                    if cur_p <= trail_stop:
                        reason = "TRAIL_STOP"

            # 时间退出
            if reason is None and entry_d is not None:
                from datetime import datetime
                e = datetime.strptime(entry_d, '%Y-%m-%d')
                n = datetime.strptime(now_date, '%Y-%m-%d')
                if (n - e).days >= MAX_DAYS:
                    reason = "TIME_OUT"

        if reason:
            ret = 0
            if entry_p > 0: ret = (cur_p/entry_p - 1)*100
            order_shares(stock, -(vol*100), 'FIX', cur_p, ContextInfo, ContextInfo.accountID)
            for dd in [ContextInfo.entry_date, ContextInfo.entry_price, ContextInfo.peak_close]:
                if stock in dd: del dd[stock]
            print("%s SELL %s p=%.2f ep=%.2f ret=%.1f%% reason=%s" % (now_date, stock, cur_p, entry_p, ret, reason))

    # ===== 买入逻辑 =====
    current_count = len([k for k in holdings if holdings[k] > 0])
    vacant = MAX_POS - current_count
    if vacant <= 0 or len(candidates) == 0:
        return

    avail = ContextInfo.capital
    for obj in get_trade_detail_data(ContextInfo.accountID, "STOCK", "ACCOUNT"):
        avail = float(obj.m_dAvailable) * 0.95
        break

    # 动态权重：前3名12%, 中间4名10%, 后3名8%
    for rank, (stock, ret_20d, cur_p, _) in enumerate(candidates[:vacant]):
        if stock in holdings and holdings[stock] > 0:
            continue

        if rank < 3:
            weight = 0.12
        elif rank < 7:
            weight = 0.10
        else:
            weight = 0.08

        cap_this = avail * weight
        shares = int(cap_this / (cur_p * 100)) * 100
        if shares >= 100:
            order_shares(stock, shares, 'FIX', cur_p, ContextInfo, ContextInfo.accountID)
            ContextInfo.entry_date[stock] = now_date
            ContextInfo.entry_price[stock] = cur_p
            ContextInfo.peak_close[stock] = cur_p
            print("%s BUY  %s p=%.2f w=%.0f%% ret20d=%.1f%%" % (now_date, stock, cur_p, weight*100, ret_20d*100))
