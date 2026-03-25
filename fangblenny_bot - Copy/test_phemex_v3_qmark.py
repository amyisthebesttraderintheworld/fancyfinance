import hmac, hashlib, requests, time, urllib.parse
# 1. Get server time
r_time = requests.get('https://api.phemex.com/public/time')
server_time = r_time.json()['data']['serverTime'] // 1000

key = 'a560c484-a52d-4285-8fa4-df5eb6b70c2b'
secret = 'E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoy'
expiry = server_time + 60
path = '/g-accounts/all-accounts'
params = {'currency': 'USDT'}
query = urllib.parse.urlencode(sorted(params.items()))
# Try Variant: path + ? + query + expiry
message = f"{path}?{query}{expiry}"
sig = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
h = {'x-phemex-access-token': key, 'x-phemex-request-expiry': str(expiry), 'x-phemex-request-signature': sig}
r = requests.get('https://api.phemex.com' + path + '?' + query, headers=h)
print(f"Status: {r.status_code} | Code: {r.json().get('code')} | Msg: {r.json().get('msg')}")
