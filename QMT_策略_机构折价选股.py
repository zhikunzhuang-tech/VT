#encoding:gbk
"""
QMT 量化策略 - 机构大宗交易折价选股
基于: 机构专用买入A股 (折价4%~20%) 为股票池
"""

import datetime
import pandas as pd
import numpy as np
import os

class A:
    pass
G = A()


def init(C):
    """策略初始化"""
    G.acct = '680000006619'  # 请替换为你的实际账号
    G.acct_type = 'STOCK'
    G.buy_code = 23 if G.acct_type == 'STOCK' else 33
    G.sell_code = 24 if G.acct_type == 'STOCK' else 34
    
    # ========== 策略参数 ==========
    G.max_positions = 5             # 最大持仓数量
    G.max_position_pct = 0.20       # 单只最大仓位比例
    G.hold_days_limit = 5           # 最大持仓天数
    G.fee_rate = 0.00025            # 手续费万分之2.5
    
    # ========== 加载股票池 ==========
    pool_path = r'D:\VT\stock_pool_qmt.txt'  # 请修改为你的实际路径
    G.stock_pool = []
    try:
        with open(pool_path, 'r') as f:
            for line in f:
                code = line.strip()
                if code:
                    G.stock_pool.append(code)
        print(f'股票池加载完成: {len(G.stock_pool)} 只')
    except Exception as e:
        print(f'股票池加载失败: {e}')
        G.stock_pool = []
    
    # ========== 持仓状态跟踪 ==========
    G.holdings = {}    # code -> {'buy_date': date, 'shares': int}
    G.daily_check = {} # code -> 今日是否已检查过买入
    
    # ========== 初始化 ==========
    now_dt = datetime.datetime.today().strftime('%Y-%m-%d')
    C.run_time('my_handlebar', '1nSecond', '{} 09:30:00'.format(now_dt))
    print('=== 策略初始化完成 ===')
    print('股票池数量:', len(G.stock_pool))
    print('账号:', G.acct)


def my_handlebar(C):
    """每秒触发的主逻辑"""
    now_time = datetime.datetime.now().strftime('%H%M%S')
    
    # 只在交易时段运行
    if now_time < '093000' or now_time > '145700':
        return
    
    # ---- 1. 检查持仓卖出 ----
    check_sell_signals(C)
    
    # ---- 2. 检查买入信号 ----
    # 只在开盘后前15分钟检查买入 (减少盘中波动干扰)
    if '093000' <= now_time <= '094500':
        check_buy_signals(C)


def check_sell_signals(C):
    """检查卖出条件"""
    positions = get_trade_detail_data(G.acct, G.acct_type, 'POSITION')
    if not positions:
        return
    
    now_date = datetime.datetime.now().strftime('%Y-%m-%d')
    
    for pos in positions:
        code = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        vol = pos.m_nCanUseVolume
        if vol <= 0:
            continue
        
        # 获取日线数据
        try:
            download_history_data(code, '1d', '20240101', '20991231')
        except:
            pass
        
        close_data = C.get_market_data_ex(['close'], [code], period='1d', count=8)
        closes = _extract_values(close_data, code)
        
        if closes is None or len(closes) < 6:
            continue
        
        try:
            closes = [float(x) for x in closes if x is not None and str(x) not in ['nan', 'NaN', '']]
        except:
            continue
        
        if len(closes) < 6:
            continue
        
        # ---- 卖出条件1: MA3 < MA5 ----
        ma3 = sum(closes[-3:]) / 3.0
        ma5 = sum(closes[-5:]) / 5.0
        
        if ma3 < ma5:
            print(f'{code} 卖出: MA3={ma3:.2f} < MA5={ma5:.2f}')
            passorder(G.sell_code, 1101, G.acct, code, 14, -1, vol,
                     'MA3下穿MA5卖出', 1, f'{code} 均线死叉卖出', C)
            continue
        
        # ---- 卖出条件2: 持有超过5个交易日 ----
        if code in G.holdings:
            buy_date = G.holdings[code]['buy_date']
            try:
                days_held = (datetime.datetime.strptime(now_date, '%Y-%m-%d') -
                           datetime.datetime.strptime(buy_date, '%Y-%m-%d')).days
                if days_held >= G.hold_days_limit:
                    print(f'{code} 卖出: 持有{days_held}天, 达到上限{G.hold_days_limit}天')
                    passorder(G.sell_code, 1101, G.acct, code, 14, -1, vol,
                             '持有到期卖出', 1, f'{code} 持有到期强制卖出', C)
            except:
                pass


def check_buy_signals(C):
    """检查买入条件"""
    if not G.stock_pool:
        return
    
    # 检查持仓数量上限
    positions = get_trade_detail_data(G.acct, G.acct_type, 'POSITION')
    current_positions = sum(1 for p in positions if p.m_nCanUseVolume > 0) if positions else 0
    
    if current_positions >= G.max_positions:
        return
    
    # 可用资金
    available_cash = get_buying_amount() * (1 - current_positions * G.max_position_pct)
    
    for code in G.stock_pool:
        if current_positions >= G.max_positions:
            break
        
        # 跳过已持仓的股票
        if positions:
            already_hold = any(
                (p.m_strInstrumentID + '.' + p.m_strExchangeID) == code
                for p in positions if p.m_nCanUseVolume > 0
            )
            if already_hold:
                continue
        
        # 获取日线数据 (需要至少10天来计算所有指标)
        try:
            download_history_data(code, '1d', '20240101', '20991231')
        except:
            pass
        
        # 获取OHLC数据
        ohlc_data = C.get_market_data_ex(
            ['close', 'open', 'high', 'low'], [code], period='1d', count=12
        )
        
        if not ohlc_data:
            continue
        
        # ---- 提取数据 ----
        close_val = _extract_values(ohlc_data, code, 'close') if isinstance(ohlc_data, dict) and 'close' in ohlc_data else _extract_values(ohlc_data, code)
        open_val = _extract_values(ohlc_data, code, 'open') if isinstance(ohlc_data, dict) and 'open' in ohlc_data else None
        high_val = _extract_values(ohlc_data, code, 'high') if isinstance(ohlc_data, dict) and 'high' in ohlc_data else None
        low_val = _extract_values(ohlc_data, code, 'low') if isinstance(ohlc_data, dict) and 'low' in ohlc_data else None
        
        # 兼容不同返回格式
        if isinstance(ohlc_data, dict) and code in ohlc_data:
            item = ohlc_data[code]
            if hasattr(item, 'columns') and hasattr(item, 'iloc'):
                try:
                    close_val = item['close'].values.tolist() if 'close' in item.columns else item.iloc[:, 0].values.tolist()
                    if 'open' in item.columns:
                        open_val = item['open'].values.tolist()
                    if 'high' in item.columns:
                        high_val = item['high'].values.tolist()
                    if 'low' in item.columns:
                        low_val = item['low'].values.tolist()
                except:
                    pass
        
        # 数据清洗
        try:
            closes = [float(x) for x in close_val if x is not None and str(x) not in ['nan', 'NaN', '']] if close_val else []
            opens = [float(x) for x in open_val if x is not None and str(x) not in ['nan', 'NaN', '']] if open_val else []
            highs = [float(x) for x in high_val if x is not None and str(x) not in ['nan', 'NaN', '']] if high_val else []
            lows = [float(x) for x in low_val if x is not None and str(x) not in ['nan', 'NaN', '']] if low_val else []
        except:
            continue
        
        # 检查数据完整性
        if len(closes) < 10 or len(opens) < 10 or len(highs) < 10 or len(lows) < 10:
            continue
        
        # =====================
        # 买入条件检查
        # =====================
        
        # ---- 条件1: MA5 > MA10 > MA20 ----
        ma5 = sum(closes[-5:]) / 5.0
        ma10 = sum(closes[-10:]) / 10.0
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20.0
        else:
            continue
        
        if not (ma5 > ma10 > ma20):
            continue
        
        # ---- 条件2: Close > MA20 且 MA20 > MA60 ----
        if len(closes) >= 60:
            ma60 = sum(closes[-60:]) / 60.0
        else:
            continue
        
        if not (closes[-1] > ma20 > ma60):
            continue
        
        # ---- 条件3: 最近5日涨幅在 -9.5% ~ 10% ----
        if len(closes) >= 6:
            pct_5d = (closes[-1] / closes[-6] - 1) * 100
        else:
            continue
        
        if not (-9.5 < pct_5d < 10):
            continue
        
        # ---- 条件4: 前一交易日收阴线 ----
        if not (closes[-2] < opens[-2]):  # close[-1] in QMT is yesterday if we just opened
            continue
        
        # ---- 条件5: TR[-1] > TR[-2] ----
        # TR = MAX(MAX((H-L), ABS(REF(C,1)-H)), ABS(REF(C,1)-L))
        if len(highs) >= 3 and len(lows) >= 3 and len(closes) >= 3:
            tr_1 = max(max(highs[-2] - lows[-2], abs(closes[-3] - highs[-2])), abs(closes[-3] - lows[-2]))
            tr_2 = max(max(highs[-3] - lows[-3], abs(closes[-4] - highs[-3])), abs(closes[-4] - lows[-3]))
        else:
            continue
        
        if not (tr_1 > tr_2):
            continue
        
        # ---- 条件6: 当前价格 < 昨日收盘价（盘中触发买入） ----
        # 用当前最新行情判断
        tick = C.get_full_tick([code])
        if tick and code in tick:
            current_price = tick[code].get('lastPrice', 0)
            if current_price <= 0:
                continue
            if current_price >= closes[-2]:
                continue
        else:
            continue
        
        # =====================
        # 所有条件满足 -> 买入
        # =====================
        
        # 计算买入金额和股数
        buy_amount = available_cash * G.max_position_pct
        buy_price = closes[-2] * 0.995  # 低于昨日收盘价买入
        buy_shares = int(buy_amount / (buy_price * 100)) * 100
        
        if buy_shares <= 0:
            continue
        
        # 记录买入日期
        if code not in G.holdings:
            G.holdings[code] = {}
        G.holdings[code]['buy_date'] = datetime.datetime.now().strftime('%Y-%m-%d')
        
        print(f'{code} 买入: 价格={buy_price:.2f}, 股数={buy_shares}')
        passorder(G.buy_code, 1101, G.acct, code, 14, -1, buy_shares,
                 '机构折价选股买入', 2, f'{code} 策略信号买入', C)


def _extract_values(data, code, field=None):
    """从QMT返回数据中提取值列表"""
    if data is None:
        return None
    
    try:
        if isinstance(data, dict) and code in data:
            item = data[code]
            if hasattr(item, 'columns') and hasattr(item, 'iloc'):
                if field and field in item.columns:
                    return item[field].values.tolist()
                return item.iloc[:, 0].values.tolist()
            elif hasattr(item, 'values') and hasattr(item.values, 'tolist'):
                return item.values.tolist()
            elif hasattr(item, 'tolist'):
                return item.tolist()
            elif isinstance(item, (list, np.ndarray)):
                return list(item)
        
        if isinstance(data, dict) and field and field in data:
            item = data[field]
            if isinstance(item, dict) and code in item:
                sub = item[code]
                if hasattr(sub, 'values') and hasattr(sub.values, 'tolist'):
                    return sub.values.tolist()
                elif hasattr(sub, 'tolist'):
                    return sub.tolist()
    except:
        pass
    
    return None
