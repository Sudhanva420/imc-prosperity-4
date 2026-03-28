from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string
import json
import numpy as np

# Simple strategy for EMERALDS, buy and sell based on deviations from a fair value, taken as 
# 10k based on data exploration
class Trader:

    def run(self, state: TradingState):

        print("traderData:", state.traderData)
        print("timestamp:", state.timestamp)

        # Persist rolling histories across ticks using traderData.
        if state.traderData:
            try:
                strategy_state = json.loads(state.traderData)
            except Exception:
                strategy_state = {}
        else:
            strategy_state = {}

        result = {}
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            print("product:", product, "buy levels:", len(order_depth.buy_orders), "sell levels:", len(order_depth.sell_orders))
            
            # EMERALDS specific logic
            if product == "EMERALDS":
                acceptable_price = 10000
                history = strategy_state.get(product, [])

                if len(order_depth.sell_orders) != 0 and len(order_depth.buy_orders) != 0:
                    best_ask = min(order_depth.sell_orders.keys())
                    best_bid = max(order_depth.buy_orders.keys())
                    mid_price = (best_ask + best_bid) / 2
                    history.append(mid_price)
                    if len(history) > 40:
                        history.pop(0)

                std_dev = float(np.std(history)) if len(history) > 10 else 1.5
                deviation_threshold = max(2 * std_dev, 2.0)
                strategy_state[product] = history

                # Position limits
                position_limit = 80
                current_pos = state.position.get(product, 0)
                print("EMERALDS fair:", acceptable_price, "position:", current_pos)
                print("EMERALDS std_dev:", round(std_dev, 4), "entry_threshold:", round(deviation_threshold, 4))

                buy_capacity = position_limit - current_pos
                sell_capacity = current_pos + position_limit

                if len(order_depth.sell_orders) != 0 and buy_capacity > 0:
                    
                    best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                    if int(best_ask) <= acceptable_price - deviation_threshold:
                        buy_amount = min(abs(best_ask_amount), buy_capacity)
                        if buy_amount > 0:
                            print("BUY", str(buy_amount) + "x", best_ask)
                            orders.append(Order(product, best_ask, buy_amount))
                            buy_capacity -= buy_amount

                if len(order_depth.buy_orders) != 0 and sell_capacity > 0:
                    best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]
                    if int(best_bid) >= acceptable_price + deviation_threshold:
                        sell_amount = min(abs(best_bid_amount), sell_capacity)
                        if sell_amount > 0:
                            print("SELL", str(sell_amount) + "x", best_bid)
                            orders.append(Order(product, best_bid, -sell_amount))
                            sell_capacity -= sell_amount


                if len(orders) == 0:
                    print("No EMERALDS order this tick")
            
            result[product] = orders
    
        traderData = json.dumps(strategy_state)
        conversions = 0
        return result, conversions, traderData