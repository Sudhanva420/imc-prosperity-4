import json
from typing import Any, List, Optional, Tuple
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
import numpy as np
import math
import jsonpickle

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", "", ""]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [state.timestamp, trader_data, self.compress_listings(state.listings), self.compress_order_depths(state.order_depths),
                self.compress_trades(state.own_trades), self.compress_trades(state.market_trades), state.position, self.compress_observations(state.observations)]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[listing.symbol, listing.product, listing.denomination] for listing in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {symbol: [order_depth.buy_orders, order_depth.sell_orders] for symbol, order_depth in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex] 
                                   for p, o in observations.conversionObservations.items()}
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid] + ("..." if mid < len(value) else "")
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out

logger = Logger()

PEBBLES_BASKET_TARGET = 50000.0
PEBBLES_THRESHOLD = 2.0  # Entry threshold for basket deviation
        
CHOCO_MIN_MOVE = 1 # Minimum profit to target per flip

CHIP_SPREAD_MEAN  = -575.98
CHIP_SPREAD_STD   = 266.28
CHIP_Z_THRESH     = 2.0

class Trader:
    def __init__(self):
        self.traderData = {}
        # Persistent state for Chocolate Shake
        self.last_choco_mid = None
        
        self.PEBBLES = ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"]
        self.MICROCHIPS = ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL"]
        self.SHAKE = "OXYGEN_SHAKE_CHOCOLATE"
        
        # All products in this round have a limit of 10
        self.LIMIT = 10

    def get_mid(self, order_depth: OrderDepth) -> Optional[float]:
        if not order_depth.buy_orders or not order_depth.sell_orders: return None
        return (max(order_depth.buy_orders.keys()) + min(order_depth.sell_orders.keys())) / 2

    def trade_pebbles_basket(self, state: TradingState) -> dict[Symbol, list[Order]]:
        
        orders = {sym: [] for sym in self.PEBBLES}
        mids = {}
        
        for sym in self.PEBBLES:
            depth = state.order_depths.get(sym)
            if depth:
                mids[sym] = self.get_mid(depth)
        
        if len(mids) < 5: return orders # Need all prices for basket arb

        current_sum = sum(mids.values())
        deviation = current_sum - PEBBLES_BASKET_TARGET

        for sym in self.PEBBLES:
            pos = state.position.get(sym, 0)
            depth = state.order_depths[sym]
            
            # If basket is too expensive, we sell the individual components
            if deviation > PEBBLES_THRESHOLD:
                if pos > -self.LIMIT:
                    # Sell at best bid to exit/enter short
                    best_bid = max(depth.buy_orders.keys())
                    orders[sym].append(Order(sym, best_bid, -(self.LIMIT + pos)))
            
            # If basket is too cheap, we buy the individual components
            elif deviation < -PEBBLES_THRESHOLD:
                if pos < self.LIMIT:
                    # Buy at best ask
                    best_ask = min(depth.sell_orders.keys())
                    orders[sym].append(Order(sym, best_ask, self.LIMIT - pos))
        
        return orders

    def trade_microchip_spread(self, state: TradingState) -> dict[Symbol, list[Order]]:
        orders = {"MICROCHIP_CIRCLE": [], "MICROCHIP_OVAL": []}
        c_depth, o_depth = state.order_depths.get("MICROCHIP_CIRCLE"), state.order_depths.get("MICROCHIP_OVAL")
        if not c_depth or not o_depth: return orders
        
        c_mid, o_mid = self.get_mid(c_depth), self.get_mid(o_depth)
        if c_mid is None or o_mid is None: return orders

        spread = c_mid - o_mid
        z_score = (spread - CHIP_SPREAD_MEAN) / CHIP_SPREAD_STD
        
        c_pos, o_pos = state.position.get("MICROCHIP_CIRCLE", 0), state.position.get("MICROCHIP_OVAL", 0)

        # Entry logic: Mean reversion on the spread
        if z_score > CHIP_Z_THRESH: # Spread too wide: Short Circle, Long Oval
            if c_pos > -self.LIMIT: orders["MICROCHIP_CIRCLE"].append(Order("MICROCHIP_CIRCLE", max(c_depth.buy_orders.keys()), -(self.LIMIT + c_pos)))
            if o_pos < self.LIMIT: orders["MICROCHIP_OVAL"].append(Order("MICROCHIP_OVAL", min(o_depth.sell_orders.keys()), self.LIMIT - o_pos))
        elif z_score < -CHIP_Z_THRESH: # Spread too narrow: Long Circle, Short Oval
            if c_pos < self.LIMIT: orders["MICROCHIP_CIRCLE"].append(Order("MICROCHIP_CIRCLE", min(c_depth.sell_orders.keys()), self.LIMIT - c_pos))
            if o_pos > -self.LIMIT: orders["MICROCHIP_OVAL"].append(Order("MICROCHIP_OVAL", max(o_depth.buy_orders.keys()), -(self.LIMIT + o_pos)))
        return orders

    def trade_choco_shake(self, state: TradingState) -> List[Order]:
        orders = []
        depth = state.order_depths.get("OXYGEN_SHAKE_CHOCOLATE")
        if not depth: return orders
        
        mid = self.get_mid(depth)
        if mid is None: return orders
        pos = state.position.get("OXYGEN_SHAKE_CHOCOLATE", 0)
        
        if self.last_choco_mid is not None:
            move = mid - self.last_choco_mid
            # Only trade if move is significant (based on your 72.4% prob finding)
            if abs(move) >= CHOCO_MIN_MOVE:
                if move > 0 and pos > -self.LIMIT: # Move up, expect down
                    orders.append(Order("OXYGEN_SHAKE_CHOCOLATE", int(mid), -(self.LIMIT + pos)))
                elif move < 0 and pos < self.LIMIT: # Move down, expect up
                    orders.append(Order("OXYGEN_SHAKE_CHOCOLATE", int(mid), self.LIMIT - pos))
        
        self.last_choco_mid = mid
        
        return orders

    def run(self, state: TradingState):
        if state.traderData:
            try:
                self.traderData = jsonpickle.decode(state.traderData)
                self.last_choco_mid = self.traderData.get("_last_choco_mid")
            except: self.traderData = {}

        result = {}
        
        # 1. Execute Pebbles Arbitrage
        pebble_orders = self.trade_pebbles_basket(state)
        for sym, ords in pebble_orders.items():
            if ords: result[sym] = ords
            
        # 2. Execute Microchip Pairs
        chip_orders = self.trade_microchip_spread(state)
        for sym, ords in chip_orders.items():
            if ords: result[sym] = ords
            
        # 3. Execute Chocolate Shake Scalping
        shake_orders = self.trade_choco_shake(state)
        if shake_orders:
            result[self.SHAKE] = shake_orders

        self.traderData.update({
            "_last_choco_mid": self.last_choco_mid
        })
        
        trader_data_out = jsonpickle.encode(self.traderData)
        logger.flush(state, result, 0, trader_data_out)
        return result, 0, trader_data_out