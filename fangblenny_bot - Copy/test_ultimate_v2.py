import hmac, hashlib, time, os, requests, urllib.parse
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
SECRET_44 = RAW_SECRET[:44]
BASE_URL = "https://api.phemex.com"

def run_test(key, secret, label, method, path, params):
    print(f"
--- Testing: {label} ---")
    expiry = str(int(time.time()) + 60)
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    url = f"{BASE_URL}{path}?{query}"

    # Phemex V3 Formulas to try:
    variants = [
        ("Path + Query + Expiry + Body", f"{path}{query}{expiry}{body}"),
        ("Method + Path + Query + Expiry + Body", f"{method.upper()}{path}{query}{expiry}{body}"),
        ("Method + Path + Expiry + Query + Body", f"{method.upper()}{path}{expiry}{query}{body}"),
    ]

    for v_name, message in variants:
        signature = hmac.new(
            secret.encode("utf-8"), 
            message.encode("utf-8"), 
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "x-phemex-access-token": key,
            "x-phemex-request-expiry": expiry,
            "x-phemex-request-signature": signature,
        }
        
        try:
            r = requests.get(url, headers=headers, timeout=10)
            print(f"  [{v_name}] Status: {r.status_code} | Code: {r.json().get('code')} | Msg: {r.json().get('msg')}")
            if r.json().get('code') == 0:
                print("  !!! SUCCESS !!!")
                return True
        except Exception as e:
            print(f"  [{v_name}] Error: {e}")
    return False

if __name__ == "__main__":
    method = "GET"
    path = "/g-accounts/all-accounts"
    params = {"currency": "USDT"}

    print("--- Testing with 44-char Secret Prefix ---")
    run_test(API_KEY, SECRET_44, "44-char Secret", method, path, params)

    print("
--- Testing with Full 91-char Secret ---")
    run_test(API_KEY, RAW_SECRET, "91-char Secret", method, path, params)
