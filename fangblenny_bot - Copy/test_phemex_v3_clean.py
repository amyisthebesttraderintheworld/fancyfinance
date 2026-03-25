import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()
API_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

# 1. method + path + query + str(expiry) + body (what test_auth.py used)
# 2. str(expiry) + method + path + query + body (some v3 examples)
# 3. path + query + str(expiry) + body (others)

def try_one(method, path, params, msg_formula):
    expiry = int(time.time()) + 60
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    
    if msg_formula == "M+P+Q+E+B":
        message = method.upper() + path + query + str(expiry) + body
    elif msg_formula == "E+M+P+Q+B":
        message = str(expiry) + method.upper() + path + query + body
    elif msg_formula == "P+Q+E+B":
        message = path + query + str(expiry) + body
    
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
    }
    url = BASE_URL + path + (("?" + query) if query else "")
    resp = requests.get(url, headers=headers)
    print(f"Formula {msg_formula} | {resp.status_code} | {resp.text[:100]}")

try_one("GET", "/g-accounts/all-accounts", {"currency": "USDT"}, "M+P+Q+E+B")
try_one("GET", "/g-accounts/all-accounts", {"currency": "USDT"}, "E+M+P+Q+B")
try_one("GET", "/g-accounts/all-accounts", {"currency": "USDT"}, "P+Q+E+B")
