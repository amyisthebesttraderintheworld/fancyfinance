import pytest
import os
from common import PhemexClient

@pytest.mark.integration
def test_phemex_client_integration_testnet():
    # Only run if environment variables or config has real keys
    api_key = os.environ.get("PHEMEX_TESTNET_KEY")
    api_secret = os.environ.get("PHEMEX_TESTNET_SECRET")
    
    if not api_key or not api_secret:
        pytest.skip("Phemex testnet credentials not found.")
        
    client = PhemexClient(api_key, api_secret, testnet=True)
    
    try:
        balance = client.get_account()
        assert isinstance(balance, float)
        
        # Test fetching open orders
        orders = client.get_open_orders("BTCUSD")
        assert isinstance(orders, list)
        
        # We don't want to place real orders here automatically without care
        # but a simple test order if desired could be added
        
    except Exception as e:
        pytest.fail(f"Phemex integration test failed: {e}")
