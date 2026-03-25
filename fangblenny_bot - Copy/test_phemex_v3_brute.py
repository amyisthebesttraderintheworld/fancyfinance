import hmac, hashlib, requests, time, urllib.parse, base64

key = 'a560c484-a52d-4285-8fa4-df5eb6b70c2b'
raw_secret = 'E0BoN9FM3nR3hyjTmgzkWcrwgH1caXerb8K7VIkzyXoyODU2MjBiNC1iZmYzLTQ1OTEtYTIxMS02YzViNzAzYTliMTY'
secret1 = raw_secret[:44]
secret2 = raw_secret[44:]
decoded2 = '85620b4-bff3-4591-a211-6c5b703a9b16'

path = '/g-accounts/all-accounts'
params = {'currency': 'USDT'}
query = urllib.parse.urlencode(sorted(params.items()))
expiry = int(time.time()) + 120

def test(s, msg_formula):
    sig_msg = msg_formula.replace('P', path).replace('Q', query).replace('E', str(expiry)).replace('M', 'GET').replace('B', '')
    signature = hmac.new(s.encode('utf-8'), sig_msg.encode('utf-8'), hashlib.sha256).hexdigest()
    h = {'x-phemex-access-token': key, 'x-phemex-request-expiry': str(expiry), 'x-phemex-request-signature': signature}
    r = requests.get('https://api.phemex.com' + path + '?' + query, headers=h)
    return r.status_code, r.json().get('code'), r.json().get('msg'), sig_msg

secrets = [('S1', secret1), ('S2', secret2), ('Dec2', decoded2), ('Full', raw_secret)]
formulas = ['PQE', 'M PQ E', 'E M PQ', 'P Q E B', 'MPQEB'] # M P Q E B

for s_name, s_val in secrets:
    for f in formulas:
        code, biz_code, msg, sig_msg = test(s_val, f.replace(' ', ''))
        print(f"Sec: {s_name} | Form: {f:10} | Res: {code} | Biz: {biz_code} | Msg: {msg}")
        if biz_code == 0:
            print(f"SUCCESS with {s_name} and {f}! Message: {sig_msg}")
            exit(0)
