from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string
import json
import numpy as np
import math
import jsonpickle

class Logger:
    def __init__(self):
        self.logs = ""

    def log(self, msg: str):
        # Accumulate logs during the tick
        self.logs += msg + "\n"

    def flush(self, state: TradingState, result: dict, traderData: str):
        # Basic JSON output that the visualizer can still read
        output = {
            "timestamp": state.timestamp,
            "logs": self.logs,
            "traderData": traderData,
            "orders": {sym: [[o.price, o.quantity] for o in orders] for sym, orders in result.items()}
        }
        # Print once per tick to avoid fragmentation
        print(json.dumps(output))
        self.logs = ""

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

        if len(order_depth.sell_orders) != 0 and len(order_depth.buy_orders) != 0:
            
            # finding the walls to be used
            bid_prices = sorted(order_depth.buy_orders.keys(), reverse=True)
            ask_prices = sorted(order_depth.sell_orders.keys())  
            
            bid_wall = bid_prices[0]
            ask_wall = ask_prices[0]

            for price in bid_prices:
                if abs(order_depth.buy_orders[price]) >= threshold:
                    bid_wall = price
                    break
            
            for price in ask_prices:
                if abs(order_depth.sell_orders[price]) >= threshold: # threshold check
                    ask_wall = price
                    break
            
            # fair value calculation
            wall_mid = (bid_wall + ask_wall) / 2.0
            alpha = 0.1
            
            prev_ema = getattr(self, 'tomatoes_ema', None)
            
            if prev_ema is None:
                self.tomatoes_ema = wall_mid
            else:
                self.tomatoes_ema = (alpha * wall_mid) + ((1 - alpha) * prev_ema)
            
            fair_value = self.tomatoes_ema
            
            # ARB Taker
            best_ask = ask_prices[0]
            best_bid = bid_prices[0]
            
            # Aggressive Buy
            if best_ask < fair_value:
                quantity = min(abs(order_depth.sell_orders[best_ask]), position_limit - position)
                if quantity > 0:
                    orders.append(Order(Product.TOMATOES, int(best_ask), quantity))
                    buy_order_volume += quantity

            # Aggressive Sell
            if best_bid > fair_value:
                quantity = min(abs(order_depth.buy_orders[best_bid]), position_limit + position)
                if quantity > 0:
                    orders.append(Order(Product.TOMATOES, int(best_bid), -quantity))
                    sell_order_volume += quantity

            # Inventory skew, passive quoting
            current_pos = position + buy_order_volume - sell_order_volume
            skew_factor = 0.5 
            skewed_fair = fair_value - (current_pos * skew_factor)
            
            sigma = 0.67
            l1_mid = (best_bid + best_ask) / 2.0
            dist_from_fair = l1_mid - fair_value

            # Hard limit check 
            if dist_from_fair < -(0.5 * sigma) and current_pos < (position_limit * 0.7):
                buy_price = int(round(skewed_fair - 1))
                buy_quantity = position_limit - (position + buy_order_volume)
                if buy_quantity > 0:
                    orders.append(Order(Product.TOMATOES, buy_price, buy_quantity))
                    buy_order_volume += buy_quantity

            elif dist_from_fair > (0.5 * sigma) and current_pos > -(position_limit * 0.7):
                sell_price = int(round(skewed_fair + 1))
                sell_quantity = position_limit + (position - sell_order_volume)
                if sell_quantity > 0:
                    orders.append(Order(Product.TOMATOES, sell_price, -sell_quantity))
                    sell_order_volume += sell_quantity

        # The "Golden Line" for debugging
        logger.log(f"Pos:{current_pos}|EMA:{fair_value:.1f}|L1:{l1_mid}|Dist:{dist_from_fair:.2f}|WallGap:{ask_wall-bid_wall}|BestBid:{best_bid}|BestAsk:{best_ask}|SkewedFair:{skewed_fair:.1f}|")
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
            emeralds_position = state.position.get(Product.EMERALDS, 0)
            emeralds_orders_list = self.emeralds_orders(
                state.order_depths[Product.EMERALDS], 10000,
                emeralds_position, self.POSITION_LIMITS[Product.EMERALDS]
            )
            result[Product.EMERALDS] = emeralds_orders_list
        
        if Product.TOMATOES in state.order_depths:
            tomatoes_position = state.position.get(Product.TOMATOES, 0)
            tomatoes_orders_list = self.tomatoes_orders(
                state.order_depths[Product.TOMATOES], 12, 10,
                tomatoes_position, self.POSITION_LIMITS[Product.TOMATOES]
            )
            result[Product.TOMATOES] = tomatoes_orders_list
        
        self.traderData['tomatoes_ema'] = getattr(self, 'tomatoes_ema', None)

        traderData = jsonpickle.encode({
            "traderData": self.traderData,
            "tomatoes_ema": self.traderData['tomatoes_ema'],
        })

        conversions = 0
        return result, conversions, traderData
