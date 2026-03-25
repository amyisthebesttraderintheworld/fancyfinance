import hmac, hashlib, requests, time, urllib.parse, base64
key = '85620b4-bff3-4591-a211-6c5b703a9b16'
secret = 'E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoy'
expiry = int(time.time()) + 120
path = '/g-accounts/all-accounts'
params = {'currency': 'USDT'}
query = urllib.parse.urlencode(sorted(params.items()))
message = f"{path}{query}{expiry}"
sig = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
h = {'x-phemex-access-token': key, 'x-phemex-request-expiry': str(expiry), 'x-phemex-request-signature': sig}
r = requests.get('https://api.phemex.com' + path + '?' + query, headers=h)
print(f"Status: {r.status_code} | Code: {r.json().get('code')} | Msg: {r.json().get('msg')}")
