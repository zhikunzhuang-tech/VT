#!/usr/bin/env python3
"""并发下载沪深300日线数据"""
import os, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
import akshare as ak
import pandas as pd

CACHE_DIR = '/home/zp/VT/.cache_hs300'
os.makedirs(CACHE_DIR, exist_ok=True)

# 沪深300成分股
import urllib.request
url = "https://www.csindex.com.cn/csindex-home/index/index-detail?indexCode=000300"

hs300_file = '/home/zp/VT/hs300_stocks.txt'
if os.path.exists(hs300_file):
    with open(hs300_file) as f:
        codes = [line.strip() for line in f if line.strip()]
else:
    df = ak.index_stock_cons_csindex('000300')
    codes = [c + '.SH' if c.startswith('6') else c + '.SZ' for c in df['成分券代码'].tolist()]
    with open(hs300_file, 'w') as f:
        for c in codes:
            f.write(c + '\n')

print(f"沪深300成分股: {len(codes)} 只")

def download_one(raw_code):
    """下载单只股票"""
    cache_file = os.path.join(CACHE_DIR, f"{raw_code}.csv")
    if os.path.exists(cache_file):
        return raw_code, 'cached', 0
    
    try:
        df = ak.stock_zh_a_hist(symbol=raw_code, period='daily',
                                start_date='20220101', end_date='20260430', adjust='qfq')
        if df is None or len(df) == 0:
            return raw_code, 'empty', 0
        
        df = df.rename(columns={
            '日期': 'date', '开盘': 'open', '收盘': 'close',
            '最高': 'high', '最低': 'low', '成交量': 'volume',
            '成交额': 'amount'
        })
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df = df[['open', 'close', 'high', 'low', 'volume']]
        df = df.sort_index()
        df.to_csv(cache_file)
        return raw_code, 'ok', len(df)
    except Exception as e:
        return raw_code, f'err:{e}', 0

# 提取6位代码
raw_codes = sorted(set(c.replace('.SH', '').replace('.SZ', '') for c in codes))
already = len([f for f in os.listdir(CACHE_DIR) if f.endswith('.csv')])
print(f"已缓存: {already}, 需下载: {len(raw_codes) - already}")

if already < len(raw_codes):
    to_download = [c for c in raw_codes if not os.path.exists(os.path.join(CACHE_DIR, f'{c}.csv'))]
    print(f"开始并发下载 {len(to_download)} 只...")
    
    success = 0
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(download_one, code): code for code in to_download}
        for i, fut in enumerate(as_completed(futures)):
            code, status, count = fut.result()
            if status == 'ok':
                success += 1
            if (i+1) % 20 == 0:
                print(f"  进度: {i+1}/{len(to_download)}")
    
    print(f"下载完成: 成功{success}只")

total = len([f for f in os.listdir(CACHE_DIR) if f.endswith('.csv')])
print(f"缓存总计: {total} 只股票")
