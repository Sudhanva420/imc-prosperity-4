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
    
    EMERALDS = "EMERALDS"
    TOMATOES = "TOMATOES"
    

        
    
class Trader:
    
    def __init__(self):
        
        self.traderData = {}

        self.tomatoes_prices = []
        
        self.POSITION_LIMITS = {
            Product.EMERALDS: 80,
            Product.TOMATOES: 80,
        }
        
    def emeralds_orders(self, order_depth: OrderDepth, fair_value: int, position: int, position_limit: int) -> List[Order]:
        orders: List[Order] = []

        buy_order_volume = 0
        sell_order_volume = 0
        
        sell_prices_above = [price for price in order_depth.sell_orders.keys() if price > fair_value + 1]
        if sell_prices_above:
            baaf = min(sell_prices_above)
        else:
            baaf = fair_value + 2

        buy_prices_below = [price for price in order_depth.buy_orders.keys() if price < fair_value - 1]
        if buy_prices_below:
            bbbf = max(buy_prices_below)
        else:
            bbbf = fair_value - 2

        if len(order_depth.sell_orders) != 0:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_amount = -1 * order_depth.sell_orders[best_ask]
            if best_ask < fair_value:
                quantity = min(best_ask_amount, position_limit - position)  
                if quantity > 0:
                    orders.append(Order(Product.EMERALDS, int(round(best_ask)), quantity))
                    buy_order_volume += quantity

        if len(order_depth.buy_orders) != 0:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_amount = order_depth.buy_orders[best_bid]
            if best_bid > fair_value:
                quantity = min(best_bid_amount, position_limit + position)  
                if quantity > 0:
                    orders.append(Order(Product.EMERALDS, int(round(best_bid)), -1 * quantity))
                    sell_order_volume += quantity
        
        buy_order_volume, sell_order_volume = self.clear_position_order(
            orders, order_depth, position, position_limit, Product.EMERALDS,
            buy_order_volume, sell_order_volume, fair_value, 1)

        buy_quantity = position_limit - (position + buy_order_volume)
        if buy_quantity > 0:
            orders.append(Order(Product.EMERALDS, int(round(bbbf + 1)), buy_quantity))  

        sell_quantity = position_limit + (position - sell_order_volume)
        if sell_quantity > 0:
            orders.append(Order(Product.EMERALDS, int(round(baaf - 1)), -sell_quantity))  

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
    
    def tomatoes_orders(self, order_depth: OrderDepth, threshold: int, window: int, position: int, position_limit: int) -> List[Order]:
        orders: List[Order] = []
        buy_order_volume = 0
        sell_order_volume = 0
        
        # Initialize variables so the logger doesn't crash if the depth is empty
        best_bid = best_ask = l1_mid = fair_value = skewed_fair = dist_from_fair = 0
        ask_wall = bid_wall = 0
        current_pos = position

        if len(order_depth.sell_orders) != 0 and len(order_depth.buy_orders) != 0:
            bid_prices = sorted(order_depth.buy_orders.keys(), reverse=True)
            ask_prices = sorted(order_depth.sell_orders.keys())  
            
            best_bid, best_ask = bid_prices[0], ask_prices[0]
            bid_wall, ask_wall = best_bid, best_ask

            for price in bid_prices:
                if abs(order_depth.buy_orders[price]) >= threshold:
                    bid_wall = price
                    break
            for price in ask_prices:
                if abs(order_depth.sell_orders[price]) >= threshold:
                    ask_wall = price
                    break
            
            wall_mid = (bid_wall + ask_wall) / 2.0
            alpha = 0.1
            prev_ema = getattr(self, 'tomatoes_ema', None)
            self.tomatoes_ema = (alpha * wall_mid) + ((1 - alpha) * prev_ema) if prev_ema is not None else wall_mid
            
            fair_value = self.tomatoes_ema
            
            # ARB Taker
            if best_ask < fair_value:
                qty = min(abs(order_depth.sell_orders[best_ask]), position_limit - position)
                if qty > 0:
                    orders.append(Order(Product.TOMATOES, int(best_ask), qty))
                    buy_order_volume += qty
            if best_bid > fair_value:
                qty = min(abs(order_depth.buy_orders[best_bid]), position_limit + position)
                if qty > 0:
                    orders.append(Order(Product.TOMATOES, int(best_bid), -qty))
                    sell_order_volume += qty

            current_pos = position + buy_order_volume - sell_order_volume
            skewed_fair = fair_value - (current_pos * 0.5)
            sigma = 0.67
            l1_mid = (best_bid + best_ask) / 2.0
            dist_from_fair = l1_mid - fair_value

            if dist_from_fair < -(0.5 * sigma) and current_pos < (position_limit * 0.7):
                buy_price = int(round(skewed_fair - 1))
                buy_qty = position_limit - (position + buy_order_volume)
                if buy_qty > 0:
                    orders.append(Order(Product.TOMATOES, buy_price, buy_qty))
            elif dist_from_fair > (0.5 * sigma) and current_pos > -(position_limit * 0.7):
                sell_price = int(round(skewed_fair + 1))
                sell_qty = position_limit + (position - sell_order_volume)
                if sell_qty > 0:
                    orders.append(Order(Product.TOMATOES, sell_price, -sell_qty))

        # FIX: Changed to logger.print
        logger.print(f"TOM| Pos:{current_pos}|EMA:{fair_value:.1f}|L1:{l1_mid}|Dist:{dist_from_fair:.2f}|WallGap:{ask_wall-bid_wall}|BestBid:{best_bid}|BestAsk:{best_ask}|SkewedFair:{skewed_fair:.1f}")
        return orders

    def run(self, state: TradingState):
        if state.traderData:
            try:
                data = jsonpickle.decode(state.traderData)
                self.tomatoes_ema = data.get("tomatoes_ema", None)
            except Exception:
                self.tomatoes_ema = None

        result = {}
        if Product.EMERALDS in state.order_depths:
            result[Product.EMERALDS] = self.emeralds_orders(state.order_depths[Product.EMERALDS], 10000, state.position.get(Product.EMERALDS, 0), 80)
        
        if Product.TOMATOES in state.order_depths:
            result[Product.TOMATOES] = self.tomatoes_orders(state.order_depths[Product.TOMATOES], 12, 10, state.position.get(Product.TOMATOES, 0), 80)
        
        # FIX: Uniform variable name and data packing
        final_trader_data = jsonpickle.encode({
            "tomatoes_ema": getattr(self, 'tomatoes_ema', None),
        })

        conversions = 0
        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data
