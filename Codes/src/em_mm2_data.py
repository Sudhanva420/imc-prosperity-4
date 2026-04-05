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
        run_rows = strategy_state.get("run_rows", [])

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            print("product:", product, "buy levels:", len(order_depth.buy_orders), "sell levels:", len(order_depth.sell_orders))

            if product == "EMERALDS":
                acceptable_price = 10000

                prev_pos = int(prev_pos_map.get(product, 0))
                curr_pos = int(state.position.get(product, 0))
                pos_delta = curr_pos - prev_pos
                print(f"POS DBG | prev:{prev_pos} curr:{curr_pos} delta:{pos_delta}")

                own_list = state.own_trades.get(product, [])
                print(f"OWN DBG | n_trades:{len(own_list)}")

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
                current_pos = state.position.get(product, 0)
                print("EMERALDS fair:", acceptable_price, "position:", current_pos)

                buy_capacity = max(0, position_limit - current_pos)
                sell_capacity = max(0, position_limit + current_pos)

                sorted_bids = sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
                for price, volume in sorted_bids:
                    print(f"Price: {price} | Volume: {volume}")

                sorted_asks = sorted(order_depth.sell_orders.items(), key=lambda x: x[0])
                for price, volume in sorted_asks:
                    print(f"Price: {price} | Volume: {volume}")

                best_bid = max(order_depth.buy_orders.keys()) if len(order_depth.buy_orders) > 0 else None
                best_ask = min(order_depth.sell_orders.keys()) if len(order_depth.sell_orders) > 0 else None

                buy_price = None
                sell_price = None
                buy_amount = 0
                sell_amount = 0

                if len(order_depth.sell_orders) != 0 and buy_capacity > 0:
                    best_ask = min(order_depth.sell_orders.keys())
                    target_volume = max(10, int(order_depth.sell_orders[best_ask] * 0.20))
                    buy_amount = min(target_volume, buy_capacity)

                    buy_price = best_ask - 1

                    if buy_amount > 0:
                        print("BUY", str(buy_amount) + "x", buy_price)
                        orders.append(Order(product, buy_price, buy_amount))
                        buy_capacity -= buy_amount
                        overall_fills_bought += buy_amount

                if len(order_depth.buy_orders) != 0 and sell_capacity > 0:
                    best_bid = max(order_depth.buy_orders.keys())
                    sell_price = best_bid + 1

                    target_volume = max(10, int(order_depth.buy_orders[best_bid] * 0.20))
                    sell_amount = min(target_volume, sell_capacity)

                    if sell_amount > 0:
                        print("SELL", str(sell_amount) + "x", sell_price)
                        orders.append(Order(product, sell_price, -sell_amount))
                        sell_capacity -= sell_amount
                        overall_fills_sold += sell_amount

                if len(orders) == 0:
                    print("No EMERALDS through taking orders this tick")

                row = {
                    "timestamp": state.timestamp,
                    "product": product,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "fair": acceptable_price,
                    "prev_pos": prev_pos,
                    "curr_pos": curr_pos,
                    "pos_delta": pos_delta,
                    "tick_buy_fills": tick_buy_fills,
                    "tick_sell_fills": tick_sell_fills,
                    "cum_buy_fills": product_fill_stats["buy"],
                    "cum_sell_fills": product_fill_stats["sell"],
                    "buy_quote": buy_price,
                    "sell_quote": sell_price,
                    "buy_order_qty": buy_amount,
                    "sell_order_qty": sell_amount,
                    "buy_capacity_after": buy_capacity,
                    "sell_capacity_after": sell_capacity,
                    "own_trades_seen_count": len(seen_trade_keys),
                }
                run_rows.append(row)
                if len(run_rows) > 300:
                    run_rows = run_rows[-300:]
                print("DATA_ROW", json.dumps(row))

            result[product] = orders

        strategy_state["prev_pos_map"] = prev_pos_map
        strategy_state["seen_trade_keys"] = list(seen_trade_keys)
        strategy_state["fill_stats"] = fill_stats
        strategy_state["run_rows"] = run_rows
        traderData = json.dumps(strategy_state)
        conversions = 0
        return result, conversions, traderData
