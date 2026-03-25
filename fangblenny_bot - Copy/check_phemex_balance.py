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
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"')
API_SECRET = RAW_SECRET[:44]
BASE_URL = "https://api.phemex.com"

def check_balance():
    print(f"--- Phemex Balance Check ---")
    print(f"Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"Secret (truncated): {API_SECRET[:8]}... (Len: {len(API_SECRET)})")
    
    path = "/g-accounts/all-accounts"
    method = "GET"
    params = {"currency": "USDT"}
    
    # 1. Prepare Query String (sorted)
    query = urllib.parse.urlencode(sorted(params.items()))
    
    # 2. Expiry
    try:
        server_time_resp = requests.get("https://api.phemex.com/public/time", timeout=5)
        server_time = server_time_resp.json()['data']['serverTime'] // 1000
        expiry = str(server_time + 60)
    except:
        expiry = str(int(time.time()) + 60)
    
    # 3. Signature Formulas
    formulas = [
        ("Path + Query + Expiry", f"{path}{query}{expiry}"),
        ("Method + Path + Query + Expiry", f"{method.upper()}{path}{query}{expiry}"),
    ]
    
    for label, message in formulas:
        print(f"\nTrying Formula: {label}")
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
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"HTTP Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"API Code: {data.get('code')}")
                print(f"API Msg: {data.get('msg')}")
                
                if data.get("code") == 0:
                    print("SUCCESS!")
                    accounts = data.get("data", [])
                    for acc in accounts:
                        if acc.get("currency") == "USDT":
                            balance = float(acc.get("accountBalanceEv", 0)) / 1e8
                            print(f"USDT Balance: {balance:.2f}")
                    return True
            else:
                print(f"Error Response: {response.text}")
                
        except Exception as e:
            print(f"Request Exception: {e}")
            
    return False

if __name__ == "__main__":
    check_balance()
