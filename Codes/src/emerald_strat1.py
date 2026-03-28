from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string

class Trader:

    def run(self, state: TradingState):

        print("traderData:", state.traderData)
        print("timestamp:", state.timestamp)
        result = {}
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            print("product:", product, "buy levels:", len(order_depth.buy_orders), "sell levels:", len(order_depth.sell_orders))
            
            # EMERALDS specific logic
            if product == "EMERALDS":
                acceptable_price = 10000
                price_std_dev = 1
                deviation_threshold = 2 * price_std_dev
                
                # Position limits enforced 
                position_limit = 80
                current_pos = state.position.get(product, 0)
                print("EMERALDS fair:", acceptable_price, "position:", current_pos)

                buy_capacity = position_limit - current_pos
                sell_capacity = current_pos + position_limit

                # Take ask if cheap vs fair value.
                if len(order_depth.sell_orders) != 0 and buy_capacity > 0:
                    
                    best_ask, best_ask_amount = list(order_depth.sell_orders.items())[0]
                    if int(best_ask) <= acceptable_price - deviation_threshold:
                        buy_amount = min(abs(best_ask_amount), buy_capacity)
                        if buy_amount > 0:
                            print("BUY", str(buy_amount) + "x", best_ask)
                            orders.append(Order(product, best_ask, buy_amount))
                            buy_capacity -= buy_amount

                # Hit bid if rich vs fair value.
                if len(order_depth.buy_orders) != 0 and sell_capacity > 0:
                    best_bid, best_bid_amount = list(order_depth.buy_orders.items())[0]
                    if int(best_bid) >= acceptable_price + deviation_threshold:
                        sell_amount = min(abs(best_bid_amount), sell_capacity)
                        if sell_amount > 0:
                            print("SELL", str(sell_amount) + "x", best_bid)
                            orders.append(Order(product, best_bid, -sell_amount))
                            sell_capacity -= sell_amount

                # Passive quotes for market making behaviour (mispricing dont always exist)
                quote_size = 5
                if buy_capacity > 0:
                    bid_quote = acceptable_price - 1
                    bid_qty = min(quote_size, buy_capacity)
                    orders.append(Order(product, bid_quote, bid_qty))
                    print("MM BUY", str(bid_qty) + "x", bid_quote)

                if sell_capacity > 0:
                    ask_quote = acceptable_price + 1
                    ask_qty = min(quote_size, sell_capacity)
                    orders.append(Order(product, ask_quote, -ask_qty))
                    print("MM SELL", str(ask_qty) + "x", ask_quote)

                if len(orders) == 0:
                    print("No EMERALDS order this tick")
            
            result[product] = orders
    
        traderData = "" 
        conversions = 0
        return result, conversions, traderData