import base64, os, hmac, hashlib, requests, time, urllib.parse
from dotenv import load_dotenv

load_dotenv()
raw = os.getenv('PHEMEX_API_SECRET', '').strip().strip("'").strip('"')
secret = raw[:44]
try:
    key = base64.b64decode(raw[44:] + '==').decode('utf-8')
except:
    key = "COULD-NOT-DECODE"

print(f"Secret: {secret[:5]}... Length: {len(secret)}")
print(f"Key from secret: {key}")

expiry = int(time.time()) + 120
path = '/g-accounts/all-accounts'
method = 'GET'

# Try a few formulas with this key/secret
formulas = [
    ("P+E+B", f"{path}{expiry}"),
    ("M+P+E+B", f"{method}{path}{expiry}"),
]

for name, msg in formulas:
    sig = hmac.new(secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {
        'x-phemex-access-token': key,
        'x-phemex-request-expiry': str(expiry),
        'x-phemex-request-signature': sig,
        'Content-Type': 'application/json'
    }
    r = requests.get('https://api.phemex.com' + path, headers=headers)
    try:
        data = r.json()
        print(f"Formula: {name} | Status: {r.status_code} | Code: {data.get('code')} | Msg: {data.get('msg')}")
    except:
        print(f"Formula: {name} | Status: {r.status_code} | Text: {r.text[:50]}")
