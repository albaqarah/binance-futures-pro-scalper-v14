from __future__ import annotations
import hashlib, hmac, json, math, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional
from .config import Settings


class BinanceFuturesClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://testnet.binancefuture.com" if settings.use_testnet else "https://fapi.binance.com"
        self._rules_cache: dict[str, dict[str, float]] = {}
        self._time_offset = 0  # selisih jam lokal vs server Binance (ms)

    def _sign(self, params: Dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params, doseq=True)
        sig = hmac.new(self.settings.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return query + "&signature=" + sig

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False, _retry: bool = False) -> Any:
        params = params or {}
        headers = {}
        if self.settings.api_key:
            headers["X-MBX-APIKEY"] = self.settings.api_key
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._time_offset
            params.setdefault("recvWindow", 10000)
            query = self._sign(params)
        else:
            query = urllib.parse.urlencode(params, doseq=True)
        url = self.base_url + path
        data = None
        if method.upper() == "GET":
            if query: url += "?" + query
        else:
            data = query.encode(); headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            # Auto-recovery error timestamp (-1021): sinkron ulang jam lalu coba sekali lagi.
            if signed and e.code == 400 and "-1021" in body and not _retry:
                self.sync_time()
                params.pop("timestamp", None)
                return self._request(method, path, params, signed=True, _retry=True)
            raise RuntimeError(f"Binance HTTP {e.code}: {body}") from e

    def sync_time(self) -> int:
        """Sinkron jam lokal ke server Binance (mengatasi error -1021 timestamp)."""
        try:
            server = int(self._request("GET", "/fapi/v1/time")["serverTime"])
            self._time_offset = server - int(time.time() * 1000)
        except Exception:
            pass  # gagal sinkron: pertahankan offset terakhir, jangan reset ke 0
        return self._time_offset

    # ---------------- account / market ----------------
    def get_account(self) -> dict[str, Any]:
        if self.settings.dry_run: return {"availableBalance": "1000.0", "dryRun": True}
        return self._request("GET", "/fapi/v2/account", signed=True)

    def get_available_margin_usdt(self) -> float:
        a = self.get_account()
        return float(a.get("availableBalance") or a.get("maxWithdrawAmount") or 0)

    def get_balances(self) -> dict[str, float]:
        """Ambil saldo akun futures: wallet balance, margin tersedia, margin balance, uPnL.
        Pakai field top-level /fapi/v2/account; kalau kosong, fallback ke aset USDT."""
        if self.settings.dry_run:
            return {"wallet": 1000.0, "available": 1000.0, "margin_balance": 1000.0, "upnl": 0.0}
        a = self.get_account()

        def _f(*keys):
            for k in keys:
                v = a.get(k)
                if v not in (None, ""):
                    try:
                        return float(v)
                    except Exception:
                        pass
            return None

        wallet = _f("totalWalletBalance")
        avail = _f("availableBalance", "maxWithdrawAmount")
        margin_bal = _f("totalMarginBalance")
        upnl = _f("totalUnrealizedProfit", "totalCrossUnPnl")
        if wallet is None or avail is None or margin_bal is None or upnl is None:
            for asset in (a.get("assets") or []):
                if asset.get("asset") == "USDT":
                    if wallet is None: wallet = float(asset.get("walletBalance") or 0)
                    if avail is None: avail = float(asset.get("availableBalance") or 0)
                    if margin_bal is None: margin_bal = float(asset.get("marginBalance") or 0)
                    if upnl is None: upnl = float(asset.get("unrealizedProfit") or 0)
                    break
        return {
            "wallet": wallet or 0.0,
            "available": avail or 0.0,
            "margin_balance": margin_bal if margin_bal is not None else (wallet or 0.0),
            "upnl": upnl or 0.0,
        }

    def set_leverage(self, symbol: str, leverage: int) -> Any:
        if self.settings.dry_run: return {"dryRun": True, "symbol": symbol, "leverage": leverage}
        return self._request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)

    def klines(self, symbol: str, interval: str, limit: int = 150) -> list:
        return self._request("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    def depth(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        return self._request("GET", "/fapi/v1/depth", {"symbol": symbol, "limit": limit})

    def orderbook_imbalance(self, symbol: str) -> float:
        d = self.depth(symbol, 20)
        bids = sum(float(p) * float(q) for p, q in d.get("bids", []))
        asks = sum(float(p) * float(q) for p, q in d.get("asks", []))
        total = bids + asks
        return 0.0 if total <= 0 else (bids - asks) / total

    def mark_price(self, symbol: str) -> float:
        return float(self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})["markPrice"])

    def book_ticker(self, symbol: str) -> dict[str, Any]:
        if self.settings.dry_run:
            p = self.mark_price(symbol)
            return {"bidPrice": p, "askPrice": p}
        return self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol})

    def spread_pct(self, symbol: str) -> float:
        """Selisih bid-ask sebagai pecahan dari mid price (0.001 = 0.1%)."""
        bt = self.book_ticker(symbol)
        bid = float(bt.get("bidPrice") or 0)
        ask = float(bt.get("askPrice") or 0)
        mid = (bid + ask) / 2
        return 0.0 if mid <= 0 else (ask - bid) / mid

    def funding_rate(self, symbol: str) -> float:
        """lastFundingRate dari premiumIndex (pecahan, mis. 0.0001 = 0.01%)."""
        try:
            r = self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
            return float(r.get("lastFundingRate") or 0)
        except Exception:
            return 0.0

    def open_interest(self, symbol: str) -> float:
        """v11: Open interest terkini (jumlah kontrak terbuka)."""
        try:
            r = self._request("GET", "/fapi/v1/openInterest", {"symbol": symbol})
            return float(r.get("openInterest") or 0)
        except Exception:
            return 0.0

    def open_interest_hist(self, symbol: str, period: str = "5m", limit: int = 6) -> list:
        """v11: Riwayat open interest (utk deteksi penumpukan posisi -> squeeze)."""
        try:
            return self._request("GET", "/futures/data/openInterestHist",
                                 {"symbol": symbol, "period": period, "limit": limit}) or []
        except Exception:
            return []

    def long_short_account_ratio(self, symbol: str, period: str = "5m", limit: int = 2) -> float:
        """v11: Rasio AKUN retail long/short (globalLongShortAccountRatio). GRATIS."""
        try:
            rows = self._request("GET", "/futures/data/globalLongShortAccountRatio",
                                 {"symbol": symbol, "period": period, "limit": limit}) or []
            if rows:
                return float(rows[-1].get("longShortRatio") or 0)
        except Exception:
            pass
        return 0.0

    def top_long_short_position_ratio(self, symbol: str, period: str = "5m", limit: int = 2) -> float:
        """v11: Rasio POSISI top trader long/short (smart money). GRATIS."""
        try:
            rows = self._request("GET", "/futures/data/topLongShortPositionRatio",
                                 {"symbol": symbol, "period": period, "limit": limit}) or []
            if rows:
                return float(rows[-1].get("longShortRatio") or 0)
        except Exception:
            pass
        return 0.0

    def taker_long_short_ratio(self, symbol: str, period: str = "5m", limit: int = 2) -> float:
        """v11: Taker buy/sell volume ratio. GRATIS."""
        try:
            rows = self._request("GET", "/futures/data/takerlongshortRatio",
                                 {"symbol": symbol, "period": period, "limit": limit}) or []
            if rows:
                return float(rows[-1].get("buySellRatio") or 0)
        except Exception:
            pass
        return 0.0

    def entry_limit_order(self, symbol: str, side: str, qty: float, price: float) -> Any:
        """Entry pakai LIMIT order (maker) untuk hindari slippage (DOGE/SOL)."""
        order_side = "BUY" if side.upper() == "LONG" else "SELL"
        params = {
            "symbol": symbol, "side": order_side, "type": "LIMIT",
            "timeInForce": "GTC", "quantity": qty, "price": self.round_price(symbol, price),
        }
        if self.settings.dry_run:
            return {"dryRun": True, "orderId": "DRY", "order": params}
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def order_status(self, symbol: str, order_id: Any) -> dict[str, Any]:
        if self.settings.dry_run:
            return {"status": "FILLED", "executedQty": 0}
        return self._request("GET", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def cancel_order(self, symbol: str, order_id: Any) -> Any:
        if self.settings.dry_run:
            return {"dryRun": True, "symbol": symbol, "orderId": order_id}
        return self._request("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def exchange_info(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        for s in self.exchange_info().get("symbols", []):
            if s.get("symbol") == symbol: return s
        raise RuntimeError(f"Symbol not found: {symbol}")

    @staticmethod
    def _floor_to_step(value: float, step: float) -> float:
        return value if step <= 0 else math.floor(value / step) * step

    @staticmethod
    def _decimals(step: float) -> int:
        # Hitung desimal dari Decimal(str(step)) supaya bebas artefak float (fix -1111).
        try:
            exp = Decimal(str(step)).normalize().as_tuple().exponent
            return max(0, -exp) if isinstance(exp, int) else 0
        except Exception:
            return 0

    def trade_rules(self, symbol: str) -> dict[str, float]:
        if symbol in self._rules_cache:
            return self._rules_cache[symbol]
        info = self.symbol_info(symbol)
        price_precision = int(info.get("pricePrecision", 8) or 8)
        qty_precision = int(info.get("quantityPrecision", 8) or 8)
        min_qty, step, min_notional, tick_size = 0.0, 0.0, 5.0, 0.0
        for f in info.get("filters", []):
            typ = f.get("filterType")
            if typ == "MARKET_LOT_SIZE":
                min_qty = float(f.get("minQty", 0) or 0); step = float(f.get("stepSize", 0) or 0)
            elif typ == "LOT_SIZE" and step == 0:
                min_qty = float(f.get("minQty", 0) or 0); step = float(f.get("stepSize", 0) or 0)
            elif typ == "PRICE_FILTER":
                tick_size = float(f.get("tickSize", 0) or 0)
            elif typ == "MIN_NOTIONAL":
                min_notional = float(f.get("notional", f.get("minNotional", 5)) or 5)
        rules = {"min_qty": min_qty, "step_size": step, "min_notional": min_notional, "tick_size": tick_size, "price_precision": price_precision, "qty_precision": qty_precision}
        self._rules_cache[symbol] = rules
        return rules

    def round_price(self, symbol: str, price: float) -> str:
        """Bulatkan harga trigger ke kelipatan tickSize pakai Decimal (fix error -1111)."""
        rules = self.trade_rules(symbol)
        tick = rules.get("tick_size", 0) or 0
        if tick <= 0:
            pp = int(rules.get("price_precision", 8) or 8)
            return f"{price:.{pp}f}"
        tick_d = Decimal(str(tick))
        price_d = Decimal(str(price))
        rounded = (price_d / tick_d).to_integral_value(rounding=ROUND_DOWN) * tick_d
        return f"{rounded:.{self._decimals(tick)}f}"

    def calc_qty(self, symbol: str, notional: float) -> tuple[float, float, dict[str, float]]:
        price = self.mark_price(symbol); rules = self.trade_rules(symbol)
        step = rules.get("step_size", 0) or 0
        min_qty = rules.get("min_qty", 0) or 0
        min_notional = rules.get("min_notional", 5.0) or 5.0
        # Pakai buffer kecil agar tidak jatuh tepat di bawah minimum notional.
        target = max(notional, min_notional * 1.02)
        if step > 0:
            qty = self._floor_to_step(target / price, step)
            if qty < min_qty:
                qty = min_qty
            # Naikkan per step sampai memenuhi minimum notional (mengatasi error -4164).
            guard = 0
            while qty * price < min_notional and guard < 1000:
                qty += step
                guard += 1
            qty = round(qty, self._decimals(step))
        else:
            qty = max(target / price, min_qty)
        return qty, price, rules

    # ---------------- orders ----------------
    def entry_order(self, symbol: str, side: str, qty: float) -> Any:
        order_side = "BUY" if side.upper() == "LONG" else "SELL"
        params = {"symbol": symbol, "side": order_side, "type": "MARKET", "quantity": qty}
        if self.settings.dry_run: return {"dryRun": True, "order": params}
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def _close_side(self, side: str) -> str:
        return "SELL" if side.upper() == "LONG" else "BUY"

    def _protective_order(self, symbol: str, side: str, order_type: str, stop_price: float, qty: float | None = None) -> Any:
        """Pasang SL/TP via Algo Order API Binance (/fapi/v1/algoOrder).
        WAJIB sejak migrasi Binance 2025-12-09: STOP_MARKET/TAKE_PROFIT_MARKET
        ditolak di /fapi/v1/order dengan error -4120 (STOP_ORDER_SWITCH_ALGO).
        Berlapis biar tahan banting:
          1) closePosition=true (mode one-way, tutup seluruh posisi)
          2) + positionSide (kalau akun mode HEDGE, error -4061)
          3) reduceOnly + quantity (kalau closePosition ditolak)
        """
        close_side = self._close_side(side)
        trig = self.round_price(symbol, stop_price)
        base = {
            "symbol": symbol,
            "side": close_side,
            "algoType": "CONDITIONAL",
            "type": order_type,
            "triggerPrice": trig,
            "workingType": "MARK_PRICE",
        }
        if self.settings.dry_run:
            return {"dryRun": True, "order": {**base, "closePosition": "true"}}
        try:
            return self._request("POST", "/fapi/v1/algoOrder", {**base, "closePosition": "true"}, signed=True)
        except RuntimeError as e1:
            msg = str(e1)
            # Akun mode HEDGE wajib positionSide.
            if "-4061" in msg or "position side" in msg.lower():
                ps = "LONG" if side.upper() == "LONG" else "SHORT"
                try:
                    return self._request("POST", "/fapi/v1/algoOrder", {**base, "closePosition": "true", "positionSide": ps}, signed=True)
                except RuntimeError:
                    pass
            # Fallback: reduceOnly + quantity (butuh qty posisi; tidak boleh di mode hedge).
            if qty and qty > 0:
                ro = {**base, "quantity": qty, "reduceOnly": "true"}
                return self._request("POST", "/fapi/v1/algoOrder", ro, signed=True)
            raise

    def stop_loss_order(self, symbol: str, side: str, stop_price: float, qty: float | None = None) -> Any:
        """Stop Loss Futures USDⓈ-M (STOP_MARKET via Algo Order API)."""
        return self._protective_order(symbol, side, "STOP_MARKET", stop_price, qty)

    def take_profit_order(self, symbol: str, side: str, stop_price: float, qty: float | None = None) -> Any:
        """Take Profit Futures USDⓈ-M (TAKE_PROFIT_MARKET via Algo Order API)."""
        return self._protective_order(symbol, side, "TAKE_PROFIT_MARKET", stop_price, qty)

    def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Daftar algo order (SL/TP) aktif via /fapi/v1/openAlgoOrders.
        Normalisasi field 'type' dari 'orderType'/'strategyType' supaya deteksi SL/TP konsisten."""
        if self.settings.dry_run: return []
        params: dict[str, Any] = {}
        if symbol: params["symbol"] = symbol
        res = self._request("GET", "/fapi/v1/openAlgoOrders", params, signed=True)
        orders: list[dict[str, Any]] = []
        if isinstance(res, list):
            orders = res
        elif isinstance(res, dict):
            for key in ("orders", "data", "rows"):
                if isinstance(res.get(key), list):
                    orders = res[key]; break
        for o in orders:
            if isinstance(o, dict) and not o.get("type"):
                o["type"] = o.get("orderType") or o.get("strategyType")
        return orders

    @staticmethod
    def _algo_id(order: dict[str, Any]) -> Any:
        return order.get("algoId") or order.get("orderId") or order.get("clientAlgoId")

    def cancel_algo_order(self, symbol: str, algo_id: Any) -> Any:
        """Batalkan satu algo order berdasarkan algoId (endpoint /fapi/v1/algoOrder)."""
        if self.settings.dry_run: return {"dryRun": True, "symbol": symbol, "algoId": algo_id}
        return self._request("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": algo_id}, signed=True)

    def cancel_stop_loss_orders(self, symbol: str) -> int:
        """Batalkan semua STOP_MARKET aktif pada simbol. Return jumlah yang dibatalkan."""
        cancelled = 0
        for o in self.open_algo_orders(symbol):
            otype = str(o.get("type") or o.get("strategyType") or "").upper()
            if "STOP" in otype and "TAKE_PROFIT" not in otype:
                aid = self._algo_id(o)
                if aid is not None:
                    self.cancel_algo_order(symbol, aid)
                    cancelled += 1
        return cancelled

    def cancel_all_algo_orders(self, symbol: str) -> int:
        """Batalkan SEMUA algo order (SL & TP) pada simbol. Return jumlah yang dibatalkan."""
        cancelled = 0
        for o in self.open_algo_orders(symbol):
            aid = self._algo_id(o)
            if aid is not None:
                self.cancel_algo_order(symbol, aid)
                cancelled += 1
        return cancelled

    def close_position_market(self, symbol: str, side: str, qty: float) -> Any:
        """Tutup posisi di harga market (reduceOnly) — auto rounding step_size."""
        order_side = self._close_side(side)
        rules = self.trade_rules(symbol)
        step = rules.get("step_size", 0) or 0
        if step > 0:
            qty = self._floor_to_step(qty, step)
            qty = round(qty, self._decimals(step))
        params = {"symbol": symbol, "side": order_side, "type": "MARKET", "quantity": qty, "reduceOnly": "true"}
        if self.settings.dry_run: return {"dryRun": True, "order": params}
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    # ---------------- positions / pnl ----------------
    def positions(self) -> list[dict[str, Any]]:
        if self.settings.dry_run: return []
        return self._request("GET", "/fapi/v2/positionRisk", signed=True)

    def open_positions(self) -> list[dict[str, Any]]:
        return [p for p in self.positions() if float(p.get("positionAmt", 0) or 0) != 0]

    def income_today(self) -> list[dict[str, Any]]:
        if self.settings.dry_run: return []
        now = datetime.now(timezone.utc); start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        return self._request("GET", "/fapi/v1/income", {"startTime": int(start.timestamp() * 1000), "limit": 1000}, signed=True)
