import requests

base_url = "https://testnet-api.phemex.com"
response = requests.get(f"{base_url}/public/products")
data = response.json()

if 'data' in data:
    if 'perpProductsV2' in data['data']:
        products = data['data']['perpProductsV2']
        print(f"Found {len(products)} perpProductsV2 symbols.")
        usdt_perps = [p['symbol'] for p in products if p.get('settleCurrency') == 'USDT' and p.get('status') == 'Listed']
        print(f"Found {len(usdt_perps)} USDT Perpetual symbols.")
        if usdt_perps:
            print(f"Examples: {usdt_perps[:10]}")
    else:
        print("perpProductsV2 not found in data['data']")
        print("Keys in data['data']:", data['data'].keys())
else:
    print("Unexpected response structure")
