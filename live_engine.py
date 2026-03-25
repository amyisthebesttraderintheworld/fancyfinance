from simulator import Simulator
from common import PhemexClient, Position, calculate_position_size, get_logger
import asyncio
import time

class LiveEngine(Simulator):
    def __init__(self, config, notifier, command_queue):
        super().__init__(config, notifier, command_queue)
        self.logger = get_logger("LiveEngine")
        self.client = None

        if self._runtime_api_ready():
            self._configure_live_client(notify=True)
        else:
            self.logger.warning("Live Engine started without unlocked API credentials. Use /unlock_api to continue.")
            self.notifier.send_message("🔐 Live Engine waiting for `/unlock_api <passphrase>` to load exchange credentials.")

    def _configure_live_client(self, notify: bool = True):
        api_key = self.config['phemex'].get('api_key')
        api_secret = self.config['phemex'].get('api_secret')
        if not api_key or not api_secret or api_key == "YOUR_API_KEY" or api_secret == "YOUR_API_SECRET":
            self.client = None
            return False

        self.client = PhemexClient(api_key, api_secret)
        self.balance = self.client.get_account()
        self.logger.info(f"Live Engine initialized. Balance: {self.balance}")
        if notify:
            self.notifier.send_message(f"🚀 Live Engine Started. Balance: {self.balance:.4f} BTC")
        return True

    def _apply_runtime_api_keys(self, user_id: int, api_key: str, api_secret: str):
        super()._apply_runtime_api_keys(user_id, api_key, api_secret)
        self._configure_live_client(notify=True)

    async def _handle_command(self, cmd):
        c, args, chat_id = cmd
        response = ""
        
        if c == '/shutdown':
            self.stop()
            response = "Engine shutting down..."
        elif c == '/emergency_stop':
            self.is_paused = True
            # Cancel all orders logic would go here
            for s in self.symbols:
                try:
                    # Cancel all (requires API support or loop through open orders)
                    self.client.cancel_order(s, "ALL") # Placeholder if API supports 'ALL' or loop
                    self.logger.warning(f"Emergency stop: Cancelled orders for {s}")
                except:
                    pass
            response = "EMERGENCY STOP TRIGGERED. Trading paused, orders cancelling."
        else:
            await super()._handle_command(cmd)
            return

        self._send_command_response(chat_id, response)

    def _execute_trade(self, symbol, direction, price, qty, is_entry, stop_loss=None, take_profit=None, reason=None):
        # Override simulation logic with real API calls
        if self.client is None:
            self.logger.warning("Live trade requested before API vault was unlocked.")
            self.notifier.send_message("🔐 Unlock the API vault with `/unlock_api <passphrase>` before live trading.")
            return
        
        # Safety Checks
        current_balance = self.client.get_account()
        if current_balance < self.balance * (1 - self.config['risk']['max_daily_loss']):
            self.logger.critical("Max daily loss exceeded. Stopping.")
            self.stop()
            self.notifier.send_message("🚨 Max daily loss exceeded. Engine stopped.")
            return

        side = "Buy" if direction == 'long' else "Sell"
        if not is_entry:
            side = "Sell" if direction == 'long' else "Buy" # Closing
        
        try:
            # Place Order
            # Note: For simplicity, using Market orders or aggressive Limit orders. 
            # Real implementation should manage order lifecycle.
            
            # If closing, close position
            if not is_entry:
                # To close, place opposite order. 
                # Phemex often has specific closePosition API or just reduceOnly order.
                # Here we simply place a reducing order.
                self.client.place_order(symbol, side, qty) 
                self.notifier.send_message(f"🔴 LIVE EXIT: {symbol} {side} Qty: {qty} Reason: {reason}")
                if symbol in self.positions:
                    del self.positions[symbol]
                    
            else:
                # Opening
                self.client.place_order(symbol, side, qty)
                
                # Should ideally place bracket orders (SL/TP) here using API
                # Phemex supports attaching SL/TP to orders or positions
                
                self.positions[symbol] = Position(symbol, direction, price, qty, stop_loss, take_profit, int(time.time()*1000))
                self.notifier.send_message(f"🔵 LIVE ENTRY: {symbol} {side} Qty: {qty}")
                
        except Exception as e:
            self.logger.error(f"Order Execution Failed: {e}")
            self.notifier.send_message(f"⚠️ Order Execution Failed: {e}")
