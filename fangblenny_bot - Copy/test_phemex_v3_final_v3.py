import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

# The key found in test_phemex_v3_dec.py
DECODED_KEY = '85620b4-bff3-4591-a211-6c5b703a9b16'
# The secret prefix in .env
API_SECRET = 'E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoy'
BASE_URL = "https://api.phemex.com"

def test_phemex(key, secret, label):
    print(f"--- Testing {label} (Key: {key}) ---")
    expiry = int(time.time()) + 60
    path = "/g-accounts/all-accounts"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # Formula: Path + Query + Expiry + Body
    message = f"{path}{query}{expiry}{body}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": key,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL}{path}?{query}"
    
    r = requests.get(url, headers=headers)
    print(f"Status: {r.status_code}")
    try:
        data = r.json()
        print(f"Code: {data.get('code')} | Msg: {data.get('msg')}")
    except:
        print(f"Body: {r.text[:200]}")
    print("-" * 40)

if __name__ == "__main__":
    test_phemex(DECODED_KEY, API_SECRET, "Decoded Key from Secret")
