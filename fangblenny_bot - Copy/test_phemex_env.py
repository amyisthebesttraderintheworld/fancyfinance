import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_SECRET = RAW_SECRET[:44]

def test_phemex(url, method, path, params=None):
    expiry = int(time.time()) + 120
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    full_url = url + path + (("?" + query) if query else "")
    
    # Formula for V3
    message = f"{method.upper()}{path}{query}{expiry}{body}"
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    
    try:
        resp = requests.request(method, full_url, headers=headers, timeout=5)
        data = None
        if resp.status_code == 200:
            try:
                data = resp.json()
            except:
                data = {"code": 200, "msg": resp.text[:100]}
        else:
            data = {"code": resp.status_code, "msg": resp.text[:100]}
        print(f"URL: {url} | Code: {data.get('code')} | Msg: {data.get('msg')}")
        return data.get('code') == 0
    except Exception as e:
        print(f"URL: {url} | Error: {e}")
    return False

print("Testing Mainnet:")
test_phemex("https://api.phemex.com", "GET", "/g-accounts/all-accounts", {"currency": "USDT"})
print("\nTesting Testnet:")
test_phemex("https://testnet-api.phemex.com", "GET", "/g-accounts/all-accounts", {"currency": "USDT"})
