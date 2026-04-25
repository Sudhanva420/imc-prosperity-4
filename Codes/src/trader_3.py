import json
from typing import Any, List, Optional, Tuple

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
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

SURFACE_STRIKES  = {5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500}
ATM_STRIKES      = {5000, 5100, 5200, 5300, 5400, 5500}
OTM_STRIKES      = {6000, 6500}
DEEP_ITM_STRIKES = {4000, 4500}

# Per-strike rolling buffer — 8 strikes × 50 = 400 points max
SURFACE_BUFFER  = 50
SURFACE_MIN_OBS = 40  # don't trade until surface is warmed up

# IV sanity bounds — matches offline filter (v_t > 0.05), cap blowups
IV_MIN = 0.05
IV_MAX = 1.5

# Price deviation edge (in seashells) required to trade
# OTM options have low absolute value so need a wider gate to avoid tick noise
ATM_EDGE         = 2.0   # K=5000–5500
OTM_EDGE         = 4.0   # K=6000–6500
SMILE_DIP_EDGE   = 0.7   # K=5400 — structurally cheap, be more aggressive buying
SMILE_DIP_STRIKE = 5400

# Deep ITM intrinsic edge
ITM_EDGE = 2

# VFE market-making
VFE_MA_ALPHA     = 0.05
VFE_TREND_THRESH = 2.0
VFE_BASE_EDGE    = 2
VFE_INV_SCALE    = 5.0

# ─────────────────────────────────────────────────────────────────────────────


class VolSurface:
    """
    Real-time parabola fit: IV = a*m² + b*m + c  where m = log(K/S)

    Per-strike rolling buffers prevent ATM strikes from dominating the fit.
    Pipeline matches the offline analysis:
        1. Collect (moneyness, IV) observations per strike
        2. polyfit deg=2 across all buffered points
        3. fair_iv(K, S) → plug into BS → theoretical fair price
        4. Trade price deviation: market_price - fair_price
    """

    def __init__(self, buffer_size: int = SURFACE_BUFFER):
        self.buffer_size = buffer_size
        self.buffers: dict[int, list] = {}
        self.coeffs: Optional[Tuple[float, float, float]] = None

    def update(self, strike: int, S: float, iv: float) -> None:
        if S <= 0 or iv < IV_MIN or iv > IV_MAX:
            return
        m_t = math.log(strike / S)
        if strike not in self.buffers:
            self.buffers[strike] = []
        self.buffers[strike].append((m_t, iv))
        if len(self.buffers[strike]) > self.buffer_size:
            self.buffers[strike].pop(0)

    def fit(self) -> bool:
        all_m, all_iv = [], []
        for buf in self.buffers.values():
            for m_t, iv in buf:
                all_m.append(m_t)
                all_iv.append(iv)

        if len(all_m) < SURFACE_MIN_OBS:
            return False

        try:
            raw = np.polyfit(np.array(all_m), np.array(all_iv), deg=2)
            self.coeffs = (float(raw[0]), float(raw[1]), float(raw[2]))
            return True
        except Exception:
            return False

    def fair_iv(self, strike: int, S: float) -> Optional[float]:
        if self.coeffs is None or S <= 0:
            return None
        m_t = math.log(strike / S)
        a, b, c = self.coeffs
        fair = a * m_t**2 + b * m_t + c
        return fair if fair > IV_MIN else None

    def total_obs(self) -> int:
        return sum(len(b) for b in self.buffers.values())

    def to_dict(self) -> dict:
        return {
            "buffers": {str(k): v for k, v in self.buffers.items()},
            "coeffs" : list(self.coeffs) if self.coeffs else None,
        }

    def from_dict(self, d: dict) -> None:
        self.buffers = {int(k): v for k, v in d["buffers"].items()}
        coeffs       = d.get("coeffs")
        self.coeffs  = tuple(coeffs) if coeffs else None


class Trader:
    def __init__(self):
        self.traderData = {}
        self.vfe_ma     = None
        self.surface    = VolSurface()

        self.POSITION_LIMITS = {
            "VELVETFRUIT_EXTRACT": 200,
            "HYDROGEL_PACK"      : 200,
        }
        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]:
            self.POSITION_LIMITS[f"VEV_{k}"] = 300

    # ── Math helpers ──────────────────────────────────────────────────────────

    def norm_cdf(self, x: float) -> float:
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def bs_call(self, S: float, K: float, T: float, sigma: float) -> float:
        if sigma <= 0 or T <= 0:
            return max(0.0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.norm_cdf(d1) - K * self.norm_cdf(d2)

    def implied_vol(self, market_price: float, S: float, K: float, T: float) -> Optional[float]:
        """Used only for surface observation collection, not for trading signal."""
        if market_price <= 0 or S <= 0:
            return None
        low, high = 0.01, 2.0
        for _ in range(25):
            mid = (low + high) / 2
            if self.bs_call(S, K, T, mid) > market_price:
                high = mid
            else:
                low = mid
        iv = (low + high) / 2
        return iv if IV_MIN <= iv <= IV_MAX else None

    def get_mid(self, order_depth: OrderDepth) -> Optional[float]:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        return (max(order_depth.buy_orders.keys()) + min(order_depth.sell_orders.keys())) / 2

    # ── VFE market-making ─────────────────────────────────────────────────────

    def trade_vfe(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders = []
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol  = order_depth.buy_orders[best_bid]
        ask_vol  = abs(order_depth.sell_orders[best_ask])
        micro    = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)

        if self.vfe_ma is None:
            self.vfe_ma = micro
        self.vfe_ma = VFE_MA_ALPHA * micro + (1 - VFE_MA_ALPHA) * self.vfe_ma

        spread   = best_ask - best_bid
        edge     = max(VFE_BASE_EDGE, spread // 2)
        limit    = self.POSITION_LIMITS["VELVETFRUIT_EXTRACT"]
        inv_bias = (position / limit) * VFE_INV_SCALE
        diff     = micro - self.vfe_ma

        fair_bid = int(round(micro - edge - inv_bias))
        fair_ask = int(round(micro + edge - inv_bias))

        if position < limit:
            bid = fair_bid if diff > -VFE_TREND_THRESH else fair_bid - 1
            orders.append(Order("VELVETFRUIT_EXTRACT", bid, limit - position))

        if position > -limit:
            ask = fair_ask if diff < VFE_TREND_THRESH else fair_ask + 1
            orders.append(Order("VELVETFRUIT_EXTRACT", ask, -(limit + position)))

        return orders

    # ── Deep ITM: delta-one proxy ─────────────────────────────────────────────

    def trade_itm(self, symbol: str, order_depth: OrderDepth, S: float, position: int) -> List[Order]:
        orders = []
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        K = int(symbol.split("_")[1])
        limit = self.POSITION_LIMITS[symbol]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        intrinsic = max(0.0, S - K)

        if best_ask < intrinsic - ITM_EDGE:
            qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))
        elif best_bid > intrinsic + ITM_EDGE:
            qty = min(limit + position, order_depth.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        return orders

    # ── Surface-fitted price deviation trading (ATM + OTM) ───────────────────
    #
    # Signal pipeline (matches previous year winner):
    #   1. Get fair IV from parabola fit at this strike's moneyness
    #   2. Convert fair IV → fair price via Black-Scholes
    #   3. price_dev = market_price - fair_price
    #      +ve → market too expensive → sell
    #      -ve → market too cheap    → buy
    #   4. Trade when |price_dev| exceeds strike-specific edge
    #
    # implied_vol() is NOT called here — only used during surface observation
    # collection in run(). This saves one bisection solve per strike per tick.

    def trade_surface(self, symbol: str, order_depth: OrderDepth,
                      S: float, T: float, position: int) -> List[Order]:
        orders = []
        mid = self.get_mid(order_depth)
        if mid is None or self.surface.total_obs() < SURFACE_MIN_OBS:
            return orders

        K        = int(symbol.split("_")[1])
        limit    = self.POSITION_LIMITS[symbol]
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        fair_iv = self.surface.fair_iv(K, S)
        if fair_iv is None:
            return orders

        fair_price = self.bs_call(S, K, T, fair_iv)
        price_dev  = mid - fair_price  # +ve = expensive, -ve = cheap

        # Strike-specific edge to filter tick noise
        if K == SMILE_DIP_STRIKE:
            buy_edge  = SMILE_DIP_EDGE
            sell_edge = ATM_EDGE
        elif K in OTM_STRIKES:
            buy_edge  = OTM_EDGE
            sell_edge = OTM_EDGE
        else:
            buy_edge  = ATM_EDGE
            sell_edge = ATM_EDGE
        
        BASE_SIZE = 50
        
        if price_dev < -buy_edge:
            # Market price below fair → buy
              # start

            qty = min(BASE_SIZE, limit - position, abs(order_depth.sell_orders[best_ask]))
            #qty = min(limit - position, abs(order_depth.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(symbol, best_ask, qty))

        elif price_dev > sell_edge:
            # Market price above fair → sell
            #qty = min(limit + position, order_depth.buy_orders[best_bid])
            qty = min(BASE_SIZE, limit + position, order_depth.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(symbol, best_bid, -qty))

        return orders

    # ── Main run loop ─────────────────────────────────────────────────────────

    def run(self, state: TradingState):
        if state.traderData:
            try:
                self.traderData = jsonpickle.decode(state.traderData)
                self.vfe_ma     = self.traderData.get("_vfe_ma", None)
                sd = self.traderData.get("_surface")
                if sd:
                    self.surface.from_dict(sd)
            except Exception:
                self.traderData = {}

        result      = {}
        tte_days    = 5 - (state.timestamp / 1_000_000)
        current_tte = max(tte_days, 0.001) / 365

        vfe_depth = state.order_depths.get("VELVETFRUIT_EXTRACT")
        S = self.get_mid(vfe_depth) if vfe_depth else None

        # VFE market-making
        if vfe_depth is not None:
            pos = state.position.get("VELVETFRUIT_EXTRACT", 0)
            result["VELVETFRUIT_EXTRACT"] = self.trade_vfe(vfe_depth, pos)

        if S is None:
            self.traderData["_vfe_ma"]  = self.vfe_ma
            self.traderData["_surface"] = self.surface.to_dict()
            trader_data_out = jsonpickle.encode(self.traderData)
            logger.flush(state, result, 0, trader_data_out)
            return result, 0, trader_data_out

        # ── Step 1: Feed IV observations into surface for all clean strikes ───
        # implied_vol() called here ONLY — not inside trade_surface
        for k in SURFACE_STRIKES:
            sym = f"VEV_{k}"
            if sym in state.order_depths:
                mid = self.get_mid(state.order_depths[sym])
                if mid is not None:
                    iv = self.implied_vol(mid, S, k, current_tte)
                    if iv is not None:
                        self.surface.update(k, S, iv)

        # ── Step 2: Refit parabola ────────────────────────────────────────────
        self.surface.fit()

        # ── Step 3: Trade ATM + OTM on price deviation from fair surface ──────
        #for k in sorted(ATM_STRIKES | OTM_STRIKES):
        for k in [5300]:
            sym = f"VEV_{k}"
            if sym in state.order_depths:
                pos = state.position.get(sym, 0)
                result[sym] = self.trade_surface(
                    sym, state.order_depths[sym], S, current_tte, pos
                )

        # ── Step 4: Deep ITM — intrinsic proxy ───────────────────────────────
        #for k in DEEP_ITM_STRIKES:
        #    sym = f"VEV_{k}"
        #    if sym in state.order_depths:
        #        pos = state.position.get(sym, 0)
        #       result[sym] = self.trade_itm(sym, state.order_depths[sym], S, pos)

        # Persist
        self.traderData["_vfe_ma"]  = self.vfe_ma
        self.traderData["_surface"] = self.surface.to_dict()
        trader_data_out = jsonpickle.encode(self.traderData)
        logger.flush(state, result, 0, trader_data_out)
        return result, 0, trader_data_out