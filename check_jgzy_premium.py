#!/usr/bin/env python3
"""Check A-share institutional block trade premium distribution."""
import json
import urllib.request
import urllib.parse

PROXY = "http://192.168.0.107:1082"
BASE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

proxy_handler = urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY})
opener = urllib.request.build_opener(proxy_handler)

def is_ashare_code(code):
    if not code or len(code) != 6:
        return False
    return code[0] in ('6', '0', '3')

all_premiums = []
date_ranges = [
    ("2026-03-04", "2026-03-18"),
    ("2026-03-18", "2026-04-01"),
    ("2026-04-01", "2026-04-15"),
    ("2026-04-15", "2026-04-30"),
]

for sd, ed in date_ranges:
    for page in [1, 2, 3]:
        params = {
            "reportName": "RPT_DATA_BLOCKTRADE",
            "filter": '(BUYER_NAME="机构专用")(TRADE_DATE>=\'' + sd + "')(TRADE_DATE<'" + ed + "')",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,PREMIUM_RATIO,DEAL_VOLUME,DEAL_AMT,TRADE_DATE",
            "sortTypes": "-1",
            "sortColumns": "TRADE_DATE",
            "pageNumber": str(page),
            "pageSize": "500",
            "source": "WEB",
            "client": "WEB",
            "callback": "j"
        }
        url = BASE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            resp = opener.open(req, timeout=30)
            raw = resp.read().decode("utf-8").strip()
            if raw.startswith("j(") and raw.endswith(");"):
                raw = raw[2:-2]
            d = json.loads(raw)
            for row in d["result"]["data"]:
                if is_ashare_code(row.get("SECURITY_CODE","")):
                    p = row.get("PREMIUM_RATIO")
                    if p is not None:
                        all_premiums.append({
                            "code": row["SECURITY_CODE"],
                            "name": row["SECURITY_NAME_ABBR"],
                            "premium": float(p) * 100,
                            "amt": float(row.get("DEAL_AMT", 0)),
                            "date": (row.get("TRADE_DATE") or "")[:10]
                        })
            if len(d["result"]["data"]) < 500:
                break
        except Exception as e:
            print(f"Error: {e}")
            break

print(f"A-share institutional trades sampled: {len(all_premiums)}")

pos = [r for r in all_premiums if r["premium"] > 0]
neg = [r for r in all_premiums if r["premium"] < 0]
zero = [r for r in all_premiums if r["premium"] == 0]

print(f"  折价(负): {len(neg)} ({len(neg)/len(all_premiums)*100:.0f}%)")
print(f"  溢价(正): {len(pos)} ({len(pos)/len(all_premiums)*100:.0f}%)")
print(f"  平价(0):  {len(zero)}")

# Premium > 0% A shares
gt4 = [r for r in pos if r["premium"] > 4]
between = [r for r in pos if 4 < r["premium"] < 20]

print(f"\nA股 溢价>4%: {len(gt4)} 笔")
print(f"A股 溢价4%~20%: {len(between)} 笔")

if between:
    print(f"\n{'='*60}")
    print(f"{'日期':<12} {'代码':<8} {'名称':<10} {'溢价%':<8} {'金额(万)':<10}")
    print(f"{'='*60}")
    for r in sorted(between, key=lambda x: -x["premium"]):
        print(f"{r['date']:<12} {r['code']:<8} {r['name']:<10} {r['premium']:+>7.2f}% {r['amt']/1e4:>8.0f}")
    print(f"{'='*60}")

if gt4:
    print(f"\n所有溢价>4%的：")
    for r in sorted(gt4, key=lambda x: -x["premium"]):
        amt_str = f"{r['amt']/1e4:.0f}万"
        if r['amt'] >= 1e8:
            amt_str = f"{r['amt']/1e8:.2f}亿"
        print(f"  {r['date']} | {r['code']} {r['name']:8s} | +{r['premium']:.2f}% | {amt_str}")

# All positive premiums summary
if pos:
    print(f"\n=== 全部溢价A股({len(pos)}笔) ===")
    for r in sorted(pos, key=lambda x: -x["premium"]):
        amt_str = f"{r['amt']/1e4:.0f}万"
        if r['amt'] >= 1e8:
            amt_str = f"{r['amt']/1e8:.2f}亿"
        print(f"  {r['date']} | {r['code']} {r['name']:8s} | +{r['premium']:.2f}% | {amt_str}")
else:
    print("\n机构专用买入A股没有任何溢价成交记录")
