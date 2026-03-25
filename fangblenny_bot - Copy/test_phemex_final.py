import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_SECRET = RAW_SECRET[:44]
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

def test_phemex(method, path, params=None):
    expiry = int(time.time()) + 120
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    url = BASE_URL + path + (("?" + query) if query else "")
    
    # Formulas to try
    formulas = [
        ("P+Q+E+B", f"{path}{query}{expiry}{body}"),
        ("M+P+Q+E+B", f"{method.upper()}{path}{query}{expiry}{body}"),
    ]
    
    for f_name, message in formulas:
        signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        for h_name in ["x-phemex-request-signature", "x-phemex-signature"]:
            headers = {
                "x-phemex-access-token": API_KEY,
                "x-phemex-request-expiry": str(expiry),
                h_name: signature,
                "Content-Type": "application/json",
            }
            
            try:
                resp = requests.request(method, url, headers=headers, timeout=5)
                data = resp.json() if resp.status_code == 200 else {"code": resp.status_code, "msg": resp.text[:50]}
                print(f"Formula: {f_name:12} | Header: {h_name:30} | Code: {data.get('code')} | Msg: {data.get('msg')}")
                if data.get('code') == 0:
                    print("SUCCESS!")
                    return True
            except Exception as e:
                print(f"Error: {e}")
    return False

print(f"Testing against {BASE_URL}")
test_phemex("GET", "/g-accounts/all-accounts", {"currency": "USDT"})
