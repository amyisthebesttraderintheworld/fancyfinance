import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
BASE_URL = "https://api.phemex.com"

def test_auth(secret, label):
    expiry = int(time.time()) + 120
    path = "/g-accounts/all-accounts"
    method = "GET"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # Standard V3 REST formula: method + path + query + expiry + body
    message = f"{method.upper()}{path}{query}{expiry}{body}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL}{path}?{query}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"[{label}] Status: {resp.status_code} | Code: {resp.json().get('code')} | Msg: {resp.json().get('msg')}")
    except Exception as e:
        print(f"[{label}] Error: {e}")

# Try full secret, first 44, last 47
test_auth(RAW_SECRET, "Full 91 chars")
test_auth(RAW_SECRET[:44], "First 44")
test_auth(RAW_SECRET[44:], "Last 47")

# Try Standard V2 formula: path + query + expiry + body (fallback)
def test_auth_v2(secret, label):
    expiry = int(time.time()) + 120
    path = "/accounts/all-accounts"
    query = ""
    body = ""
    message = f"{path}{query}{expiry}{body}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
    }
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"[{label} V2] Status: {resp.status_code} | Code: {resp.json().get('code')} | Msg: {resp.json().get('msg')}")
    except: pass

test_auth_v2(RAW_SECRET, "Full 91 chars")
test_auth_v2(RAW_SECRET[:44], "First 44")
test_auth_v2(RAW_SECRET[44:], "Last 47")
