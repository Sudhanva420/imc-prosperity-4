from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string
import json
import numpy as np

class Trader:

    def run(self, state: TradingState):

        print("traderData:", state.traderData)
        print("timestamp:", state.timestamp)

        if state.traderData:
            try:
                strategy_state = json.loads(state.traderData)
            except Exception:
                strategy_state = {}
        else:
            strategy_state = {}

        result = {}
        
        overall_fills_bought = 0
        overall_fills_sold = 0

        fill_stats = strategy_state.get("fill_stats", {})
        
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            print("product:", product, "buy levels:", len(order_depth.buy_orders), "sell levels:", len(order_depth.sell_orders))
            
            # EMERALDS specific logic
            if product == "EMERALDS":
                acceptable_price = 10000

                # Read realized fills from exchange 
                tick_buy_fills = 0
                tick_sell_fills = 0
                for trade in state.own_trades.get(product, []):
                    qty = abs(int(trade.quantity))
                    if trade.buyer == "SUBMISSION":
                        tick_buy_fills += qty
                    elif trade.seller == "SUBMISSION":
                        tick_sell_fills += qty

                product_fill_stats = fill_stats.get(product, {"buy": 0, "sell": 0})
                product_fill_stats["buy"] += tick_buy_fills
                product_fill_stats["sell"] += tick_sell_fills
                fill_stats[product] = product_fill_stats

                print(
                    "EMERALDS fills | tick buy:", tick_buy_fills,
                    "tick sell:", tick_sell_fills,
                    "cum buy:", product_fill_stats["buy"],
                    "cum sell:", product_fill_stats["sell"],
                )

                position_limit = 80
                current_pos = state.position.get(product, 0)
                print("EMERALDS fair:", acceptable_price, "position:", current_pos)

                buy_capacity = max(0, position_limit - current_pos)
                sell_capacity = max(0, position_limit + current_pos)

                if len(order_depth.sell_orders) != 0 and buy_capacity > 0:
                    buy_price = 9997
                    buy_amount = min(20, buy_capacity)
                    if buy_amount > 0:
                        print("BUY", str(buy_amount) + "x", buy_price)
                        orders.append(Order(product, buy_price, buy_amount))
                        buy_capacity -= buy_amount
                        overall_fills_bought += buy_amount

                if len(order_depth.buy_orders) != 0 and sell_capacity > 0:
                    sell_price = 10003
                    sell_amount = min(20, sell_capacity)
                    if sell_amount > 0:
                        print("SELL", str(sell_amount) + "x", sell_price)
                        orders.append(Order(product, sell_price, -sell_amount))
                        sell_capacity -= sell_amount
                        overall_fills_sold += sell_amount
                
                if len(orders) == 0:
                    print("No EMERALDS through taking orders this tick")

            result[product] = orders

        strategy_state["fill_stats"] = fill_stats
        traderData = json.dumps(strategy_state)
        conversions = 0
        return result, conversions, traderData