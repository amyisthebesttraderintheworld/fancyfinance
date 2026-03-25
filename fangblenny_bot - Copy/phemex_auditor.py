import os
import time
import hmac
import hashlib
import requests
import urllib.parse
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
FULL_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
# Some tests used first 44 chars
TRUNC_SECRET = FULL_SECRET[:44]
BASE_URL = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')

def sign_and_request(method, path, params=None, secret=None):
    if secret is None:
        secret = FULL_SECRET
    
    params = params if params else {}
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    expiry = str(int(time.time()) + 60)
    body = "" # GET has no body
    
    # Formula: Path + Query + Expiry + Body
    message = path + query + expiry + body
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": expiry,
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }
    
    url = f"{BASE_URL}{path}?{query}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def audit():
    print(f"--- Phemex Exchange Audit (Deep Scan) ---")
    print(f"Base URL: {BASE_URL}")
    print(f"Key: {API_KEY[:8]}...")
    
    for label, secret in [("Full Secret (91 chars)", FULL_SECRET), ("Truncated Secret (44 chars)", TRUNC_SECRET)]:
        print(f"\n--- Testing with {label} ---")
        
        # 1. Unified Positions
        print(f"Checking Unified Positions (/g-accounts/accountPositions)...")
        data = sign_and_request("GET", "/g-accounts/accountPositions", {"currency": "USDT"}, secret=secret)
        if data and data.get("code") == 0:
            positions = data.get("data", {}).get("positions", [])
            active = [p for p in positions if float(p.get("sizeRv", 0)) != 0]
            if active:
                print(f"  FOUND {len(active)} active Unified positions:")
                for p in active:
                    print(f"    - {p['symbol']}: {p['side']} {p['sizeRv']} @ {p['avgEntryPriceRp']}")
            else:
                print("  No active Unified positions.")
        else:
            print(f"  Unified check failed: {data.get('code')} - {data.get('msg')}")

        # 2. Contract Positions (Classic)
        print(f"Checking Contract Positions (/accounts/accountPositions)...")
        data = sign_and_request("GET", "/accounts/accountPositions", {"currency": "BTC"}, secret=secret) # USDT usually /g-
        if data and data.get("code") == 0:
             # Handle classic positions
             pass
        else:
            print(f"  Contract check skipped or failed: {data.get('code')}")

        # 3. Active Orders
        print(f"Checking Active Orders (/g-orders/activeList)...")
        # Unified requires symbol? Let's try XAUUSDT as it was in the sim
        data = sign_and_request("GET", "/g-orders/activeList", {"symbol": "XAUUSDT"}, secret=secret)
        if data and data.get("code") == 0:
            rows = data.get("data", {}).get("rows", [])
            if rows:
                print(f"  FOUND {len(rows)} active orders for XAUUSDT.")
            else:
                print("  No active orders for XAUUSDT.")

        # 4. Balance
        print(f"Checking Balance (/g-accounts/all-accounts)...")
        data = sign_and_request("GET", "/g-accounts/all-accounts", {"currency": "USDT"}, secret=secret)
        if data and data.get("code") == 0:
            print("  SUCCESS: Balance retrieved.")
            print(json.dumps(data.get("data"), indent=4))
        else:
            print(f"  Balance check failed: {data.get('code')} - {data.get('msg')}")

if __name__ == "__main__":
    audit()
