import json
from typing import Any

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
from typing import List
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
                compressed.append([trade.symbol, trade.price, trade.quantity,
                                    trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice,
                observation.transportFees, observation.exportTariff,
                observation.importTariff, observation.sugarPrice,
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


# ── Strategy parameters ───────────────────────────────────────────────────────

# From analysis: RV=33.8% vs ATM IV=29.5% → options are CHEAP → long vol bias ATM
# Underlying ranges 5216-5284, never threatens OTM strikes → OTM skew is RICH → short vol bias OTM
# K=5400 sits in a smile dip (~28.1% vs ~29-30% neighbours) → structural buy

ATM_STRIKES     = {5000, 5100, 5200, 5300, 5400, 5500}   # clean IV data, full counts
OTM_STRIKES     = {6000, 6500}                             # rich skew, short vol
DEEP_ITM_STRIKES = {4000, 4500}                            # delta-one proxy only

# ATM vol trading thresholds (z-score of IV)
ATM_BUY_Z   = -1.5   # IV cheap vs recent history → buy
ATM_SELL_Z  =  1.5   # IV rich vs recent history → sell

# K=5400 smile dip: we know from static analysis this strike is structurally cheap
# so we use a tighter buy threshold to be more aggressive there
SMILE_DIP_STRIKE = 5400
SMILE_DIP_BUY_Z  = -0.8  # buy sooner for this strike

# OTM skew thresholds (skew = OTM_IV - ATM_IV)
# From data: K=6000 skew ~0.15, K=6500 skew ~0.38 vs ATM ~0.295
# Underlying max move is ~0.8% so these far OTM strikes are nearly unreachable
OTM_SKEW_SELL  = 0.12   # skew above this → sell OTM vol (rich fear premium)
OTM_SKEW_BUY   = 0.04   # skew below this → buy OTM (too flat, unlikely)

# IV history window for mean reversion
IV_HISTORY_WINDOW = 100
IV_MIN_SAMPLES    = 20

# Deep ITM intrinsic edge (ticks of edge required to trade)
ITM_EDGE = 2

# VFE market-making parameters
VFE_MA_ALPHA     = 0.05   # slow EMA to track wave (~40-50k period)
VFE_TREND_THRESH = 2.0    # price vs MA diff to suppress quoting into trend
VFE_BASE_EDGE    = 2      # minimum half-spread
VFE_INV_SCALE    = 5.0    # inventory skew multiplier

# ─────────────────────────────────────────────────────────────────────────────


class Trader:
    def __init__(self):
        self.traderData = {}

        self.POSITION_LIMITS = {
            "VELVETFRUIT_EXTRACT": 200,
            "HYDROGEL_PACK": 200,
        }
        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]:
            self.POSITION_LIMITS[f"VEV_{k}"] = 300

        # Persistent state (also stored in traderData for cross-tick survival)
        self.vfe_ma = None

    # ── Math helpers ──────────────────────────────────────────────────────────

    def norm_cdf(self, x: float) -> float:
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def bs_call(self, S: float, K: float, T: float, sigma: float) -> float:
        if sigma <= 0 or T <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.norm_cdf(d1) - K * self.norm_cdf(d2)

    def bs_delta(self, S: float, K: float, T: float, sigma: float) -> float:
        """Black-Scholes delta for a call option."""
        if sigma <= 0 or T <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        return self.norm_cdf(d1)

    def implied_vol(self, market_price: float, S: float, K: float, T: float) -> float:
        """Bisection IV solver. Returns vol in [0.01, 2.0]."""
        low, high = 0.01, 2.0
        for _ in range(25):
            mid = (low + high) / 2
            if self.bs_call(S, K, T, mid) > market_price:
                high = mid
            else:
                low = mid
        return (low + high) / 2

    def get_mid(self, order_depth: OrderDepth):
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        return (max(order_depth.buy_orders.keys()) + min(order_depth.sell_orders.keys())) / 2

    # ── VFE market-making ─────────────────────────────────────────────────────
    # Strategy: passive MM with micro-price + slow EMA trend filter.
    # The wave structure (~40-50k period) means we want to lean into selling
    # near the ceiling (~5284) and buying near the floor (~5216).

    def trade_vfe(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders = []
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol  = order_depth.buy_orders[best_bid]
        ask_vol  = abs(order_depth.sell_orders[best_ask])

        # Micro-price: weight by opposite-side volume
        micro = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)

        # Slow EMA to track the wave
        if self.vfe_ma is None:
            self.vfe_ma = micro
        self.vfe_ma = VFE_MA_ALPHA * micro + (1 - VFE_MA_ALPHA) * self.vfe_ma

        spread = best_ask - best_bid
        edge   = max(VFE_BASE_EDGE, spread // 2)
        limit  = self.POSITION_LIMITS["VELVETFRUIT_EXTRACT"]

        # Inventory skew: drag prices toward unwinding
        inv_bias = (position / limit) * VFE_INV_SCALE
        diff_from_ma = micro - self.vfe_ma

        fair_bid = int(round(micro - edge - inv_bias))
        fair_ask = int(round(micro + edge - inv_bias))

        # Buy side — suppress if price is falling hard away from MA
        if position < limit:
            bid = fair_bid if diff_from_ma > -VFE_TREND_THRESH else fair_bid - 1
            orders.append(Order("VELVETFRUIT_EXTRACT", bid, limit - position))

        # Sell side — suppress if price is running hard above MA
        if position > -limit:
            ask = fair_ask if diff_from_ma < VFE_TREND_THRESH else fair_ask + 1
            orders.append(Order("VELVETFRUIT_EXTRACT", ask, -(limit + position)))

        return orders

    # ── Deep ITM: delta-one proxy ─────────────────────────────────────────────
    # Delta ≈ 1 → option price ≈ intrinsic value (S - K).
    # Trade when the voucher deviates from intrinsic by more than ITM_EDGE ticks.
    # IV is meaningless here due to high std dev in data.

    def trade_itm(self, symbol: str, order_depth: OrderDepth, S: float, position: int) -> List[Order]:
        orders = []
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        K         = int(symbol.split("_")[1])
        limit     = self.POSITION_LIMITS[symbol]
        best_bid  = max(order_depth.buy_orders.keys())
        best_ask  = min(order_depth.sell_orders.keys())
        intrinsic = max(0.0, S - K)

        if best_ask < intrinsic - ITM_EDGE:
            # Voucher too cheap vs intrinsic → buy
            qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        elif best_bid > intrinsic + ITM_EDGE:
            # Voucher too expensive vs intrinsic → sell
            qty = min(limit + position, order_depth.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        return orders

    # ── ATM: IV mean reversion ────────────────────────────────────────────────
    # From analysis: RV (33.8%) > ATM IV (29.5%) → options are cheap → long vol bias.
    # We still trade the z-score (mean revert within the session) but use a
    # tighter buy threshold (-1.5) than sell (+1.5) to reflect the long bias.
    # K=5400 gets an even tighter buy threshold since it sits in a smile dip.

    def trade_atm(self, symbol: str, order_depth: OrderDepth, S: float, T: float, position: int) -> List[Order]:
        orders = []
        mid = self.get_mid(order_depth)
        if mid is None:
            return orders

        K     = int(symbol.split("_")[1])
        limit = self.POSITION_LIMITS[symbol]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        iv = self.implied_vol(mid, S, K, T)

        # Maintain rolling IV history
        key = f"iv_{symbol}"
        if key not in self.traderData:
            self.traderData[key] = []
        self.traderData[key].append(iv)
        if len(self.traderData[key]) > IV_HISTORY_WINDOW:
            self.traderData[key].pop(0)

        if len(self.traderData[key]) < IV_MIN_SAMPLES:
            return orders  # not enough history yet

        iv_mean = float(np.mean(self.traderData[key]))
        iv_std  = float(np.std(self.traderData[key]))
        if iv_std <= 0:
            return orders

        z = (iv - iv_mean) / iv_std

        # Smile dip strike gets a more aggressive buy threshold
        buy_z = SMILE_DIP_BUY_Z if K == SMILE_DIP_STRIKE else ATM_BUY_Z

        if z < buy_z:
            # IV cheap → buy the voucher (long vol / long gamma)
            qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        elif z > ATM_SELL_Z:
            # IV rich → sell the voucher (short vol)
            qty = min(limit + position, order_depth.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        return orders

    # ── OTM: skew / relative value ────────────────────────────────────────────
    # From analysis: underlying max range ~0.8%, K=6000 is ~14% OTM, K=6500 ~24% OTM.
    # The underlying literally cannot reach these strikes in the data.
    # K=6000 IV ~45%, K=6500 IV ~68% vs ATM ~29.5% → rich fear premium → short vol.
    # We anchor to current ATM IV (K=5200 as the cleaner of the two near-ATM strikes).

    def trade_otm(self, symbol: str, order_depth: OrderDepth, S: float, T: float, position: int) -> List[Order]:
        orders = []
        mid = self.get_mid(order_depth)
        if mid is None:
            return orders

        K     = int(symbol.split("_")[1])
        limit = self.POSITION_LIMITS[symbol]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        # Need current ATM IV as anchor — use VEV_5200 history
        atm_iv_list = self.traderData.get("iv_VEV_5200", [])
        if not atm_iv_list:
            return orders  # wait for ATM data to populate

        atm_iv     = float(np.mean(atm_iv_list[-20:]))  # recent ATM IV average
        current_iv = self.implied_vol(mid, S, K, T)
        skew       = current_iv - atm_iv

        if skew > OTM_SKEW_SELL:
            # Skew too steep → OTM vol rich → sell the voucher
            qty = min(limit + position, order_depth.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        elif skew < OTM_SKEW_BUY:
            # Skew collapsed → OTM vol cheap → buy the voucher
            qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        return orders

    # ── Main run loop ─────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        # Restore persistent state
        if state.traderData:
            try:
                self.traderData = jsonpickle.decode(state.traderData)
                # Restore VFE MA
                self.vfe_ma = self.traderData.get("_vfe_ma", None)
            except:
                self.traderData = {}

        result = {}

        # Time to expiry: 5 trading days total, ~1M timestamps per day
        tte_days   = 5 - (state.timestamp / 1_000_000)
        current_tte = max(tte_days, 0.001) / 365

        # Underlying mid price (needed for all option models)
        vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        S = self.get_mid(vfe_depth) if vfe_depth else None

        # ── VFE: market-make the underlying ──────────────────────────────────
        if vfe_depth is not None:
            pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
            result["VELVETFRUIT_EXTRACT"] = self.trade_vfe(vfe_depth, pos)

        if S is None:
            # Can't price options without underlying — flush and return
            self.traderData["_vfe_ma"] = self.vfe_ma
            trader_data_out = jsonpickle.encode(self.traderData)
            logger.flush(state, result, 0, trader_data_out)
            return result, 0, trader_data_out

        # ── Process ATM strikes FIRST so OTM can read their IV history ────────
        atm_order = [5000, 5100, 5200, 5300, 5400, 5500]
        for k in atm_order:
            sym = f"VEV_{k}"
            if sym in state.order_depths:
                pos = state.position.get(sym, 0)
                result[sym] = self.trade_atm(sym, state.order_depths[sym], S, current_tte, pos)

        # ── OTM strikes (anchored to ATM IV populated above) ──────────────────
        for k in [6000, 6500]:
            sym = f"VEV_{k}"
            if sym in state.order_depths:
                pos = state.position.get(sym, 0)
                result[sym] = self.trade_otm(sym, state.order_depths[sym], S, current_tte, pos)

        # ── Deep ITM strikes ──────────────────────────────────────────────────
        for k in [4000, 4500]:
            sym = f"VEV_{k}"
            if sym in state.order_depths:
                pos = state.position.get(sym, 0)
                result[sym] = self.trade_itm(sym, state.order_depths[sym], S, pos)

        # Persist state
        self.traderData["_vfe_ma"] = self.vfe_ma
        trader_data_out = jsonpickle.encode(self.traderData)
        logger.flush(state, result, 0, trader_data_out)
        return result, 0, trader_data_out
