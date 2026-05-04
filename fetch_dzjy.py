#!/usr/bin/env python3
"""Fetch block trading data from East Money for the last 2 months."""
import json
import csv
import os
import urllib.request
import urllib.parse

PROXY = "http://192.168.0.107:1082"
BASE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# Split into weekly chunks so each fits within API's 12-page limit
date_chunks = [
    ("2026-03-04", "2026-03-11"),
    ("2026-03-11", "2026-03-18"),
    ("2026-03-18", "2026-03-25"),
    ("2026-03-25", "2026-04-01"),
    ("2026-04-01", "2026-04-08"),
    ("2026-04-08", "2026-04-15"),
    ("2026-04-15", "2026-04-22"),
    ("2026-04-22", "2026-04-30"),
]

COLUMNS = "TRADE_DATE,SECURITY_CODE,SECURITY_NAME_ABBR,CLOSE_PRICE,DEAL_PRICE,PREMIUM_RATIO,DEAL_VOLUME,DEAL_AMT,BUYER_NAME,SELLER_NAME"

all_data = []

proxy_handler = urllib.request.ProxyHandler({
    'http': PROXY,
    'https': PROXY
})
opener = urllib.request.build_opener(proxy_handler)

for start_date, end_date in date_chunks:
    print(f"  {start_date} ~ {end_date}...", end=" ", flush=True)
    page = 1
    chunk_count = 0
    while True:
        params = {
            'reportName': 'RPT_DATA_BLOCKTRADE',
            'filter': f"(TRADE_DATE>='{start_date}')(TRADE_DATE<'{end_date}')",
            'columns': COLUMNS,
            'sortTypes': '-1',
            'sortColumns': 'TRADE_DATE',
            'pageNumber': str(page),
            'pageSize': '500',
            'source': 'WEB',
            'client': 'WEB',
            'callback': 'j'
        }
        url = BASE_URL + '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        try:
            resp = opener.open(req, timeout=30)
            raw = resp.read().decode('utf-8')
            # Strip JSONP wrapper
            raw = raw.strip()
            if raw.startswith('j(') and raw.endswith(');'):
                raw = raw[2:-2]
            d = json.loads(raw)
            records = d['result']['data']
            if not records:
                break
            all_data.extend(records)
            chunk_count += len(records)
            if len(records) < 500:
                break
            page += 1
        except Exception as e:
            print(f"Error at page {page}: {e}")
            break
    print(f"{chunk_count} records")

# Save CSV
csv_path = '/home/zp/VT/dazongjiaoyi_2026_0303_0430.csv'
fieldnames = ['交易日期','代码','名称','收盘价','成交价','折溢价率%','成交量(股)','成交金额(元)',
              '买方','卖方']

with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in all_data:
        premium = row.get('PREMIUM_RATIO')
        if premium is not None:
            premium = round(float(premium) * 100, 2)
        writer.writerow({
            '交易日期': (row.get('TRADE_DATE') or '')[:10],
            '代码': row.get('SECURITY_CODE',''),
            '名称': row.get('SECURITY_NAME_ABBR',''),
            '收盘价': row.get('CLOSE_PRICE',''),
            '成交价': row.get('DEAL_PRICE',''),
            '折溢价率%': premium,
            '成交量(股)': row.get('DEAL_VOLUME',''),
            '成交金额(元)': row.get('DEAL_AMT',''),
            '买方': row.get('BUYER_NAME',''),
            '卖方': row.get('SELLER_NAME',''),
        })

fsize = os.path.getsize(csv_path)
print(f"\n=== Done ===")
print(f"Records: {len(all_data)}")
print(f"Unique stocks: {len(set(r['SECURITY_CODE'] for r in all_data))}")
print(f"Date range: {all_data[-1]['TRADE_DATE'][:10]} ~ {all_data[0]['TRADE_DATE'][:10]}")
print(f"File: {csv_path} ({fsize/1024:.0f} KB)")
