import os, time, hmac, hashlib, requests
from dotenv import load_dotenv
load_dotenv()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
API_SECRET = RAW_SECRET[:44]
BASE_URL = "https://api.phemex.com"

def test_minimal():
    expiry = int(time.time()) + 120
    path = "/g-accounts/all-accounts"
    # Unified Account V3: path + query + expiry + body
    message = f"{path}{expiry}"
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
    }
    r = requests.get(BASE_URL + path, headers=headers)
    print(f"Status: {r.status_code} | Code: {r.json().get('code')} | Msg: {r.json().get('msg')}")

test_minimal()
