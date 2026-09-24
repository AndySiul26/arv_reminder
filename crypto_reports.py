"""Lista personal e informes directos de mercados en varios exchanges."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests

import crypto_alerts
import crypto_smart
import crypto_strength
from services import enviar_telegram


TIMEFRAMES = (
    ("1m", 60), ("5m", 300), ("30m", 1800),
    ("1h", 3600), ("4h", 14400), ("1d", 86400),
)
MAX_MARKETS = max(1, min(30, int(os.getenv("CRYPTO_REPORT_MAX_MARKETS", "20"))))
BITSO_MAX_PAGES = max(1, min(20, int(os.getenv("CRYPTO_REPORT_BITSO_PAGES", "8"))))
MESSAGE_LIMIT = 3800
BINANCE_API_BASE_URL = os.getenv(
    "BINANCE_API_BASE_URL", "https://api.binance.com/api/v3"
).rstrip("/")
BINANCE_API_FALLBACK_URL = os.getenv(
    "BINANCE_API_FALLBACK_URL", "https://data-api.binance.vision/api/v3"
).rstrip("/")
BINANCE_COMPARABLE_QUOTES = tuple(
    quote.strip().upper()
    for quote in os.getenv(
        "BINANCE_COMPARABLE_QUOTES", "USD,USDT,USDC,TUSD"
    ).split(",")
    if quote.strip()
)
_cache = {}
_cache_lock = threading.Lock()
_binance_markets_cache = {"expires": 0, "items": []}
_binance_markets_lock = threading.Lock()


def _db():
    return crypto_alerts._db()


def listar_mercados(chat_id):
    try:
        rows = (_db().table("cripto_mercados_usuario").select("book")
                .eq("chat_id", str(chat_id)).order("creado_en").execute().data or [])
        return [row["book"] for row in rows]
    except Exception as exc:
        print(f"[ERROR] No se obtuvo lista de mercados: {exc}")
        return []


def detectar_fuentes(book):
    sources = []
    try:
        if book in set(crypto_alerts.obtener_libros_bitso()):
            crypto_alerts.obtener_ticker_bitso(book)
            sources.append("bitso")
    except Exception:
        pass
    try:
        crypto_strength.validar_producto(book)
        sources.append("coinbase_exchange")
    except Exception:
        pass
    try:
        sources.extend(
            f"binance:{item['symbol'].lower()}"
            for item in _binance_comparable_markets(book)
        )
    except Exception:
        pass
    return sources


def agregar_mercado(chat_id, book):
    book = str(book or "").strip().lower().replace("/", "_").replace("-", "_").replace(" ", "")
    if not re.fullmatch(r"[a-z0-9]{2,20}_[a-z0-9]{2,20}", book):
        return None, "Escribe un par como ADA/USD."
    existing = listar_mercados(chat_id)
    if book in existing:
        return book, "Ese mercado ya está en tu lista."
    if len(existing) >= MAX_MARKETS:
        return None, f"Puedes guardar hasta {MAX_MARKETS} mercados."
    sources = detectar_fuentes(book)
    warning = None
    if not sources:
        warning = (
            "Mercado guardado, pero hoy ningún exchange configurado publica "
            "ese par exacto; el informe lo mostrará como no disponible."
        )
    try:
        _db().table("cripto_mercados_usuario").insert({
            "chat_id": str(chat_id), "book": book, "fuentes_detectadas": sources,
        }).execute()
        return book, warning
    except Exception as exc:
        print(f"[ERROR] No se agregó mercado: {exc}")
        return None, "No pude guardar el mercado."


def quitar_mercado(chat_id, book):
    try:
        rows = (_db().table("cripto_mercados_usuario").delete()
                .eq("chat_id", str(chat_id)).eq("book", str(book).lower()).execute().data)
        return bool(rows)
    except Exception:
        return False


def _parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _format(value):
    return "n/d" if value is None else crypto_alerts.formatear_precio(value)


def _weighted_average(items, price_key="price", weight_key="amount"):
    total_value = Decimal("0")
    total_weight = Decimal("0")
    for item in items:
        try:
            price = Decimal(str(item[price_key]))
            weight = Decimal(str(item[weight_key]))
        except (KeyError, InvalidOperation, TypeError):
            continue
        if price > 0 and weight > 0:
            total_value += price * weight
            total_weight += weight
    return total_value / total_weight if total_weight > 0 else None


def _bitso_trades(book):
    trades, marker = [], None
    for _ in range(BITSO_MAX_PAGES):
        params = {"book": book, "limit": 100, "sort": "desc"}
        if marker is not None:
            params["marker"] = marker
        payload = crypto_alerts._bitso_get("trades", params=params) or []
        if not payload:
            break
        trades.extend(payload)
        new_marker = payload[-1].get("tid")
        if new_marker is None or str(new_marker) == str(marker):
            break
        marker = new_marker
        oldest = _parse_time(payload[-1].get("created_at"))
        if oldest and datetime.now(timezone.utc) - oldest >= timedelta(days=1):
            break
        if len(payload) < 100:
            break
    unique = {str(item.get("tid")): item for item in trades if item.get("tid") is not None}
    return list(unique.values())


def _bitso_report(book):
    payload = crypto_alerts._bitso_get("ticker", params={"book": book})
    if not payload or str(payload.get("book", "")).lower() != book:
        raise RuntimeError("Ticker Bitso inválido")
    trades = _bitso_trades(book)
    now = datetime.now(timezone.utc)
    dated = [(item, _parse_time(item.get("created_at"))) for item in trades]
    dated = [(item, stamp) for item, stamp in dated if stamp]
    oldest = min((stamp for _, stamp in dated), default=None)
    averages = {}
    partial = {}
    for label, seconds in TIMEFRAMES:
        cutoff = now - timedelta(seconds=seconds)
        window = [item for item, stamp in dated if stamp >= cutoff]
        averages[label] = _weighted_average(window)
        partial[label] = bool(oldest and oldest > cutoff)
    return {
        "provider": "Bitso", "last": Decimal(str(payload["last"])),
        "averages": averages, "partial": partial,
        "vwap_24h": Decimal(str(payload["vwap"])) if payload.get("vwap") else None,
        "samples": len(dated),
        "coverage": (now - oldest).total_seconds() if oldest else 0,
        "method": "VWAP de trades",
    }


def _coinbase_ticker(book):
    product = crypto_strength._product_id(book)
    response = requests.get(
        f"{crypto_smart.API_URL}/products/{product}/ticker",
        headers=crypto_smart._headers(), timeout=crypto_smart.TIMEOUT,
    )
    if response.status_code in (400, 404):
        raise crypto_strength.AnalisisNoDisponibleError(f"Coinbase no publica {product}")
    response.raise_for_status()
    return Decimal(str(response.json()["price"]))


def _candle_average(candles, cutoff):
    selected = [item for item in candles if item["time"] >= cutoff]
    total, volume = Decimal("0"), Decimal("0")
    for item in selected:
        typical = (item["high"] + item["low"] + item["close"]) / Decimal("3")
        weight = item["volume"]
        if weight > 0:
            total += typical * weight
            volume += weight
    return total / volume if volume > 0 else None


def _coinbase_report(book):
    now = datetime.now(timezone.utc)
    short = crypto_smart._request_candles(book, 60, 300)
    long = crypto_smart._request_candles(book, 300, 300)
    if not short:
        raise RuntimeError("Coinbase no devolvió velas")
    averages = {}
    for label, seconds in TIMEFRAMES:
        source = short if seconds <= 14400 else long
        averages[label] = _candle_average(source, int(now.timestamp()) - seconds)
    return {
        "provider": "Coinbase Exchange", "last": _coinbase_ticker(book),
        "averages": averages, "partial": {label: False for label, _ in TIMEFRAMES},
        "vwap_24h": None, "samples": len(short) + len(long),
        "coverage": 86400, "method": "promedio OHLC típico ponderado por volumen",
    }


def _binance_get(path, params=None):
    last_error = None
    endpoints = dict.fromkeys((BINANCE_API_BASE_URL, BINANCE_API_FALLBACK_URL))
    for endpoint in endpoints:
        try:
            response = requests.get(
                f"{endpoint}/{path.lstrip('/')}",
                params=params,
                headers={"User-Agent": "ARV-Reminder/4.0 market-reports"},
                timeout=crypto_smart.TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("No hay endpoints públicos de Binance configurados")


def _binance_markets():
    """Devuelve mercados spot activos de Binance con caché de una hora."""
    now = time.time()
    with _binance_markets_lock:
        if _binance_markets_cache["expires"] > now:
            return list(_binance_markets_cache["items"])
    payload = _binance_get("exchangeInfo")
    markets = [
        item for item in payload.get("symbols", [])
        if item.get("status") == "TRADING"
        and item.get("isSpotTradingAllowed", True)
    ]
    with _binance_markets_lock:
        _binance_markets_cache["items"] = markets
        _binance_markets_cache["expires"] = now + 3600
    return list(markets)


def _binance_comparable_markets(book):
    """Encuentra el par exacto y equivalentes USD sin ocultar su cotización."""
    base, requested_quote = str(book).upper().split("_", 1)
    if requested_quote in BINANCE_COMPARABLE_QUOTES:
        quotes = set(BINANCE_COMPARABLE_QUOTES)
    else:
        quotes = {requested_quote}
    rank = {quote: index for index, quote in enumerate(BINANCE_COMPARABLE_QUOTES)}
    matches = [
        item for item in _binance_markets()
        if item.get("baseAsset") == base and item.get("quoteAsset") in quotes
    ]
    return sorted(
        matches,
        key=lambda item: (
            0 if item.get("quoteAsset") == requested_quote else 1,
            rank.get(item.get("quoteAsset"), 999),
        ),
    )


def _binance_klines(symbol, interval, limit):
    rows = _binance_get(
        "klines", params={"symbol": symbol, "interval": interval, "limit": limit}
    )
    result = []
    for row in rows:
        try:
            result.append({
                "time": int(row[0]) // 1000,
                "base_volume": Decimal(str(row[5])),
                "quote_volume": Decimal(str(row[7])),
            })
        except (IndexError, InvalidOperation, TypeError, ValueError):
            continue
    return result


def _binance_vwap(candles, cutoff):
    selected = [item for item in candles if item["time"] >= cutoff]
    base_volume = sum(
        (item["base_volume"] for item in selected), Decimal("0")
    )
    quote_volume = sum(
        (item["quote_volume"] for item in selected), Decimal("0")
    )
    return quote_volume / base_volume if base_volume > 0 else None


def _binance_report(market, requested_book):
    symbol = market["symbol"]
    short = _binance_klines(symbol, "1m", 1000)
    long = _binance_klines(symbol, "5m", 300)
    if not short:
        raise RuntimeError(f"Binance no devolvió velas para {symbol}")
    now = int(datetime.now(timezone.utc).timestamp())
    averages = {}
    partial = {}
    for label, seconds in TIMEFRAMES:
        source = short if seconds <= 14400 else long
        averages[label] = _binance_vwap(source, now - seconds)
        oldest = min((item["time"] for item in source), default=now)
        partial[label] = oldest > now - seconds
    trades = _binance_get("trades", params={"symbol": symbol, "limit": 1})
    if not trades:
        raise RuntimeError(f"Binance no devolvió el último trade de {symbol}")
    requested_quote = requested_book.upper().split("_", 1)[1]
    actual_quote = market["quoteAsset"]
    return {
        "provider": f"Binance Spot · {market['baseAsset']}/{actual_quote}",
        "last": Decimal(str(trades[-1]["price"])),
        "averages": averages,
        "partial": partial,
        "vwap_24h": None,
        "samples": len(short) + len(long),
        "coverage": max(
            0, now - min((item["time"] for item in long), default=now)
        ),
        "method": "VWAP de velas por volumen negociado",
        "quote_note": (
            None if actual_quote == requested_quote else
            f"Comparativa en {actual_quote}; no es {requested_quote} exacto."
        ),
    }


def _duration(seconds):
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{max(0, seconds) / 60:.0f} min"


def _source_block(data):
    lines = [
        f"🏦 {data['provider']}",
        f"Último trade: {_format(data['last'])}",
        f"Promedios ({data['method']}):",
    ]
    for index in range(0, len(TIMEFRAMES), 3):
        parts = []
        for label, _ in TIMEFRAMES[index:index + 3]:
            suffix = "*" if data["partial"].get(label) and data["averages"].get(label) is not None else ""
            parts.append(f"{label} {_format(data['averages'].get(label))}{suffix}")
        lines.append(" · ".join(parts))
    if data.get("vwap_24h") is not None:
        lines.append(f"VWAP oficial 24 h: {_format(data['vwap_24h'])}")
    if any(data["partial"].values()):
        lines.append(f"* parcial; trades disponibles: {data['samples']} / cobertura {_duration(data['coverage'])}")
    if data.get("quote_note"):
        lines.append(f"ℹ️ {data['quote_note']}")
    return "\n".join(lines)


def reporte_mercado(book):
    with _cache_lock:
        cached = _cache.get(book)
        if cached and time.time() - cached[0] < 30:
            return cached[1]
    blocks = [f"💎 {crypto_alerts.nombre_book(book)}"]
    found = False
    try:
        if book in set(crypto_alerts.obtener_libros_bitso()):
            blocks.append(_source_block(_bitso_report(book)))
            found = True
        else:
            blocks.append("🏦 Bitso: par no disponible")
    except Exception as exc:
        blocks.append(f"🏦 Bitso: información temporalmente no disponible ({type(exc).__name__})")
    try:
        crypto_strength.validar_producto(book)
        blocks.append(_source_block(_coinbase_report(book)))
        found = True
    except Exception:
        if not found:
            blocks.append("🏦 Coinbase Exchange: par no disponible")
    try:
        binance_markets = _binance_comparable_markets(book)
        if binance_markets:
            for market in binance_markets:
                try:
                    blocks.append(_source_block(_binance_report(market, book)))
                    found = True
                except Exception as exc:
                    blocks.append(
                        f"🏦 Binance Spot · {market['baseAsset']}/{market['quoteAsset']}: "
                        f"información temporalmente no disponible ({type(exc).__name__})"
                    )
        else:
            blocks.append("🏦 Binance Spot: par o equivalente USD no disponible")
    except Exception as exc:
        blocks.append(
            "🏦 Binance Spot: información temporalmente no disponible "
            f"({type(exc).__name__})"
        )
    text = "\n\n".join(blocks)
    with _cache_lock:
        _cache[book] = (time.time(), text)
    return text


def dividir_informe(header, blocks, limit=MESSAGE_LIMIT):
    chunks, current = [], header
    for block in blocks:
        candidate = current + "\n\n" + block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current != header:
            chunks.append(current)
            current = header + "\n\n" + block
        else:
            lines, piece = block.splitlines(), header
            for line in lines:
                if len(piece) + len(line) + 1 > limit:
                    chunks.append(piece)
                    piece = header + "\n\n" + line
                else:
                    piece += "\n" + line
            current = piece
    if current:
        chunks.append(current)
    return chunks


def generar_informe(chat_id):
    markets = listar_mercados(chat_id)
    if not markets:
        return []
    blocks = [reporte_mercado(book) for book in markets]
    header = (
        "📊 INFORME DE MERCADOS\n"
        f"Consultado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        "Los promedios con * tienen cobertura parcial."
    )
    return dividir_informe(header, blocks)


def generar_y_enviar(chat_id):
    try:
        chunks = generar_informe(chat_id)
        if not chunks:
            enviar_telegram(chat_id, tipo="texto", mensaje="Tu lista de mercados está vacía.")
            return
        for index, chunk in enumerate(chunks, 1):
            prefix = f"Parte {index}/{len(chunks)}\n\n" if len(chunks) > 1 else ""
            enviar_telegram(chat_id, tipo="texto", mensaje=prefix + chunk)
    except Exception as exc:
        print(f"[ERROR] Informe de mercados: {exc}")
        enviar_telegram(chat_id, tipo="texto", mensaje="No pude completar el informe en este momento.")


def iniciar_informe_async(chat_id):
    thread = threading.Thread(
        target=generar_y_enviar, args=(str(chat_id),),
        name=f"market-report-{chat_id}", daemon=True,
    )
    thread.start()
    return thread
