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
BASE_URL = "https://api.phemex.com"

# E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoy (44)
# ODU2MjBiNC1iZmYzLTQ1OTEtYTIxMS02YzViNzAzYTliMTY (47)
S1 = RAW_SECRET[:44]
S2 = RAW_SECRET[44:]

def check(secret, s_name):
    print(f"\n--- Testing Secret: {s_name} ({len(secret)} chars) ---")
    
    path = "/g-accounts/all-accounts"
    method = "GET"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    expiry = str(int(time.time()) + 60)
    
    # Formula 1: Path + Query + Expiry
    msg1 = f"{path}{query}{expiry}"
    sig1 = hmac.new(secret.encode("utf-8"), msg1.encode("utf-8"), hashlib.sha256).hexdigest()
    h1 = {"x-phemex-access-token": API_KEY, "x-phemex-request-expiry": expiry, "x-phemex-request-signature": sig1}
    r1 = requests.get(f"{BASE_URL}{path}?{query}", headers=h1)
    print(f"Formula: Path + Query + Expiry")
    print(f"Status: {r1.status_code} | Code: {r1.json().get('code')} | Msg: {r1.json().get('msg')}")

    # Formula 2: Method + Path + Query + Expiry
    msg2 = f"{method.upper()}{path}{query}{expiry}"
    sig2 = hmac.new(secret.encode("utf-8"), msg2.encode("utf-8"), hashlib.sha256).hexdigest()
    h2 = {"x-phemex-access-token": API_KEY, "x-phemex-request-expiry": expiry, "x-phemex-request-signature": sig2}
    r2 = requests.get(f"{BASE_URL}{path}?{query}", headers=h2)
    print(f"Formula: Method + Path + Query + Expiry")
    print(f"Status: {r2.status_code} | Code: {r2.json().get('code')} | Msg: {r2.json().get('msg')}")

if __name__ == "__main__":
    check(S1, "S1 (First 44)")
    check(S2, "S2 (Last 47)")
    check(RAW_SECRET, "Full (91)")
