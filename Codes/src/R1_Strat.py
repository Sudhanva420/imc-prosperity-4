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
    
    ACO = "ASH_COATED_OSMIUM"
    IPR = "INTARIAN_PEPPER_ROOT"
    
   
class Trader:
    
    def __init__(self):
        
        self.traderData = {}

        self.ipr_spreads = []
        
        self.POSITION_LIMITS = {
            Product.ACO: 80,
            Product.IPR: 80,
        }

        self.aco_prices=[]

        
    def aco_orders(self, order_depth: OrderDepth, fair_value: int, position: int, position_limit: int) -> List[Order]:
        
        orders: List[Order] = []

        logger.print(f"Position: {position}")


        if not order_depth.buy_orders and not order_depth.sell_orders:
            logger.print("No order book on both sides")
            return []
        
        if order_depth.buy_orders and not order_depth.sell_orders:
            best_bid = max(order_depth.buy_orders.keys())
            bid_vol = order_depth.buy_orders[best_bid]

            qty = min(position_limit - position, bid_vol)

            logger.print("ONLY BIDS PRESENT → STRONG BUY SIGNAL")
            logger.print(f"Best Bid: {best_bid}, Volume: {bid_vol}, Qty: {qty}")

            if qty > 0:
                price = best_bid + 1
                logger.print(f"--> BUY {qty} @ {price}")
                orders.append(Order(Product.ACO, price, qty))

            return orders

        if order_depth.sell_orders and not order_depth.buy_orders:
            best_ask = min(order_depth.sell_orders.keys())
            ask_vol = order_depth.sell_orders[best_ask]

            qty = min(position_limit + position, ask_vol)

            logger.print("ONLY ASKS PRESENT → STRONG SELL SIGNAL")
            logger.print(f"Best Ask: {best_ask}, Volume: {ask_vol}, Qty: {qty}")

            if qty > 0:
                price = best_ask - 1
                logger.print(f"--> SELL {qty} @ {price}")
                orders.append(Order(Product.ACO, price, -qty))

            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        bid_vol = order_depth.buy_orders[best_bid]
        ask_vol = order_depth.sell_orders[best_ask]

        logger.print(f"Best Bid: {best_bid} (vol {bid_vol})")
        logger.print(f"Best Ask: {best_ask} (vol {ask_vol})")

        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid

        logger.print(f"Mid Price: {mid_price}")
        logger.print(f"Spread: {spread}")


        if not hasattr(self, 'aco_prices'):
            self.aco_prices = []

        self.aco_prices.append(mid_price)
        if len(self.aco_prices) > 50:
            self.aco_prices = self.aco_prices[-50:]

        logger.print(f"Stored Prices: {len(self.aco_prices)}")

        recent = np.array(self.aco_prices, dtype=float)
        mean = float(np.mean(recent))
        std = float(np.std(recent)) if len(recent) > 1 else 1.0

        logger.print(f"Rolling Mean: {round(mean,2)}")
        logger.print(f"Rolling Std: {round(std,2)}")

        z = (mid_price - mean) / std if std > 0 else 0
        logger.print(f"Z-score: {round(z,2)}")


        skew = position * 0.2
        adjusted_mid = mid_price - skew

        logger.print(f"Skew: {round(skew,2)}")
        logger.print(f"Adjusted Mid: {round(adjusted_mid,2)}")


        if abs(z) > 2:
            width = 1.2 * std
            logger.print("Regime: STRONG → tight quotes")
        elif abs(z) > 1:
            width = 1.8 * std
            logger.print("Regime: MEDIUM")
        else:
            width = 2.5 * std
            logger.print("Regime: NORMAL")

        logger.print(f"Width: {round(width,2)}")


        buy_price = int(round(adjusted_mid - width))
        sell_price = int(round(adjusted_mid + width))

        logger.print(f"Raw Buy Price: {buy_price}")
        logger.print(f"Raw Sell Price: {sell_price}")

        # Competitive adjustment
        buy_price = min(buy_price, best_bid + 1)
        sell_price = max(sell_price, best_ask - 1)

        logger.print(f"Adjusted Buy Price: {buy_price}")
        logger.print(f"Adjusted Sell Price: {sell_price}")

        if sell_price <= buy_price:
            sell_price = buy_price + 1
            logger.print("Adjusted to avoid crossing!")


        buy_capacity = position_limit - position
        sell_capacity = position_limit + position

        logger.print(f"Buy Capacity: {buy_capacity}")
        logger.print(f"Sell Capacity: {sell_capacity}")


        if buy_capacity > 0:
            logger.print(f"--> BUY {buy_capacity} @ {buy_price}")
            orders.append(Order(Product.ACO, buy_price, buy_capacity))

        if sell_capacity > 0:
            logger.print(f"--> SELL {sell_capacity} @ {sell_price}")
            orders.append(Order(Product.ACO, sell_price, -sell_capacity))

        logger.print(f"Final Orders: {orders}")

        return orders
        
    def clear_position_order(
        
        self, orders: List[Order], order_depth: OrderDepth, position: int, position_limit: int,
        product: str, buy_order_volume: int, sell_order_volume: int, fair_value: float, width: int
    ) -> List[Order]:
        
        position_after_take = position + buy_order_volume - sell_order_volume
        fair = round(fair_value)
        fair_for_bid = math.floor(fair_value)
        fair_for_ask = math.ceil(fair_value)

        buy_quantity = position_limit - (position + buy_order_volume)
        sell_quantity = position_limit + (position - sell_order_volume)

        if position_after_take > 0:
            if fair_for_ask in order_depth.buy_orders.keys():
                clear_quantity = min(order_depth.buy_orders[fair_for_ask], position_after_take)
                sent_quantity = min(sell_quantity, clear_quantity)
                orders.append(Order(product, int(fair_for_ask), -abs(sent_quantity)))
                sell_order_volume += abs(sent_quantity)

        if position_after_take < 0:
            if fair_for_bid in order_depth.sell_orders.keys():
                clear_quantity = min(abs(order_depth.sell_orders[fair_for_bid]), abs(position_after_take))
                sent_quantity = min(buy_quantity, clear_quantity)
                orders.append(Order(product, int(fair_for_bid), abs(sent_quantity)))
                buy_order_volume += abs(sent_quantity)
    
        return buy_order_volume, sell_order_volume
    
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
                self.aco_ema = data.get("aco_ema", None)
                self.ipr_spreads = data.get("ipr_spreads", [])
                self.aco_prices = data.get("aco_prices", [])
                
            except Exception:
                self.aco_ema = None
                self.ipr_spreads = []
                self.aco_prices = []
        else:
            self.aco_ema = None
            self.ipr_spreads = []
            self.aco_prices = []

        result = {}
        if Product.ACO in state.order_depths:
           result[Product.ACO] = self.aco_orders(state.order_depths[Product.ACO], 10000, state.position.get(Product.ACO, 0), self.POSITION_LIMITS[Product.ACO])
        
        if Product.IPR in state.order_depths:
            result[Product.IPR] = self.ipr_orders(state.order_depths[Product.IPR], state.position.get(Product.IPR, 0), 80)
        
        # FIX: Uniform variable name and data packing
        final_trader_data = jsonpickle.encode({
            "aco_prices": self.aco_prices,
            "ipr_spreads": self.ipr_spreads,
            "aco_ema": self.aco_ema
        })

        conversions = 0
        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data