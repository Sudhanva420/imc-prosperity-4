from Codes.src.datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string

class Trader:

    def run(self, state: TradingState):
        """
        Simple EMERALDS strategy:
        - Fair value anchor at 10000
        - Take trades only when price is past 2 deviations from fair value
        - Always place passive quotes so we can get fills and show PnL activity
        """
        print("traderData:", state.traderData)
        print("timestamp:", state.timestamp)
        result = {}
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            print("product:", product, "buy levels:", len(order_depth.buy_orders), "sell levels:", len(order_depth.sell_orders))
            
            # 1. EMERALDS specific logic
            if product == "EMERALDS":
                acceptable_price = 10000
                price_std_dev = 1
                deviation_threshold = 2 * price_std_dev
                # Keep this conservative to avoid silent order rejections.
                position_limit = 80
                current_pos = state.position.get(product, 0)
                print("EMERALDS fair:", acceptable_price, "position:", current_pos)

                buy_capacity = position_limit - current_pos
                sell_capacity = current_pos + position_limit

                # Take ask if clearly cheap vs fair value.
                if len(order_depth.sell_orders) != 0 and buy_capacity > 0:
                    
                    best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                    if int(best_ask) <= acceptable_price - deviation_threshold:
                        buy_amount = min(abs(best_ask_amount), buy_capacity)
                        if buy_amount > 0:
                            print("BUY", str(buy_amount) + "x", best_ask)
                            orders.append(Order(product, best_ask, buy_amount))
                            buy_capacity -= buy_amount

                # Hit bid if clearly rich vs fair value.
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
    
        traderData = "" 
        conversions = 0
        return result, conversions, traderData