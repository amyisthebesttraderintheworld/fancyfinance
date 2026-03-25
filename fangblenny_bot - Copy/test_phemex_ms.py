import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_SECRET = RAW_SECRET[:44]
BASE_URL = "https://api.phemex.com"

def test_phemex(method, path, params=None):
    # Try with MILLISECONDS for expiry
    expiry = int(time.time() * 1000) + 60000 # 1 minute from now
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    url = BASE_URL + path + (("?" + query) if query else "")
    
    # Try various formulas with milliseconds
    formulas = [
        ("M+P+Q+E+B", f"{method.upper()}{path}{query}{expiry}{body}"),
        ("P+Q+E+B", f"{path}{query}{expiry}{body}"),
    ]
    
    for f_name, message in formulas:
        signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "x-phemex-access-token": API_KEY,
            "x-phemex-request-expiry": str(expiry),
            "x-phemex-request-signature": signature,
            "Content-Type": "application/json",
        }
        
        try:
            resp = requests.request(method, url, headers=headers, timeout=5)
            data = resp.json() if resp.status_code == 200 else {"code": resp.status_code, "msg": resp.text[:100]}
            print(f"Formula: {f_name:12} | Expiry: {expiry} | Code: {data.get('code')} | Msg: {data.get('msg')}")
            if data.get('code') == 0:
                print("SUCCESS!")
                return True
        except Exception as e:
            print(f"Error: {e}")
    return False

print(f"Testing with MILLISECONDS against {BASE_URL}")
test_phemex("GET", "/g-accounts/all-accounts", {"currency": "USDT"})
