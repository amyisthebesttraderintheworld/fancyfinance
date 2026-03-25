import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
API_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

def test_auth(method, path, params=None, use_method_in_sig=True):
    expiry = int(time.time()) + 60
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    
    if use_method_in_sig:
        message = method.upper() + path + query + str(expiry) + body
    else:
        message = path + query + str(expiry) + body
    
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = BASE_URL + path + (("?" + query) if query else "")
    print(f"Testing {method} {path}")
    try:
        resp = requests.request(method, url, headers=headers, timeout=5)
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 20)

# Try a very simple authenticated GET that usually works
test_auth("GET", "/accounts/accountPositions", params={"currency": "BTC"})
test_auth("GET", "/accounts/accountPositions", params={"currency": "USDT"})
test_auth("GET", "/phemex-unified/accounts/all")
