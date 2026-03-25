import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

# Secret is 91 chars. Let's try splitting it.
# E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoy (44 chars)
# ODU2MjBiNC1iZmYzLTQ1OTEtYTIxMS02YzViNzAzYTliMTY (47 chars)
secret1 = RAW_SECRET[:44]
secret2 = RAW_SECRET[44:]

def test_secret(key, secret, method, path, params=None):
    if not secret: return
    expiry = int(time.time()) + 60
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body = ""
    # M + P + Q + E + B
    message = method.upper() + path + query + str(expiry) + body
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-phemex-access-token": key,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = BASE_URL + path + (("?" + query) if query else "")
    try:
        resp = requests.request(method, url, headers=headers, timeout=5)
        print(f"Secret: {secret[:5]}... | Status: {resp.status_code} | Code: {resp.json().get('code')}")
        return resp.json().get('code') == 0
    except:
        return False

print(f"Total secret length: {len(RAW_SECRET)}")
print("Testing Full Secret:")
test_secret(API_KEY, RAW_SECRET, "GET", "/g-accounts/all-accounts", {"currency": "USDT"})
print("Testing Secret Part 1 (first 44):")
test_secret(API_KEY, secret1, "GET", "/g-accounts/all-accounts", {"currency": "USDT"})
print("Testing Secret Part 2 (last 47):")
test_secret(API_KEY, secret2, "GET", "/g-accounts/all-accounts", {"currency": "USDT"})
