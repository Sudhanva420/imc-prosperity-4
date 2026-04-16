import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
from typing import List
import math
import numpy as np
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
    
    ACO = "ASH_COATED_OSMIUM"
    IPR = "INTARIAN_PEPPER_ROOT"
    
    
class Trader:
    
    def __init__(self):
        self.POSITION_LIMITS = {
            Product.ACO: 80,
            Product.IPR: 80,
        }
        
    def aco_orders(self, order_depth: OrderDepth, position: int, position_limit: int) -> List[Order]:
        orders: List[Order] = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return []

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = (best_bid + best_ask) / 2

        if not isinstance(self.aco_prices, list):
            self.aco_prices = []

        self.aco_prices.append(mid_price)
        if len(self.aco_prices) > 50:
            self.aco_prices = self.aco_prices[-50:]

        # Keep these as scalar diagnostics for later strategy changes.
        recent = np.array(self.aco_prices[-50:], dtype=float)
        recent_mean = float(np.mean(recent))
        recent_std = float(np.std(recent)) if len(recent) > 1 else 0.0
            
        z_mid = (mid_price - recent_mean) / recent_std if recent_std > 0 else 0.0
        logger.print(f"ACO stats | n={len(self.aco_prices)} mean50={recent_mean:.2f} std50={recent_std:.4f} z={z_mid:.3f}")

        
        reversion_strength = 0.5
        #fair_value = mid_price + (reversion_strength * (recent_mean - mid_price))

        buy_capacity = position_limit - position
        sell_capacity = position_limit + position  

        sell_price = int(round(mid_price + (2.5*recent_std)))
        buy_price = int(round(mid_price - (2.5*recent_std)))
         
        orders.append(Order(Product.ACO, sell_price, -sell_capacity))

         
        orders.append(Order(Product.ACO, buy_price, buy_capacity))

        return orders
    
    def ipr_orders(self, order_depth: OrderDepth, position: int, position_limit: int) -> List[Order]:
        
        orders: List[Order] = []
        
        if order_depth.buy_orders and order_depth.sell_orders:
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
        else:
            return []

        slope = 0.101

        projected_mid = mid_price + (slope * 50)
        
        
        logger.print(spread, mid_price, projected_mid)
        
        if position < position_limit:

            buy_price = int(round(projected_mid - 1)) 
            orders.append(Order(Product.IPR, buy_price, position_limit - position))

        if position > 0:

            sell_price = int(round(projected_mid + 2))
            orders.append(Order(Product.IPR, sell_price, -position))

        return orders
    
    def run(self, state: TradingState):
        if state.traderData:
            try:
                data = jsonpickle.decode(state.traderData)
                loaded_prices = data.get("aco_prices", [])
                self.aco_prices = loaded_prices if isinstance(loaded_prices, list) else []
                
            except Exception:
                self.aco_prices = []
        else:
            self.aco_prices = []

        result = {}
        if Product.ACO in state.order_depths:
            result[Product.ACO] = self.aco_orders(state.order_depths[Product.ACO], state.position.get(Product.ACO, 0), 80)
        
        if Product.IPR in state.order_depths:
            result[Product.IPR] = self.ipr_orders(state.order_depths[Product.IPR], state.position.get(Product.IPR, 0), 80)
        
        # FIX: Uniform variable name and data packing
        final_trader_data = jsonpickle.encode({
            "aco_prices": getattr(self, 'aco_prices', None),
        })

        conversions = 0
        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data
