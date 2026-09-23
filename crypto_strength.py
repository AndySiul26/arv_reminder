"""Alertas de cambio porcentual e impulso usando velas de Coinbase Exchange."""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests

import crypto_alerts
from services import enviar_mensaje_con_grid


COINBASE_EXCHANGE_URL = os.getenv(
    "COINBASE_EXCHANGE_URL", "https://api.exchange.coinbase.com"
).rstrip("/")
STRENGTH_TIMEOUT_SECONDS = int(os.getenv("CRYPTO_STRENGTH_TIMEOUT_SECONDS", "10"))
STRENGTH_INTERVAL_SECONDS = max(
    60, int(os.getenv("CRYPTO_STRENGTH_INTERVAL_SECONDS", "60"))
)
STRENGTH_CONSTANT_INTERVAL_SECONDS = max(
    60, int(os.getenv("CRYPTO_STRENGTH_CONSTANT_INTERVAL_SECONDS", "60"))
)
MIN_BASELINE_CHANGE = Decimal("0.05")

TIMEFRAMES = {
    "1m": {"seconds": 60, "granularity": 60, "label": "1 minuto"},
    "5m": {"seconds": 300, "granularity": 60, "label": "5 minutos"},
    "30m": {"seconds": 1800, "granularity": 300, "label": "30 minutos"},
    "1h": {"seconds": 3600, "granularity": 300, "label": "1 hora"},
    "4h": {"seconds": 14400, "granularity": 3600, "label": "4 horas"},
    "1d": {"seconds": 86400, "granularity": 3600, "label": "1 día"},
}


class AnalisisNoDisponibleError(RuntimeError):
    pass


def _headers():
    return {"User-Agent": "ARV-Reminder/4.0 strength-alerts"}


def _product_id(book):
    base, separator, quote = str(book).strip().lower().partition("_")
    if not separator or not base or not quote:
        raise AnalisisNoDisponibleError("Par inválido")
    return f"{base.upper()}-{quote.upper()}"


def validar_producto(book):
    product_id = _product_id(book)
    try:
        response = requests.get(
            f"{COINBASE_EXCHANGE_URL}/products/{product_id}",
            headers=_headers(),
            timeout=STRENGTH_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AnalisisNoDisponibleError("Coinbase Exchange no respondió") from exc
    if response.status_code in (400, 404):
        raise AnalisisNoDisponibleError(
            f"Coinbase Exchange no publica {product_id}"
        )
    response.raise_for_status()
    data = response.json()
    if (
        data.get("id") != product_id
        or data.get("base_currency") != product_id.split("-", 1)[0]
        or data.get("quote_currency") != product_id.split("-", 1)[1]
        or data.get("status") != "online"
    ):
        raise AnalisisNoDisponibleError(f"Producto no disponible: {product_id}")
    return data


def obtener_analisis(book, temporalidad, ahora=None):
    """Calcula el cambio móvil de precio para el par y la temporalidad."""
    config = TIMEFRAMES.get(str(temporalidad))
    if not config:
        raise ValueError("Temporalidad no soportada")
    product_id = _product_id(book)
    ahora = ahora or datetime.now(timezone.utc)
    target_ts = int(ahora.timestamp()) - config["seconds"]
    granularity = config["granularity"]
    start_ts = target_ts - (granularity * 3)
    params = {
        "granularity": granularity,
        "start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
        "end": ahora.isoformat(),
    }
    try:
        candle_response = requests.get(
            f"{COINBASE_EXCHANGE_URL}/products/{product_id}/candles",
            params=params,
            headers=_headers(),
            timeout=STRENGTH_TIMEOUT_SECONDS,
        )
        ticker_response = requests.get(
            f"{COINBASE_EXCHANGE_URL}/products/{product_id}/ticker",
            headers=_headers(),
            timeout=STRENGTH_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AnalisisNoDisponibleError(
            f"No se pudo consultar {product_id}"
        ) from exc
    if candle_response.status_code in (400, 404) or ticker_response.status_code in (
        400,
        404,
    ):
        raise AnalisisNoDisponibleError(
            f"Coinbase Exchange no ofrece histórico para {product_id}"
        )
    candle_response.raise_for_status()
    ticker_response.raise_for_status()
    candles = candle_response.json()
    ticker = ticker_response.json()
    if not candles:
        raise AnalisisNoDisponibleError("No hay velas suficientes")
    try:
        # Cada timestamp es el inicio de la vela. Se toma el cierre más cercano
        # al instante de referencia sin usar una vela futura.
        completed = [
            candle for candle in candles
            if int(candle[0]) + granularity <= int(ahora.timestamp())
        ]
        if not completed:
            raise AnalisisNoDisponibleError("No hay velas cerradas")
        candle = min(
            completed,
            key=lambda item: abs((int(item[0]) + granularity) - target_ts),
        )
        reference_price = Decimal(str(candle[4]))
        current_price = Decimal(str(ticker["price"]))
    except (IndexError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise AnalisisNoDisponibleError("Datos históricos inválidos") from exc
    if reference_price <= 0 or current_price <= 0:
        raise AnalisisNoDisponibleError("Precio histórico inválido")
    change = ((current_price / reference_price) - Decimal("1")) * Decimal("100")
    reference_time = datetime.fromtimestamp(
        int(candle[0]) + granularity, timezone.utc
    )
    return {
        "book": str(book).lower(),
        "product_id": product_id,
        "temporalidad": str(temporalidad),
        "temporalidad_label": config["label"],
        "precio_actual": current_price,
        "precio_referencia": reference_price,
        "cambio_pct": change,
        "referencia_en": reference_time.isoformat(),
        "consultado_en": ahora.isoformat(),
        "provider": "coinbase_exchange",
        "provider_label": "Coinbase Exchange",
        "price_type": "ticker y cierre de vela",
    }


def calcular_variacion_fuerza(cambio_actual, cambio_referencia):
    actual = Decimal(str(cambio_actual))
    referencia = Decimal(str(cambio_referencia))
    if abs(referencia) < MIN_BASELINE_CHANGE:
        return None
    return ((actual - referencia) / abs(referencia)) * Decimal("100")


def evaluar_condicion(alerta, analisis):
    actual = Decimal(str(analisis["cambio_pct"]))
    referencia = Decimal(str(alerta["cambio_referencia_pct"]))
    mode = alerta.get("modo", "fuerza")
    hits = []
    fuerza = calcular_variacion_fuerza(actual, referencia)
    if mode in ("fuerza", "ambos") and fuerza is not None:
        threshold = Decimal(str(alerta.get("umbral_pct") or 20))
        if fuerza <= -threshold:
            hits.append("fuerza_baja")
        elif fuerza >= threshold:
            hits.append("fuerza_alta")
    if mode in ("cruce_cero", "ambos"):
        if referencia > 0 and actual <= 0:
            hits.append("cruce_bajista")
        elif referencia < 0 and actual >= 0:
            hits.append("cruce_alcista")
    return hits, fuerza


def crear_alerta(
    chat_id,
    usuario,
    book,
    temporalidad,
    modo,
    cambio_referencia_pct,
    precio_referencia,
    umbral_pct=None,
    aviso_constante=False,
):
    client = crypto_alerts._db()
    if not client:
        return None
    payload = {
        "chat_id": str(chat_id),
        "usuario": usuario,
        "book": str(book).lower(),
        "temporalidad": temporalidad,
        "modo": modo,
        "umbral_pct": str(umbral_pct) if umbral_pct is not None else None,
        "cambio_referencia_pct": str(cambio_referencia_pct),
        "precio_referencia_inicial": str(precio_referencia),
        "aviso_constante": bool(aviso_constante),
        "aviso_detenido": False,
        "condicion_activa": False,
        "estado": "activa",
        "fuente": "coinbase_exchange",
    }
    try:
        response = client.table("cripto_fuerza_alertas").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as exc:
        print(f"[ERROR] No se pudo crear alerta de fuerza: {exc}")
        return None


def listar_alertas(chat_id, solo_activas=False):
    client = crypto_alerts._db()
    if not client:
        return []
    try:
        query = (
            client.table("cripto_fuerza_alertas")
            .select("*")
            .eq("chat_id", str(chat_id))
        )
        if solo_activas:
            query = query.eq("estado", "activa")
        return query.order("id", desc=True).execute().data or []
    except Exception as exc:
        print(f"[ERROR] No se pudieron listar alertas de fuerza: {exc}")
        return []


def obtener_alerta(alerta_id, chat_id):
    client = crypto_alerts._db()
    if not client:
        return None
    try:
        rows = (
            client.table("cripto_fuerza_alertas")
            .select("*")
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception:
        return None


def eliminar_alerta(alerta_id, chat_id):
    client = crypto_alerts._db()
    if not client:
        return False
    try:
        rows = (
            client.table("cripto_fuerza_alertas")
            .delete()
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .execute()
            .data
        )
        return bool(rows)
    except Exception:
        return False


def detener_constante(alerta_id, chat_id):
    client = crypto_alerts._db()
    if not client:
        return False
    try:
        rows = (
            client.table("cripto_fuerza_alertas")
            .update({"aviso_detenido": True, "actualizado_en": datetime.now(timezone.utc).isoformat()})
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .eq("aviso_constante", True)
            .execute()
            .data
        )
        return bool(rows)
    except Exception:
        return False


def recalibrar_alerta(alerta_id, chat_id):
    alerta = obtener_alerta(alerta_id, chat_id)
    if not alerta:
        return None
    analisis = obtener_analisis(alerta["book"], alerta["temporalidad"])
    if alerta.get("modo") in ("fuerza", "ambos") and abs(
        analisis["cambio_pct"]
    ) < MIN_BASELINE_CHANGE:
        raise ValueError("El cambio actual está demasiado cerca de cero")
    client = crypto_alerts._db()
    payload = {
        "cambio_referencia_pct": str(analisis["cambio_pct"]),
        "precio_referencia_inicial": str(analisis["precio_actual"]),
        "condicion_activa": False,
        "aviso_detenido": False,
        "lado_activo": None,
        "ultima_notificacion_en": None,
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    rows = (
        client.table("cripto_fuerza_alertas")
        .update(payload)
        .eq("id", int(alerta_id))
        .eq("chat_id", str(chat_id))
        .execute()
        .data
    )
    return (rows[0], analisis) if rows else None


def _fmt(value, places=2):
    value = Decimal(str(value))
    return f"{value:+.{places}f}%"


def mensaje_alerta(alerta, analisis, hits, fuerza, repeticion=False):
    labels = {
        "fuerza_baja": "📉 La fuerza disminuyó",
        "fuerza_alta": "📈 La fuerza aumentó",
        "cruce_bajista": "🔻 El cambio cruzó a 0% o negativo",
        "cruce_alcista": "🔺 El cambio cruzó a 0% o positivo",
    }
    title = "📢 ALERTA CONSTANTE DE FUERZA" if alerta.get(
        "aviso_constante"
    ) else "⚡ ALERTA DE FUERZA"
    if repeticion:
        title += " · RECORDATORIO"
    hit_text = "\n".join(labels[item] for item in hits)
    fuerza_text = _fmt(fuerza) if fuerza is not None else "no aplica"
    return (
        f"{title}\n\n{hit_text}\n\n"
        f"💎 Mercado: {crypto_alerts.nombre_book(alerta['book'])}\n"
        f"⏱ Temporalidad: {TIMEFRAMES[alerta['temporalidad']]['label']}\n"
        f"💰 Precio actual: {crypto_alerts.formatear_precio(analisis['precio_actual'])}\n"
        f"🕰 Precio al inicio de la ventana: {crypto_alerts.formatear_precio(analisis['precio_referencia'])}\n"
        f"📊 Cambio actual del precio: {_fmt(analisis['cambio_pct'])}\n"
        f"📌 Cambio usado como referencia: {_fmt(alerta['cambio_referencia_pct'])}\n"
        f"🧭 Variación de fuerza: {fuerza_text}\n\n"
        "🏦 Fuente: Coinbase Exchange\n"
        f"📍 Tipo: {analisis['price_type']}\n"
        f"🕐 Consultado: {analisis['consultado_en']}\n\n"
        "Información de mercado; no constituye asesoría financiera."
    )


class MonitorFuerzaCripto:
    def __init__(self, interval_seconds=STRENGTH_INTERVAL_SECONDS):
        self.interval_seconds = max(60, int(interval_seconds))
        self.activo = False
        self.hilo = None
        self._stop = threading.Event()

    def iniciar(self):
        if self.activo:
            return
        self.activo = True
        self._stop.clear()
        self.hilo = threading.Thread(
            target=self._run, name="crypto-strength-monitor", daemon=True
        )
        self.hilo.start()
        print(f"Monitor de fuerza cripto iniciado (cada {self.interval_seconds}s)")

    def detener(self):
        self.activo = False
        self._stop.set()
        if self.hilo:
            self.hilo.join(timeout=2)

    def _run(self):
        while self.activo:
            try:
                self.verificar_una_vez()
            except Exception as exc:
                print(f"[ERROR] Ciclo de fuerza cripto: {exc}")
            self._stop.wait(self.interval_seconds)

    def verificar_una_vez(self):
        client = crypto_alerts._db()
        if not client:
            return 0
        try:
            alertas = (
                client.table("cripto_fuerza_alertas")
                .select("*")
                .eq("estado", "activa")
                .execute()
                .data
                or []
            )
        except Exception as exc:
            print(f"[WARN] No se consultaron alertas de fuerza: {exc}")
            return 0
        grouped = {}
        for alerta in alertas:
            grouped.setdefault(
                (alerta["book"], alerta["temporalidad"]), []
            ).append(alerta)
        enviados = 0
        now = datetime.now(timezone.utc)
        for (book, timeframe), items in grouped.items():
            try:
                analysis = obtener_analisis(book, timeframe, ahora=now)
            except Exception as exc:
                print(f"[WARN] Análisis no disponible para {book}/{timeframe}: {exc}")
                continue
            for alerta in items:
                hits, fuerza = evaluar_condicion(alerta, analysis)
                active_before = bool(alerta.get("condicion_activa"))
                updates = {
                    "ultimo_cambio_pct": str(analysis["cambio_pct"]),
                    "ultima_fuerza_pct": str(fuerza) if fuerza is not None else None,
                    "ultimo_precio": str(analysis["precio_actual"]),
                    "ultima_consulta_en": analysis["consultado_en"],
                    "actualizado_en": now.isoformat(),
                }
                if not hits:
                    updates.update({
                        "condicion_activa": False,
                        "lado_activo": None,
                        "aviso_detenido": False,
                    })
                    client.table("cripto_fuerza_alertas").update(updates).eq(
                        "id", alerta["id"]
                    ).execute()
                    continue
                should_send = not active_before
                repetition = False
                if alerta.get("aviso_constante") and not alerta.get("aviso_detenido"):
                    last = crypto_alerts._parse_datetime(
                        alerta.get("ultima_notificacion_en")
                    )
                    if not active_before or last is None or (
                        now - last
                    ).total_seconds() >= STRENGTH_CONSTANT_INTERVAL_SECONDS:
                        should_send = True
                        repetition = active_before
                elif alerta.get("aviso_detenido"):
                    should_send = False
                updates.update({
                    "condicion_activa": True,
                    "lado_activo": ",".join(hits),
                })
                if should_send:
                    rows = []
                    if alerta.get("aviso_constante"):
                        rows = [[{
                            "texto": "🛑 Detener este aviso",
                            "data": f"strength_stop:{alerta['id']}",
                        }]]
                    response = enviar_mensaje_con_grid(
                        alerta["chat_id"],
                        mensaje_alerta(alerta, analysis, hits, fuerza, repetition),
                        rows,
                    )
                    if response and response.status_code == 200:
                        updates["ultima_notificacion_en"] = now.isoformat()
                        enviados += 1
                client.table("cripto_fuerza_alertas").update(updates).eq(
                    "id", alerta["id"]
                ).execute()
        return enviados


monitor_fuerza = MonitorFuerzaCripto()


def iniciar_monitor_fuerza():
    monitor_fuerza.iniciar()


def detener_monitor_fuerza():
    monitor_fuerza.detener()
