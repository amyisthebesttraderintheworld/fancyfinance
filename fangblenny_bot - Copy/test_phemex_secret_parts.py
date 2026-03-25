import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

# Secret is 91 chars. E0BoN... (44) + ODU2M... (47)
secret1 = RAW_SECRET[:44]

def test_phemex(secret, label):
    expiry = int(time.time()) + 60
    method = "GET"
    path = "/g-accounts/all-accounts"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # Method + Path + Query + Expiry + Body
    message = method + path + query + str(expiry) + body
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
    }
    url = BASE_URL + path + "?" + query
    resp = requests.get(url, headers=headers)
    print(f"[{label}] {resp.status_code} | {resp.text[:100]}")

test_phemex(RAW_SECRET, "Full Secret")
test_phemex(secret1, "First 44 Only")
