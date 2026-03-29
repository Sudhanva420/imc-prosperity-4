from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string
import json
import numpy as np

class Trader:

    def run(self, state: TradingState):

        print("traderData:", state.traderData)
        print("timestamp:", state.timestamp)

        # Persist rolling histories across ticks using traderData.
        if state.traderData:
            try:
                strategy_state = json.loads(state.traderData)
                print("Loaded strategy state:", strategy_state)
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
                fair_value_anchor = 10000

                product_state = strategy_state.get(product, {})
                if not isinstance(product_state, dict):
                    product_state = {}

                history = product_state.get("history", [])
                ema_fair = float(product_state.get("ema_fair", fair_value_anchor))
                vol_ema = float(product_state.get("vol_ema", 1.5))

                if len(order_depth.sell_orders) != 0 and len(order_depth.buy_orders) != 0:
                    best_ask = min(order_depth.sell_orders.keys())
                    best_bid = max(order_depth.buy_orders.keys())
                    mid_price = (best_ask + best_bid) / 2
                    history.append(mid_price)
                    if len(history) > 40:
                        history.pop(0)

                    # Slow fair-value adaptation so anchor dominates unless a persistent shift appears.
                    ema_alpha = 0.03
                    ema_fair = ((1 - ema_alpha) * ema_fair) + (ema_alpha * mid_price)
                else:
                    best_ask = None
                    best_bid = None

                std_dev = float(np.std(history)) if len(history) > 10 else 1.5
                vol_alpha = 0.05
                vol_ema = ((1 - vol_alpha) * vol_ema) + (vol_alpha * std_dev)

                product_state["history"] = history
                product_state["ema_fair"] = ema_fair
                product_state["vol_ema"] = vol_ema
                strategy_state[product] = product_state

                # Enforce position limits
                position_limit = 80
                current_pos = state.position.get(product, 0)
                adaptive_fair = (0.85 * fair_value_anchor) + (0.15 * ema_fair)
                print("EMERALDS fair:", round(adaptive_fair, 3), "position:", current_pos)
                print("EMERALDS std_dev:", round(std_dev, 4), "vol_ema:", round(vol_ema, 4))

                buy_capacity = position_limit - current_pos
                sell_capacity = current_pos + position_limit

                if best_ask is None or best_bid is None:
                    result[product] = orders
                    continue

                best_ask_amount = order_depth.sell_orders[best_ask]
                best_bid_amount = order_depth.buy_orders[best_bid]
                top_spread = best_ask - best_bid

                # Part 1 + Part 2: anchored fair value with inventory-aware reservation shift.
                inventory_penalty = 0.05
                reservation_price = adaptive_fair - (inventory_penalty * current_pos)

                # Part 3: signal-based skew from level-1 imbalance + microprice bias.
                bid_v = max(best_bid_amount, 0)
                ask_v = abs(min(best_ask_amount, 0))
                total_v = bid_v + ask_v
                imbalance = (bid_v - ask_v) / total_v if total_v > 0 else 0.0
                micro_price = (best_bid * ask_v + best_ask * bid_v) / total_v if total_v > 0 else (best_bid + best_ask) / 2
                micro_bias = micro_price - ((best_bid + best_ask) / 2)

                signal_shift = float(np.clip((0.8 * imbalance) + (0.4 * micro_bias), -1.0, 1.0))
                reservation_price += signal_shift

                # Part 4: opportunistic taker if top-of-book is sufficiently off reservation.
                taker_threshold = max(0.75, 0.6 * vol_ema)

                # Regime guardrails for hidden data.
                # Tight spread: avoid over-aggression and reduce taker activity.
                # Wide/volatile regime: quote wider and smaller to reduce adverse selection.
                if top_spread <= 2:
                    taker_threshold += 0.35
                if top_spread >= 8 or vol_ema >= 1.4:
                    taker_threshold += 0.25

                if buy_capacity > 0 and best_ask <= reservation_price - taker_threshold:
                    buy_amount = min(abs(best_ask_amount), buy_capacity, 12)
                    if buy_amount > 0:
                        print("TAKER BUY", str(buy_amount) + "x", best_ask)
                        orders.append(Order(product, best_ask, buy_amount))
                        buy_capacity -= buy_amount

                if sell_capacity > 0 and best_bid >= reservation_price + taker_threshold:
                    sell_amount = min(abs(best_bid_amount), sell_capacity, 12)
                    if sell_amount > 0:
                        print("TAKER SELL", str(sell_amount) + "x", best_bid)
                        orders.append(Order(product, best_bid, -sell_amount))
                        sell_capacity -= sell_amount

                # Core passive MM quotes.
                half_spread = max(1, int(np.ceil(0.5 + 0.25 * vol_ema + 0.10 * max(0, top_spread - 4))))
                bid_quote = int(np.floor(reservation_price - half_spread))
                ask_quote = int(np.ceil(reservation_price + half_spread))
                if bid_quote >= ask_quote:
                    bid_quote = ask_quote - 1

                # Size down when volatility or spread regime worsens.
                base_quote_size = 10
                if vol_ema >= 1.4:
                    base_quote_size = 7
                if top_spread >= 8:
                    base_quote_size = min(base_quote_size, 6)
                if top_spread <= 2:
                    base_quote_size = min(base_quote_size, 5)

                buy_quote_size = min(base_quote_size, max(0, buy_capacity))
                sell_quote_size = min(base_quote_size, max(0, sell_capacity))

                # Inventory pressure: avoid adding to a stretched side.
                if current_pos >= 60:
                    buy_quote_size = min(buy_quote_size, 2)
                if current_pos <= -60:
                    sell_quote_size = min(sell_quote_size, 2)

                if buy_quote_size > 0:
                    orders.append(Order(product, bid_quote, buy_quote_size))
                    print("MM BUY", str(buy_quote_size) + "x", bid_quote)

                if sell_quote_size > 0:
                    orders.append(Order(product, ask_quote, -sell_quote_size))
                    print("MM SELL", str(sell_quote_size) + "x", ask_quote)

                print(
                    "EMERALDS dbg:",
                    "best_bid", best_bid,
                    "best_ask", best_ask,
                    "spr", top_spread,
                    "imb", round(imbalance, 3),
                    "micro_bias", round(micro_bias, 3),
                    "ema_fair", round(ema_fair, 3),
                    "res", round(reservation_price, 3),
                    "tk", round(taker_threshold, 3),
                )

                if len(orders) == 0:
                    print("No EMERALDS order this tick")
            
            result[product] = orders
    
        traderData = json.dumps(strategy_state)
        conversions = 0
        return result, conversions, traderData