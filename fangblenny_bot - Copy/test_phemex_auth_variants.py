import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
API_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

def test_variants(method, path, params=None):
    expiry = int(time.time()) + 60
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    url = BASE_URL + path + (("?" + query) if query else "")
    
    variants = [
        ("V3 (M+P+Q+E+B)", f"{method}{path}{query}{expiry}{body}"),
        ("V3 (M+P+E+Q+B)", f"{method}{path}{expiry}{query}{body}"),
        ("V3 (E+M+P+Q+B)", f"{expiry}{method}{path}{query}{body}"),
        ("V3 (M+P+?+Q+E+B)", f"{method}{path}?{query}{expiry}{body}"),
        ("V2 (P+Q+E+B)", f"{path}{query}{expiry}{body}"),
        ("V2 (P+?+Q+E+B)", f"{path}?{query}{expiry}{body}"),
    ]
    
    for label, message in variants:
        signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "x-phemex-access-token": API_KEY,
            "x-phemex-request-expiry": str(expiry),
            "x-phemex-request-signature": signature,
            "Content-Type": "application/json",
        }
        resp = requests.request(method, url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                print(f"  [SUCCESS] {label}")
                return
            else:
                print(f"  [FAIL]    {label}: {data.get('code')} {data.get('msg')}")
        else:
            print(f"  [FAIL]    {label}: HTTP {resp.status_code}")

print("Testing variants for /g-accounts/all-accounts?currency=USDT")
test_variants("GET", "/g-accounts/all-accounts", {"currency": "USDT"})
