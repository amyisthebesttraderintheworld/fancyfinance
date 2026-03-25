import base64, os, hmac, hashlib, requests, time, urllib.parse
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
SECRET_STR = RAW_SECRET[:44]
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

def test_auth(secret_bytes, label):
    expiry = int(time.time()) + 120
    path = "/g-accounts/all-accounts"
    method = "GET"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # Try the most likely formula for V3
    message = method.upper() + path + query + str(expiry) + body
    
    signature = hmac.new(secret_bytes, message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = BASE_URL + path + "?" + query
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"[{label}] Status: {resp.status_code} | Code: {resp.json().get('code')} | Msg: {resp.json().get('msg')}")
    except Exception as e:
        print(f"[{label}] Error: {e}")

# Case 1: Raw String (Standard Phemex)
test_auth(SECRET_STR.encode("utf-8"), "Raw String")

# Case 2: Base64 Decoded (Common for other exchanges)
try:
    decoded = base64.b64decode(SECRET_STR)
    test_auth(decoded, "Base64 Decoded")
except Exception as e:
    print(f"Base64 Decode failed: {e}")
