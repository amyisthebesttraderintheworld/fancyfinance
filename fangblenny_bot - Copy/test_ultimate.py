import hmac, hashlib, time, os, requests, urllib.parse, base64
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("PHEMEX_API_KEY", "").strip().strip("'").strip('"').strip()
RAW_SECRET = os.getenv("PHEMEX_API_SECRET", "").strip().strip("'").strip('"').strip()
SECRET_44 = RAW_SECRET[:44]
BASE_URL = "https://api.phemex.com"

def test_phemex(key, secret, label):
    print(f"\n--- Testing: {label} ---")
    print(f"Key: {key[:5]}...{key[-5:]} (Len: {len(key)})")
    print(f"Secret: {secret[:5]}...{secret[-5:]} (Len: {len(secret)})")
    
    expiry = str(int(time.time()) + 60)
    path = "/g-accounts/all-accounts"
    params = {"currency": "USDT"}
    query = urllib.parse.urlencode(sorted(params.items()))
    body = ""
    
    # Standard V3 Formula: path + query + expiry + body
    message = f"{path}{query}{expiry}{body}"
    
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
    
    url = f"{BASE_URL}{path}?{query}"
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Code: {data.get('code')} | Msg: {data.get('msg')}")
        if data.get('code') == 0:
            print("!!! SUCCESS !!!")
            return True
    except Exception as e:
        print(f"Error: {e}")
    return False

if __name__ == "__main__":
    # Attempt with RAW 91-char secret
    test_phemex(API_KEY, RAW_SECRET, "Full 91-char Secret")
    
    # Attempt with 44-char prefix
    test_phemex(API_KEY, SECRET_44, "44-char Secret Prefix")
    
    # Maybe the API_KEY itself is different? 
    # Let's try decoding that second half properly
    try:
        # 47 chars + 1 padding = 48 (multiple of 4)
        padded = RAW_SECRET[44:] + "="
        decoded_key = base64.b64decode(padded).decode()
        test_phemex(decoded_key, SECRET_44, f"Decoded Key ({decoded_key}) + 44-char Secret")
    except:
        pass
