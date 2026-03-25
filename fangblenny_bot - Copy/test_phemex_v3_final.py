import os, time, hmac, hashlib, requests, urllib.parse
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_SECRET = RAW_SECRET[:44]
BASE_URL = "https://api.phemex.com"

def test_phemex_v3_final():
    expiry = int(time.time()) + 60
    path = "/g-accounts/all-accounts"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # EXACT formula from api_ref.txt: Path + Query + Expiry + Body
    message = f"{path}{query}{expiry}{body}"
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL}{path}?{query}"
    
    print(f"Testing URL: {url}")
    print(f"Message: {message}")
    
    r = requests.get(url, headers=headers)
    print(f"Status: {r.status_code}")
    try:
        data = r.json()
        print(f"Code: {data.get('code')} | Msg: {data.get('msg')}")
        if data.get('code') == 0:
            print("SUCCESS: Balance found" if "data" in data else "SUCCESS: Empty data")
    except:
        print(f"Body: {r.text[:200]}")

if __name__ == "__main__":
    test_phemex_v3_final()
