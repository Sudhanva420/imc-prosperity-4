import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
from typing import List
import string
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
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

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

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()

class Trader:
    def __init__(self):
        self.traderData = {}
        self.vev_ema = None
        self.POSITION_LIMITS = {
            "HYDROGEL_PACK": 200,
            "VELVETFRUIT_EXTRACT": 200,
        }

        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]:
            self.POSITION_LIMITS[f"VEV_{k}"] = 300

        self.MAX_TICKS = 1000000

    def norm_cdf(self, x):
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def bs_call(self, S, K, T, sigma):
        if sigma <= 0 or T <= 0: return max(0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.norm_cdf(d1) - K * self.norm_cdf(d2)

    def implied_vol(self, market_price, S, K, T):
        low, high = 0.01, 2.0
        for _ in range(20):
            mid = (low + high) / 2
            if self.bs_call(S, K, T, mid) > market_price: high = mid
            else: low = mid
        return (low + high) / 2

    def get_mid(self, order_depth: OrderDepth):
        if not order_depth.buy_orders or not order_depth.sell_orders: return None
        return (max(order_depth.buy_orders.keys()) + min(order_depth.sell_orders.keys())) / 2

    def delta_one_orders(self, symbol, order_depth, position):
        orders = []
        mid = self.get_mid(order_depth)
        if mid is None: return orders

        alpha = 0.2 
        self.vev_ema = mid if self.vev_ema is None else alpha * mid + (1 - alpha) * self.vev_ema
        
        limit = self.POSITION_LIMITS[symbol]
        best_bid, best_ask = max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

        if mid < self.vev_ema - 2: 
            qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
            if qty > 0: orders.append(Order(symbol, best_ask, qty))
        elif mid > self.vev_ema + 2:
            qty = min(limit + position, order_depth.buy_orders[best_bid])
            if qty > 0: orders.append(Order(symbol, best_bid, -qty))
        return orders

    def option_orders(self, symbol, order_depth, S, T, position):
        orders = []
        mid = self.get_mid(order_depth)
        if mid is None: return orders

        K = int(symbol.split("_")[1])
        limit = self.POSITION_LIMITS[symbol]
        best_bid, best_ask = max(order_depth.buy_orders.keys()), min(order_depth.sell_orders.keys())

        iv = self.implied_vol(mid, S, K, T)
        if symbol not in self.traderData: self.traderData[symbol] = []

        self.traderData[symbol].append(iv)
        if len(self.traderData[symbol]) > 100: self.traderData[symbol].pop(0)

        if len(self.traderData[symbol]) >= 20:
            iv_mean, iv_std = np.mean(self.traderData[symbol]), np.std(self.traderData[symbol])
            z = (iv - iv_mean) / iv_std if iv_std > 0 else 0
            

            if abs(S - K) < 100:
                if z > 1.5: 
                    qty = min(limit + position, order_depth.buy_orders[best_bid])
                    if qty > 0: orders.append(Order(symbol, best_bid, -qty))
                elif z < -1.5: 
                    qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
                    if qty > 0: orders.append(Order(symbol, best_ask, qty))

        if S - K > 200:
            intrinsic_fair = S - K
            if best_ask < intrinsic_fair - 1: # Market price lower than floor value
                qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
                if qty > 0: orders.append(Order(symbol, best_ask, qty))
            elif best_bid > intrinsic_fair + 1:
                qty = min(limit + position, order_depth.buy_orders[best_bid])
                if qty > 0: orders.append(Order(symbol, best_bid, -qty))

        return orders

    def run(self, state: TradingState):
        if state.traderData:
            try: self.traderData = jsonpickle.decode(state.traderData)
            except: self.traderData = {}

        result = {}

        tte_days = 5 - (state.timestamp / 1_000_000)
        current_tte = max(tte_days, 0.01) / 365
        
        S = self.get_mid(state.order_depths.get("VELVETFRUIT_EXTRACT"))

        for sym in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"]:
            if sym in state.order_depths:
                result[sym] = self.delta_one_orders(sym, state.order_depths[sym], state.position.get(sym, 0))

        if S is not None:
            for sym in state.order_depths:
                if "VEV_" in sym:
                    result[sym] = self.option_orders(sym, state.order_depths[sym], S, current_tte, state.position.get(sym, 0))

        trader_data_out = jsonpickle.encode(self.traderData)
        logger.flush(state, result, 0, trader_data_out)
        return result, 0, trader_data_out