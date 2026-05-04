#!/usr/bin/env python3
"""Fetch institutional (机构专用) block trades - A shares with premium 4%~20%."""
import json
import csv
import os
import urllib.request
import urllib.parse

PROXY = "http://192.168.0.107:1082"
BASE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

date_chunks = [
    ("2026-03-04", "2026-03-18"),
    ("2026-03-18", "2026-04-01"),
    ("2026-04-01", "2026-04-15"),
    ("2026-04-15", "2026-05-01"),
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
            'filter': f"(BUYER_NAME=\"机构专用\")(TRADE_DATE>='{start_date}')(TRADE_DATE<'{end_date}')",
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

print(f"\nTotal institutional trades: {len(all_data)}")

# Now filter: A-share stocks only + premium 4%~20%
# A-share codes: 6xxxxx (SH), 0xxxxx/3xxxxx (SZ), 301xxx (SZ ChiNext)
# Exclude: 12xxxx (convertible bonds), 159xxx/513xxx (ETF), 508xxx/180xxx (REIT), 920xxx (NEEQ)
def is_ashare_code(code):
    """Check if stock code is A-share."""
    if not code or len(code) != 6:
        return False
    first = code[0]
    # SH A-shares: 6 (600, 601, 603, 605, 688 for STAR)
    # SZ A-shares: 0 (000, 001, 002), 3 (300, 301)
    if first in ('6', '0', '3'):
        return True
    return False

filtered = []
for row in all_data:
    code = row.get('SECURITY_CODE', '')
    if not is_ashare_code(code):
        continue
    
    premium = row.get('PREMIUM_RATIO')
    if premium is None:
        continue
    
    premium_pct = float(premium) * 100
    if -20 < premium_pct < -4:
        row['premium_pct'] = round(premium_pct, 2)
        filtered.append(row)

print(f"A-share with premium 4%~20%: {len(filtered)}")

# Save CSV
csv_path = '/home/zp/VT/机构专用A股_折价4_20.csv'
fieldnames = ['交易日期','代码','名称','收盘价','成交价','折溢价率%','成交量(股)','成交金额(元)','买方','卖方']

with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in filtered:
        writer.writerow({
            '交易日期': (row.get('TRADE_DATE') or '')[:10],
            '代码': row.get('SECURITY_CODE',''),
            '名称': row.get('SECURITY_NAME_ABBR',''),
            '收盘价': row.get('CLOSE_PRICE',''),
            '成交价': row.get('DEAL_PRICE',''),
            '折溢价率%': row['premium_pct'],
            '成交量(股)': row.get('DEAL_VOLUME',''),
            '成交金额(元)': row.get('DEAL_AMT',''),
            '买方': row.get('BUYER_NAME',''),
            '卖方': row.get('SELLER_NAME',''),
        })

fsize = os.path.getsize(csv_path)
print(f"\n=== Done ===")
print(f"File: {csv_path} ({fsize/1024:.0f} KB)")
print()

# Print results
for r in filtered:
    vol = int(r['DEAL_VOLUME']) if r.get('DEAL_VOLUME') else 0
    amt = float(r['DEAL_AMT'])/10000 if r.get('DEAL_AMT') else 0
    print(f"{r['TRADE_DATE'][:10]} | {r['SECURITY_CODE']} {r['SECURITY_NAME_ABBR']:8s} | "
          f"收盘:{r['CLOSE_PRICE']:>8} | 成交:{r['DEAL_PRICE']:>8} | "
          f"折溢价:{r['premium_pct']:>+6.2f}% | 量:{vol:>8,} | 额:{amt:>8.0f}万 | 卖方:{r['SELLER_NAME']}")
