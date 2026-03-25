import os
import time
import hmac
import hashlib
import requests
import urllib.parse
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Configuration
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"')
API_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"')
BASE_URL = "https://api.phemex.com"

def check_balance():
    print(f"--- Phemex Balance Check (Full 91-char Secret) ---")
    
    path = "/g-accounts/all-accounts"
    method = "GET"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    
    expiry = str(int(time.time()) + 60)
    
    # Formula: Method + Path + Query + Expiry
    message = f"{method.upper()}{path}{query}{expiry}"
    print(f"Message: {message}")
    
    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": expiry,
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json"
    }
    
    url = f"{BASE_URL}{path}?{query}"
    
    response = requests.get(url, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    check_balance()
