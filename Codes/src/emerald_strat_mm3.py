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
        prev_pos_map = strategy_state.get("prev_pos_map", {})
        seen_trade_keys = set(strategy_state.get("seen_trade_keys", []))
        
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            print("product:", product, "buy levels:", len(order_depth.buy_orders), "sell levels:", len(order_depth.sell_orders))
            
            # EMERALDS specific logic
            if product == "EMERALDS":
                acceptable_price = 10000

                # Net executed quantity from authoritative position updates.
                prev_pos = int(prev_pos_map.get(product, 0))
                curr_pos = int(state.position.get(product, 0))
                pos_delta = curr_pos - prev_pos

                print(f"POS DBG | prev:{prev_pos} curr:{curr_pos} delta:{pos_delta}")
                
                # Gross side fills from own_trades, deduplicated across run calls.
                own_list = state.own_trades.get(product, [])
                '''
                print(f"OWN DBG | n_trades:{len(own_list)}")
                for t in own_list:
                    print(
                        "TRADE DBG |",
                        f"ts:{t.timestamp}",
                        f"px:{t.price}",
                        f"qty:{t.quantity}",
                        f"buyer:{t.buyer}",
                        f"seller:{t.seller}",
                    )
                '''
                
                prev_pos_map[product] = curr_pos

                tick_buy_fills = 0
                tick_sell_fills = 0
                for trade in own_list:
                    trade_key = f"{trade.timestamp}|{trade.price}|{trade.quantity}|{trade.buyer}|{trade.seller}"
                    if trade_key in seen_trade_keys:
                        continue
                    seen_trade_keys.add(trade_key)

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
                print(
                    "EMERALDS net | tick net buy:", max(pos_delta, 0),
                    "tick net sell:", max(-pos_delta, 0),
                )

                position_limit = 80
                
                print(state.position)
                current_pos = state.position.get(product, 0)
                print("EMERALDS fair:", acceptable_price, "position:", current_pos)

                buy_capacity = max(0, position_limit - current_pos)
                sell_capacity = max(0, position_limit + current_pos)
                
                wall_price_bid = max(order_depth.buy_orders, key=order_depth.buy_orders.get)
                wall_volume = order_depth.buy_orders[wall_price_bid]
                
                wall_price_sell = min(order_depth.sell_orders, key=order_depth.sell_orders.get)
                wall_volume_sell = order_depth.sell_orders[wall_price_sell]
                
                target_edge = 3 
                
                inventory_skew = int(current_pos / 10) # Aggressive skew
                                
                if len(order_depth.sell_orders) != 0 and buy_capacity > 0:
                    
                    #buy_price = 9997
                    
                    buy_price = 10000 - target_edge - inventory_skew
                    
                    buy_price = max(buy_price, wall_price_bid + 1)
                    
                    buy_amount = min(40, buy_capacity)
                    
                    if buy_amount > 0:
                        print("BUY", str(buy_amount) + "x", buy_price)
                        orders.append(Order(product, buy_price, buy_amount))
                        buy_capacity -= buy_amount
                        overall_fills_bought += buy_amount

                if len(order_depth.buy_orders) != 0 and sell_capacity > 0:
                    
                    sell_price = 10003
                    
                    sell_price = 10000 + target_edge - inventory_skew
                    
                    sell_price = min(sell_price, wall_price_sell - 1)
                    
                    sell_amount = min(40, sell_capacity)
                    
                    if sell_amount > 0:
                        print("SELL", str(sell_amount) + "x", sell_price)
                        orders.append(Order(product, sell_price, -sell_amount))
                        sell_capacity -= sell_amount
                        overall_fills_sold += sell_amount
                
                if len(orders) == 0:
                    print("No EMERALDS through taking orders this tick")

            result[product] = orders

        strategy_state["prev_pos_map"] = prev_pos_map
        strategy_state["seen_trade_keys"] = list(seen_trade_keys)
        strategy_state["fill_stats"] = fill_stats
        traderData = json.dumps(strategy_state)
        conversions = 0
        return result, conversions, traderData