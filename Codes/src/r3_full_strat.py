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

class Product:
    
    VFE = "VELVETFRUIT_EXTRACT"
    HP = "HYDROGEL_PACK"

class Trader:
    def __init__(self):
        self.traderData = {}
        self.vfe_ma = None
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

    def delta_one_hyd(self, symbol, order_depth, position):
        
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        mid = (best_bid + best_ask) / 2

        EDGE = 7

        bid_price = int(round(mid - EDGE))
        ask_price = int(round(mid + EDGE))

        position_limit = self.POSITION_LIMITS[symbol]
        
        buy_capacity = position_limit - position
        sell_capacity = position_limit + position

        if buy_capacity > 0:
            orders.append(Order(symbol, bid_price, buy_capacity))

        if sell_capacity > 0:
            orders.append(Order(symbol, ask_price, -sell_capacity))

        return orders

    def delta_one_vfe(self, symbol, order_depth, position):
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        best_bid_vol = order_depth.buy_orders[best_bid]
        best_ask_vol = abs(order_depth.sell_orders[best_ask])

        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid

        limit = self.POSITION_LIMITS[symbol]

        # Store mids for simple return signal
        key = symbol + "_mids"
        if key not in self.traderData:
            self.traderData[key] = []

        self.traderData[key].append(mid)
        logger.print(self.traderData[key])
        if len(self.traderData[key]) > 50:
            self.traderData[key].pop(0)

        mids = self.traderData[key]
        prev_mid = mids[-2] if len(mids) >= 2 else mid
        ret = mid - prev_mid

        # -------------------------
        # Parameters
        # -------------------------
        EDGE = 1
        BASE_SIZE = 100
        MAX_TAKE_SIZE = 40
        INVENTORY_SKEW = 5.0

        # Avoid very tight / dangerous spreads
        if spread < 4:
            return orders

        # -------------------------
        # Inventory skew
        # -------------------------
        inventory_ratio = position / limit
        skew = inventory_ratio * INVENTORY_SKEW

        bid_price = int(round(mid - EDGE - skew))
        ask_price = int(round(mid + EDGE - skew))

        # Do not cross accidentally
        bid_price = min(bid_price, best_ask - 1)
        ask_price = max(ask_price, best_bid + 1)

        # Dynamic size
        if abs(position) < 50:
            quote_size = BASE_SIZE
        elif abs(position) < 120:
            quote_size = BASE_SIZE // 2
        else:
            quote_size = BASE_SIZE // 4

        buy_qty = min(quote_size, limit - position)
        sell_qty = min(quote_size, limit + position)

        # -------------------------
        # Passive market making
        # -------------------------
        if buy_qty > 0:
            orders.append(Order(symbol, bid_price, buy_qty))

        if sell_qty > 0:
            orders.append(Order(symbol, ask_price, -sell_qty))

        # -------------------------
        # Rare big-move reversal taking
        # -------------------------
        if ret >= 3:
            qty = min(MAX_TAKE_SIZE, limit + position, best_bid_vol)
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        elif ret <= -3:
            qty = min(MAX_TAKE_SIZE, limit - position, best_ask_vol)
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        # -------------------------
        # Emergency inventory reduction
        # -------------------------
        if position > 150:
            qty = min(position - 100, best_bid_vol)
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        elif position < -150:
            qty = min(-position - 100, best_ask_vol)
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        return orders

    def option_orders(self, symbol, order_depth, S, T, position, mode="AUTO"):
        orders = []
        mid = self.get_mid(order_depth)
        if mid is None: return orders

        K = int(symbol.split("_")[1])
        limit = self.POSITION_LIMITS[symbol]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        moneyness = S - K

        # --- MODE SELECTION ---
        # AUTO will assign the regime based on moneyness automatically
        if mode == "AUTO":
            if moneyness > 200:   regime = "ITM_PROXY"
            elif abs(moneyness) < 100: regime = "ATM_VOL"
            else: regime = "OTM_SMILE"
        else:
            regime = mode

        # 1. ITM_PROXY: Trade it like the underlying stock
        if regime == "ITM_PROXY":
            # Since Delta is ~1, we just look for mispricing vs Intrinsic
            intrinsic_fair = S - K
            if best_ask < intrinsic_fair - 1: # Too cheap
                qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
                if qty > 0: orders.append(Order(symbol, best_ask, qty))
            elif best_bid > intrinsic_fair + 1: # Too expensive
                qty = min(limit + position, order_depth.buy_orders[best_bid])
                if qty > 0: orders.append(Order(symbol, best_bid, -qty))

        # 2. ATM_VOL: Standard IV Mean Reversion
        elif regime == "ATM_VOL":
            iv = self.implied_vol(mid, S, K, T)
            if symbol not in self.traderData: self.traderData[symbol] = []
            self.traderData[symbol].append(iv)
            if len(self.traderData[symbol]) > 100: self.traderData[symbol].pop(0)

            if len(self.traderData[symbol]) >= 20:
                iv_mean = np.mean(self.traderData[symbol])
                iv_std = np.std(self.traderData[symbol])
                z = (iv - iv_mean) / iv_std if iv_std > 0 else 0

                if z > 1.8: # Sell overpriced vol
                    qty = min(limit + position, order_depth.buy_orders[best_bid])
                    if qty > 0: orders.append(Order(symbol, best_bid, -qty))
                elif z < -1.8: # Buy cheap vol
                    qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
                    if qty > 0: orders.append(Order(symbol, best_ask, qty))

        # 3. OTM_SMILE: Relative Value / Skew Trading
        elif regime == "OTM_SMILE":
            # Compare current IV to the 'Anchor' (ATM) IV
            # Note: You'll need to ensure VEV_5200 is processed first in run() 
            # to have its current IV available in traderData.
            anchor_iv_list = self.traderData.get("VEV_5200", [])
            if anchor_iv_list:
                current_iv = self.implied_vol(mid, S, K, T)
                atm_iv = anchor_iv_list[-1]
                
                # If the 'Smile' gets too steep (OTM IV is way higher than ATM)
                # Spread is normally ~0.15 based on your data (0.44 - 0.29)
                skew = current_iv - atm_iv
                if skew > 0.25: # Skew is too high, sell the OTM "fear"
                    qty = min(limit + position, order_depth.buy_orders[best_bid])
                    if qty > 0: orders.append(Order(symbol, best_bid, -qty))
                elif skew < 0.05: # Skew is too flat, buy the OTM "lottery ticket"
                    qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
                    if qty > 0: orders.append(Order(symbol, best_ask, qty))

        return orders

    def run(self, state: TradingState):
        if state.traderData:
            try: self.traderData = jsonpickle.decode(state.traderData)
            except: self.traderData = {}

        result = {}

        tte_days = 5 - (state.timestamp / 1_000_000)
        current_tte = max(tte_days, 0.01) / 365
        
        S = self.get_mid(state.order_depths.get("VELVETFRUIT_EXTRACT"))

        
        if Product.VFE in state.order_depths:
           result[Product.VFE] = self.delta_one_vfe(Product.VFE, state.order_depths[Product.VFE], state.position.get(Product.VFE, 0))
        
        #if Product.HP in state.order_depths:
        #  result[Product.HP] = self.delta_one_hyd(Product.HP, state.order_depths[Product.HP], state.position.get(Product.HP, 0))
        
        # In your run() loop:
        '''
        for sym in state.order_depths:
            if "VEV_" in sym:
                pos = state.position.get(sym, 0)
                
                if sym == "VEV_4500":
                    result[sym] = self.option_orders(sym, state.order_depths[sym], S, current_tte, pos, mode="ITM_PROXY")
                elif sym == "VEV_5200":
                    result[sym] = self.option_orders(sym, state.order_depths[sym], S, current_tte, pos, mode="ATM_VOL")
                elif sym == "VEV_6000":
                    result[sym] = self.option_orders(sym, state.order_depths[sym], S, current_tte, pos, mode="OTM_SMILE")
        '''
                    
        trader_data_out = jsonpickle.encode(self.traderData)
        logger.flush(state, result, 0, trader_data_out)
        return result, 0, trader_data_out