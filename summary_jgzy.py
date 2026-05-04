#!/usr/bin/env python3
import csv
from collections import defaultdict

stocks = defaultdict(lambda: {'count':0, 'total_amt':0, 'avg_premium':[], 'dates':set()})

with open('/home/zp/VT/机构专用A股_折价4_20.csv', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        code = row['代码']
        name = row['名称']
        amt = float(row['成交金额(元)'])
        premium = float(row['折溢价率%'])
        date = row['交易日期']
        
        s = stocks[f'{code} {name}']
        s['count'] += 1
        s['total_amt'] += amt
        s['avg_premium'].append(premium)
        s['dates'].add(date)

total_amt = sum(s['total_amt'] for s in stocks.values())
total_records = sum(s['count'] for s in stocks.values())

print(f'总笔数: {total_records}')
print(f'涉及股票: {len(stocks)} 只')
print(f'总成交额: {total_amt/1e8:.2f} 亿元')
print()

print('=' * 65)
print(f'{"股票":<16} {"笔数":<6} {"成交额(亿)":<12} {"平均折价":<10} {"交易天数":<8}')
print('=' * 65)
for stock, s in sorted(stocks.items(), key=lambda x: -x[1]['total_amt'])[:20]:
    avg_p = sum(s['avg_premium'])/len(s['avg_premium'])
    print(f'{stock:<16} {s["count"]:<6} {s["total_amt"]/1e8:>8.2f}    {avg_p:>+6.2f}%    {len(s["dates"])}天')
print()

print('=' * 55)
print('平均折价最深前10名:')
print('=' * 55)
for stock, s in sorted(stocks.items(), key=lambda x: sum(x[1]['avg_premium'])/len(x[1]['avg_premium']))[:10]:
    avg_p = sum(s['avg_premium'])/len(s['avg_premium'])
    total_yi = s['total_amt']/1e8
    print(f'{stock:<16} {s["count"]:<4}笔  折价:{avg_p:>+7.2f}%  总额:{total_yi:.2f}亿')
print()

print('=' * 55)
print('交易最活跃前10名(天数):')
print('=' * 55)
for stock, s in sorted(stocks.items(), key=lambda x: -len(x[1]['dates']))[:10]:
    avg_p = sum(s['avg_premium'])/len(s['avg_premium'])
    total_yi = s['total_amt']/1e8
    print(f'{stock:<16} {len(s["dates"])}天 {s["count"]}笔  折价:{avg_p:>+7.2f}%  总额:{total_yi:.2f}亿')
