import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()
API_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

def test_phemex(method, path, params=None):
    expiry = int(time.time()) + 60
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    url = BASE_URL + path + (("?" + query) if query else "")
    
    # 1. Path + Query + Expiry + Body (V3 REST)
    # 2. Expiry + Method + Path + Query + Body (V3 REST alternate)
    # 3. Method + Path + Query + Expiry + Body (Legacy/Some SDKs)
    variants = [
        ("P+Q+E+B", f"{path}{query}{expiry}{body}"),
        ("E+M+P+Q+B", f"{expiry}{method}{path}{query}{body}"),
        ("M+P+Q+E+B", f"{method}{path}{query}{expiry}{body}"),
    ]
    
    for label, msg in variants:
        sig = hmac.new(API_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
        h = {
            "x-phemex-access-token": API_KEY,
            "x-phemex-request-expiry": str(expiry),
            "x-phemex-request-signature": sig,
            "Content-Type": "application/json",
        }
        r = requests.request(method, url, headers=h)
        print(f"{label}: {r.status_code} | Code: {r.json().get('code')} | Msg: {r.json().get('msg')}")

test_phemex("GET", "/g-accounts/all-accounts", {"currency": "USDT"})
