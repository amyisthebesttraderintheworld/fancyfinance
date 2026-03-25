import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://api.phemex.com"

def test_phemex(key, secret, label):
    expiry = int(time.time()) + 120
    path = "/g-accounts/all-accounts"
    method = "GET"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # method + path + query + expiry + body
    message = f"{method.upper()}{path}{query}{expiry}{body}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": key,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL}{path}?{query}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"[{label}] Key: {key[:8]}... | Secret: {secret[:8]}... | Status: {resp.status_code} | Code: {resp.json().get('code')} | Msg: {resp.json().get('msg')}")
    except Exception as e:
        print(f"[{label}] Error: {e}")

RAW_SECRET = "E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoyODU2MjBiNC1iZmYzLTQ1OTEtYTIxMS02YzViNzAzYTliMTY"
ORIG_KEY = "a560c484-a52d-4285-8fa4-df5eb6b70c2b"

# Variant 1: Key from .env, Secret is first 44 of RAW_SECRET
test_phemex(ORIG_KEY, RAW_SECRET[:44], "Key=Env, Secret=Part1")

# Variant 2: Key from .env, Secret is last 47 of RAW_SECRET
test_phemex(ORIG_KEY, RAW_SECRET[44:], "Key=Env, Secret=Part2")

# Variant 3: Key is last 47 of RAW_SECRET, Secret is first 44 of RAW_SECRET
test_phemex(RAW_SECRET[44:], RAW_SECRET[:44], "Key=Part2, Secret=Part1")

# Variant 4: Key is first 44 of RAW_SECRET, Secret is last 47 of RAW_SECRET
test_phemex(RAW_SECRET[:44], RAW_SECRET[44:], "Key=Part1, Secret=Part2")

# Variant 5: Key from .env, Secret is FULL RAW_SECRET
test_phemex(ORIG_KEY, RAW_SECRET, "Key=Env, Secret=Full")
