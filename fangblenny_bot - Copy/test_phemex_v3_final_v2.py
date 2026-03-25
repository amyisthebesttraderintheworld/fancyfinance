import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
BASE_URL = "https://api.phemex.com"

def test_phemex(secret, label):
    print(f"--- Testing {label} (Secret Len: {len(secret)}) ---")
    expiry = int(time.time()) + 60
    path = "/g-accounts/all-accounts"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # Formula: Path + Query + Expiry + Body
    message = f"{path}{query}{expiry}{body}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
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
    test_phemex(RAW_SECRET[:44], "Truncated 44-char")
    test_phemex(RAW_SECRET, "Full 91-char")
