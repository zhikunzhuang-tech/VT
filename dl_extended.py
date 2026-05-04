#!/usr/bin/env python3
"""下载沪深300 2016-2026 日线数据"""
import os, time
from concurrent.futures import ThreadPoolExecutor
import akshare as ak

CACHE = '/home/zp/VT/.cache_hs300'
os.makedirs(CACHE, exist_ok=True)

codes = [l.strip() for l in open('/home/zp/VT/hs300_stocks.txt')]

def dl(raw):
    cf = os.path.join(CACHE, f'{raw}.csv')
    if os.path.exists(cf):
        # Check if we have data from 2016
        df = __import__('pandas').read_csv(cf)
        if len(df) > 1500:
            return raw, 'cached'
    try:
        df = ak.stock_zh_a_hist(symbol=raw, period='daily',
                                start_date='20150101', end_date='20260430', adjust='qfq')
        if df is not None and len(df) > 60:
            df = df.rename(columns={'日期':'date','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume'})
            df['date'] = __import__('pandas').to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            df[['open','close','high','low','volume']].to_csv(cf)
            return raw, 'ok'
    except: pass
    return raw, 'fail'

raw_codes = sorted(set(c.replace('.SH','').replace('.SZ','') for c in codes))
already = len([f for f in os.listdir(CACHE) if f.endswith('.csv')])
need = [c for c in raw_codes if not os.path.exists(os.path.join(CACHE, f'{c}.csv'))]
print(f"已有:{already} 需下载:{len(need)}")

if need:
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(dl, need[:100]))  # download in batches

total = len([f for f in os.listdir(CACHE) if f.endswith('.csv')])
print(f"完成: {total} 只")
