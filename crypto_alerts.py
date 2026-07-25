"""Alertas de precio de criptoactivos usando la API pública de Bitso."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests
from dotenv import load_dotenv
from supabase import create_client

try:
    import websocket
except ImportError:  # Permite ejecutar migraciones antes de instalar dependencias.
    websocket = None

from services import enviar_mensaje_con_grid


load_dotenv()

BITSO_API_BASE_URL = os.getenv(
    "BITSO_API_BASE_URL", "https://bitso.com/api/v3"
).rstrip("/")
BITSO_WS_URL = os.getenv("BITSO_WS_URL", "wss://ws.bitso.com")
BITSO_TIMEOUT_SECONDS = int(os.getenv("BITSO_TIMEOUT_SECONDS", "10"))
CRYPTO_ALERT_INTERVAL_SECONDS = max(
    60, int(os.getenv("CRYPTO_ALERT_INTERVAL_SECONDS", "60"))
)
CRYPTO_CONSTANT_INTERVAL_SECONDS = max(
    60, int(os.getenv("CRYPTO_CONSTANT_INTERVAL_SECONDS", "60"))
)
MAX_BOOKS_PER_CYCLE = 45

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = (
    os.getenv("SUPABASE_KEY_SERVICE_ROLE") or os.getenv("SUPABASE_KEY")
)
PREMIUM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_TEST_USER_ID", "")

_db_local = threading.local()
_books_lock = threading.Lock()
_books_cache = {"books": [], "expires_at": 0.0}


def _db():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    client = getattr(_db_local, "client", None)
    if client is None:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _db_local.client = client
    return client


def _bitso_get(path, params=None):
    response = requests.get(
        f"{BITSO_API_BASE_URL}/{path.lstrip('/')}",
        params=params,
        headers={"User-Agent": "ARV-Reminder/4.0 crypto-alerts"},
        timeout=BITSO_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        error = data.get("error", {})
        raise RuntimeError(error.get("message", "Respuesta inválida de Bitso"))
    return data.get("payload")


def obtener_libros_bitso(forzar=False):
    """Devuelve los mercados públicos de Bitso, con caché de una hora."""
    now = time.time()
    with _books_lock:
        if (
            not forzar
            and _books_cache["books"]
            and now < _books_cache["expires_at"]
        ):
            return list(_books_cache["books"])

        payload = _bitso_get("available_books")
        books = sorted(
            {
                item.get("book", "").lower()
                for item in (payload or [])
                if item.get("book")
            }
        )
        if not books:
            raise RuntimeError("Bitso no devolvió mercados disponibles")
        _books_cache.update({"books": books, "expires_at": now + 3600})
        return list(books)


def obtener_ticker_bitso(book):
    """Obtiene el último precio negociado de un mercado por REST."""
    book = str(book).strip().lower()
    payload = _bitso_get("ticker", params={"book": book})
    if not payload or payload.get("book", "").lower() != book:
        raise RuntimeError(f"Ticker inválido para {book}")
    try:
        last = Decimal(str(payload["last"]))
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise RuntimeError(f"Precio inválido para {book}") from exc
    if last <= 0:
        raise RuntimeError(f"Precio no positivo para {book}")
    created_at = payload.get("created_at")
    if created_at:
        try:
            generated = datetime.fromisoformat(
                str(created_at).replace("Z", "+00:00")
            )
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - generated.astimezone(timezone.utc)
            if age > timedelta(minutes=5) or age < timedelta(minutes=-1):
                raise RuntimeError(f"Ticker desactualizado para {book}")
        except ValueError as exc:
            raise RuntimeError(f"Fecha de ticker inválida para {book}") from exc
    return {
        "book": book,
        "last": last,
        "created_at": created_at,
        "bid": payload.get("bid"),
        "ask": payload.get("ask"),
        "source": "rest",
    }


def parsear_precio(texto):
    """Convierte formatos habituales como $1,500,000 o 0,25 a Decimal."""
    raw = str(texto or "").strip().lower()
    for token in ("$", "mxn", "usd", "usdt", "usdc", "ars", "brl", "cop"):
        raw = raw.replace(token, "")
    raw = raw.replace(" ", "")
    if not raw:
        return None

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        groups = raw.split(",")
        if len(groups) > 2 or (
            len(groups) == 2 and len(groups[1]) == 3 and len(groups[0]) > 0
        ):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")

    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def parsear_porcentaje(texto):
    raw = str(texto or "").strip().replace("%", "").replace(",", ".")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if Decimal("0") < value <= Decimal("100") else None


def formatear_precio(value):
    value = Decimal(str(value))
    decimals = 2 if value >= 1 else 8
    formatted = f"{value:,.{decimals}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def nombre_book(book):
    major, _, minor = str(book).partition("_")
    return f"{major.upper()}/{minor.upper()}"


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class BitsoPriceStream:
    """Mantiene en memoria el último trade de los mercados suscritos."""

    def __init__(self, url=BITSO_WS_URL):
        self.url = url
        self._lock = threading.RLock()
        self._subscriptions = set()
        self._prices = {}
        self._ws = None
        self._thread = None
        self._stop = threading.Event()
        self._running = False

    def iniciar(self):
        if websocket is None or self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="bitso-price-stream",
            daemon=True,
        )
        self._thread.start()

    def detener(self):
        self._running = False
        self._stop.set()
        with self._lock:
            ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def suscribir(self, book):
        book = str(book).strip().lower()
        if not book:
            return
        with self._lock:
            is_new = book not in self._subscriptions
            self._subscriptions.add(book)
            ws = self._ws
        if is_new and ws:
            try:
                ws.send(json.dumps({
                    "action": "subscribe",
                    "book": book,
                    "type": "trades",
                }))
            except Exception as exc:
                print(f"[WARN] No se pudo suscribir {book} en Bitso WS: {exc}")

    def _on_open(self, ws):
        with self._lock:
            self._ws = ws
            books = sorted(self._subscriptions)
        for book in books:
            ws.send(json.dumps({
                "action": "subscribe",
                "book": book,
                "type": "trades",
            }))
        print(f"Bitso WebSocket conectado ({len(books)} mercados)")

    def _on_message(self, _ws, raw):
        try:
            message = json.loads(raw)
            if message.get("type") != "trades":
                return
            book = str(message.get("book", "")).lower()
            trades = message.get("payload") or []
            if not book or not trades:
                return
            trade = max(trades, key=lambda item: int(item.get("x") or 0))
            price = Decimal(str(trade["r"]))
            if price <= 0:
                return
            timestamp_ms = int(trade.get("x") or 0)
            generated = (
                datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                if timestamp_ms
                else _utc_now()
            )
            with self._lock:
                self._prices[book] = {
                    "book": book,
                    "last": price,
                    "created_at": generated.isoformat(),
                    "source": "websocket",
                }
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            print(f"[WARN] Mensaje de Bitso WS inválido: {exc}")

    def _on_error(self, _ws, error):
        if self._running:
            print(f"[WARN] Bitso WebSocket: {error}")

    def _on_close(self, ws, _status, _message):
        with self._lock:
            if self._ws is ws:
                self._ws = None

    def _run(self):
        backoff = 1
        while self._running:
            ws = None
            try:
                ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                ws.run_forever(ping_interval=25, ping_timeout=10)
            except Exception as exc:
                if self._running:
                    print(f"[WARN] Reconexión de Bitso WS pendiente: {exc}")
            finally:
                with self._lock:
                    if ws is not None and self._ws is ws:
                        self._ws = None
            if self._running:
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    def obtener(self, book, max_age_seconds=90, permitir_rest=True):
        book = str(book).strip().lower()
        self.suscribir(book)
        now = _utc_now()
        with self._lock:
            cached = dict(self._prices.get(book) or {})
        generated = _parse_datetime(cached.get("created_at"))
        if cached and generated:
            age = (now - generated).total_seconds()
            if -60 <= age <= max_age_seconds:
                return cached
        if not permitir_rest:
            return cached or None
        ticker = obtener_ticker_bitso(book)
        with self._lock:
            self._prices[book] = dict(ticker)
        return ticker


bitso_price_stream = BitsoPriceStream()


def obtener_precio_actual(book, max_age_seconds=90):
    """Precio compartido: WebSocket reciente y REST como respaldo."""
    return bitso_price_stream.obtener(book, max_age_seconds=max_age_seconds)


def es_usuario_premium(chat_id):
    chat_id = str(chat_id)
    if PREMIUM_ADMIN_CHAT_ID and chat_id == str(PREMIUM_ADMIN_CHAT_ID):
        return True
    client = _db()
    if not client:
        return False
    try:
        response = (
            client.table("cripto_premium_users")
            .select("activo")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )
        return bool(response.data and response.data[0].get("activo"))
    except Exception as exc:
        print(f"[ERROR] No se pudo validar acceso premium de {chat_id}: {exc}")
        return False


def normalizar_alerta(alerta):
    """Adapta filas antiguas de un solo objetivo al modelo de banda."""
    alerta = dict(alerta or {})
    precio_min = alerta.get("precio_min")
    precio_max = alerta.get("precio_max")
    if precio_min is None and precio_max is None:
        if alerta.get("operador") == "lte":
            precio_min = alerta.get("precio_objetivo")
        elif alerta.get("operador") == "gte":
            precio_max = alerta.get("precio_objetivo")
    alerta["precio_min"] = precio_min
    alerta["precio_max"] = precio_max
    activa = alerta.get("estado", "activa") == "activa"
    alerta["min_armada"] = bool(
        precio_min is not None
        and alerta.get("min_armada", activa)
    )
    alerta["max_armada"] = bool(
        precio_max is not None
        and alerta.get("max_armada", activa)
    )
    alerta["aviso_constante"] = bool(alerta.get("aviso_constante", False))
    alerta["aviso_detenido"] = bool(alerta.get("aviso_detenido", False))
    return alerta


def _legacy_condition(precio_min, precio_max):
    if precio_min is not None and precio_max is None:
        return "lte", str(precio_min)
    if precio_max is not None and precio_min is None:
        return "gte", str(precio_max)
    return None, None


def crear_alerta_banda(
    chat_id,
    usuario,
    book,
    precio_min=None,
    precio_max=None,
    aviso_constante=False,
    rearme_porcentaje=None,
):
    if precio_min is None and precio_max is None:
        return None
    operador, objetivo = _legacy_condition(precio_min, precio_max)
    client = _db()
    if not client:
        return None
    data = {
        "chat_id": str(chat_id),
        "usuario": usuario,
        "book": str(book).lower(),
        "operador": operador,
        "precio_objetivo": objetivo,
        "precio_min": str(precio_min) if precio_min is not None else None,
        "precio_max": str(precio_max) if precio_max is not None else None,
        "min_armada": precio_min is not None,
        "max_armada": precio_max is not None,
        "aviso_constante": bool(aviso_constante),
        "aviso_detenido": False,
        "rearme_porcentaje": (
            str(rearme_porcentaje)
            if rearme_porcentaje is not None
            else None
        ),
        "lado_disparado": None,
        "ultima_notificacion_en": None,
        "estado": "activa",
        "una_vez": not bool(aviso_constante),
        "precio_disparo": None,
        "disparada_en": None,
        "fuente": "bitso",
    }
    try:
        response = client.table("cripto_alertas").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as exc:
        print(f"[ERROR] No se pudo crear criptoalerta para {chat_id}: {exc}")
        return None


def crear_alerta(chat_id, usuario, book, operador, precio_objetivo):
    """Compatibilidad con el flujo anterior de una sola condición."""
    return crear_alerta_banda(
        chat_id,
        usuario,
        book,
        precio_min=precio_objetivo if operador == "lte" else None,
        precio_max=precio_objetivo if operador == "gte" else None,
    )


def listar_alertas_usuario(chat_id):
    client = _db()
    if not client:
        return []
    try:
        response = (
            client.table("cripto_alertas")
            .select("*")
            .eq("chat_id", str(chat_id))
            .order("id", desc=True)
            .execute()
        )
        return [normalizar_alerta(item) for item in (response.data or [])]
    except Exception as exc:
        print(f"[ERROR] No se pudieron listar criptoalertas de {chat_id}: {exc}")
        return []


def obtener_alerta_usuario(alerta_id, chat_id):
    client = _db()
    if not client:
        return None
    try:
        response = (
            client.table("cripto_alertas")
            .select("*")
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
        )
        return normalizar_alerta(response.data[0]) if response.data else None
    except Exception as exc:
        print(f"[ERROR] No se pudo consultar criptoalerta {alerta_id}: {exc}")
        return None


def eliminar_alerta(alerta_id, chat_id):
    client = _db()
    if not client:
        return False
    try:
        response = (
            client.table("cripto_alertas")
            .delete()
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .execute()
        )
        return bool(response.data)
    except Exception as exc:
        print(f"[ERROR] No se pudo eliminar criptoalerta {alerta_id}: {exc}")
        return False


def reactivar_alerta(alerta_id, chat_id):
    alerta = obtener_alerta_usuario(alerta_id, chat_id)
    if not alerta:
        return False
    return bool(_actualizar_alerta(
        alerta_id,
        {
            "estado": "activa",
            "min_armada": alerta.get("precio_min") is not None,
            "max_armada": alerta.get("precio_max") is not None,
            "aviso_detenido": False,
            "lado_disparado": None,
            "ultima_notificacion_en": None,
            "precio_disparo": None,
            "disparada_en": None,
        },
        chat_id=chat_id,
    ))


def actualizar_alerta_banda(
    alerta_id,
    chat_id,
    precio_min=None,
    precio_max=None,
    aviso_constante=False,
    rearme_porcentaje=None,
):
    operador, objetivo = _legacy_condition(precio_min, precio_max)
    return _actualizar_alerta(
        alerta_id,
        {
            "operador": operador,
            "precio_objetivo": objetivo,
            "precio_min": (
                str(precio_min) if precio_min is not None else None
            ),
            "precio_max": (
                str(precio_max) if precio_max is not None else None
            ),
            "min_armada": precio_min is not None,
            "max_armada": precio_max is not None,
            "aviso_constante": bool(aviso_constante),
            "una_vez": not bool(aviso_constante),
            "aviso_detenido": False,
            "rearme_porcentaje": (
                str(rearme_porcentaje)
                if rearme_porcentaje is not None
                else None
            ),
            "lado_disparado": None,
            "ultima_notificacion_en": None,
            "estado": "activa",
            "precio_disparo": None,
            "disparada_en": None,
        },
        chat_id=chat_id,
    )


def actualizar_alerta_condicion(
    alerta_id, chat_id, operador, precio_objetivo
):
    """Compatibilidad con ediciones creadas por versiones anteriores."""
    return actualizar_alerta_banda(
        alerta_id,
        chat_id,
        precio_min=precio_objetivo if operador == "lte" else None,
        precio_max=precio_objetivo if operador == "gte" else None,
    )


def listar_alertas_activas():
    client = _db()
    if not client:
        return []
    try:
        response = (
            client.table("cripto_alertas")
            .select("*")
            .eq("estado", "activa")
            .order("id")
            .execute()
        )
        return [normalizar_alerta(item) for item in (response.data or [])]
    except Exception as exc:
        print(f"[ERROR] No se pudieron consultar criptoalertas activas: {exc}")
        return []


def _actualizar_alerta(alerta_id, cambios, chat_id=None):
    client = _db()
    if not client:
        return None
    payload = dict(cambios)
    payload["actualizado_en"] = _utc_now().isoformat()
    try:
        query = client.table("cripto_alertas").update(payload).eq(
            "id", int(alerta_id)
        )
        if chat_id is not None:
            query = query.eq("chat_id", str(chat_id))
        response = query.execute()
        return normalizar_alerta(response.data[0]) if response.data else None
    except Exception as exc:
        print(f"[ERROR] No se pudo actualizar criptoalerta {alerta_id}: {exc}")
        return None


def detener_alerta_constante(alerta_id, chat_id):
    alerta = obtener_alerta_usuario(alerta_id, chat_id)
    if not alerta or not alerta.get("aviso_constante"):
        return False
    hay_otro_lado = bool(
        alerta.get("min_armada") or alerta.get("max_armada")
    )
    tiene_rearme = alerta.get("rearme_porcentaje") is not None
    estado = "activa" if hay_otro_lado or tiene_rearme else "disparada"
    return bool(_actualizar_alerta(
        alerta_id,
        {"aviso_detenido": True, "estado": estado},
        chat_id=chat_id,
    ))


def es_condicion_cumplida(operador, precio_actual, precio_objetivo):
    actual = Decimal(str(precio_actual))
    objetivo = Decimal(str(precio_objetivo))
    if operador == "gte":
        return actual >= objetivo
    if operador == "lte":
        return actual <= objetivo
    return False


def _lado_cumplido(alerta, precio):
    precio = Decimal(str(precio))
    if (
        alerta.get("min_armada")
        and alerta.get("precio_min") is not None
        and precio <= Decimal(str(alerta["precio_min"]))
    ):
        return "min"
    if (
        alerta.get("max_armada")
        and alerta.get("precio_max") is not None
        and precio >= Decimal(str(alerta["precio_max"]))
    ):
        return "max"
    return None


def _aplicar_rearme(alerta, precio):
    porcentaje = alerta.get("rearme_porcentaje")
    if porcentaje is None:
        return {}
    pct = Decimal(str(porcentaje)) / Decimal("100")
    precio = Decimal(str(precio))
    cambios = {}
    if (
        alerta.get("precio_min") is not None
        and not alerta.get("min_armada")
        and precio >= Decimal(str(alerta["precio_min"])) * (1 + pct)
    ):
        cambios["min_armada"] = True
        if alerta.get("lado_disparado") == "min":
            cambios.update({
                "lado_disparado": None,
                "aviso_detenido": False,
                "ultima_notificacion_en": None,
            })
    if (
        alerta.get("precio_max") is not None
        and not alerta.get("max_armada")
        and precio <= Decimal(str(alerta["precio_max"])) * (1 - pct)
    ):
        cambios["max_armada"] = True
        if alerta.get("lado_disparado") == "max":
            cambios.update({
                "lado_disparado": None,
                "aviso_detenido": False,
                "ultima_notificacion_en": None,
            })
    if cambios:
        cambios["estado"] = "activa"
    return cambios


def _debe_repetir(alerta, precio, ahora):
    if not alerta.get("aviso_constante") or alerta.get("aviso_detenido"):
        return False
    lado = alerta.get("lado_disparado")
    if lado == "min" and alerta.get("precio_min") is not None:
        sigue_cumplida = Decimal(str(precio)) <= Decimal(
            str(alerta["precio_min"])
        )
    elif lado == "max" and alerta.get("precio_max") is not None:
        sigue_cumplida = Decimal(str(precio)) >= Decimal(
            str(alerta["precio_max"])
        )
    else:
        return False
    ultima = _parse_datetime(alerta.get("ultima_notificacion_en"))
    return bool(
        sigue_cumplida
        and (
            ultima is None
            or (ahora - ultima).total_seconds()
            >= CRYPTO_CONSTANT_INTERVAL_SECONDS
        )
    )


def _mensaje_alerta(alerta, ticker, lado, repeticion=False):
    book = alerta["book"]
    quote = book.split("_", 1)[-1].upper()
    objetivo_raw = (
        alerta["precio_min"] if lado == "min" else alerta["precio_max"]
    )
    simbolo = "≤" if lado == "min" else "≥"
    encabezado = (
        "📢 CRIPTOALERTA CONSTANTE"
        if alerta.get("aviso_constante")
        else "🚨 CRIPTOALERTA ALCANZADA"
    )
    if repeticion:
        encabezado += " · RECORDATORIO"
    return (
        f"{encabezado}\n\n"
        f"💎 Mercado: {nombre_book(book)}\n"
        f"🎯 Condición: Precio {simbolo} "
        f"{formatear_precio(objetivo_raw)} {quote}\n"
        f"💰 Precio detectado: {formatear_precio(ticker['last'])} {quote}\n"
        f"🕐 Dato de Bitso: {ticker.get('created_at') or 'sin fecha'}\n\n"
        "Fuente: último precio negociado en Bitso. Esta alerta es "
        "informativa y no constituye asesoría financiera."
    )


class MonitorCriptoAlertas:
    def __init__(self, interval_seconds=CRYPTO_ALERT_INTERVAL_SECONDS):
        self.interval_seconds = max(60, int(interval_seconds))
        self.activo = False
        self.hilo = None
        self._stop = threading.Event()
        self._book_cursor = 0

    def iniciar(self):
        if self.activo:
            return
        bitso_price_stream.iniciar()
        self.activo = True
        self._stop.clear()
        self.hilo = threading.Thread(
            target=self._ejecutar,
            name="crypto-alert-monitor",
            daemon=True,
        )
        self.hilo.start()
        print(
            "Monitor de criptoalertas iniciado "
            f"(cada {self.interval_seconds} segundos)"
        )

    def detener(self):
        self.activo = False
        self._stop.set()
        if self.hilo:
            self.hilo.join(timeout=2.0)
        bitso_price_stream.detener()
        print("Monitor de criptoalertas detenido")

    def _ejecutar(self):
        while self.activo:
            try:
                self.verificar_una_vez()
            except Exception as exc:
                print(f"[ERROR] Ciclo de criptoalertas: {exc}")
            self._stop.wait(self.interval_seconds)

    def _books_del_ciclo(self, books):
        books = sorted(set(books))
        if len(books) <= MAX_BOOKS_PER_CYCLE:
            return books
        start = self._book_cursor % len(books)
        ordered = books[start:] + books[:start]
        selected = ordered[:MAX_BOOKS_PER_CYCLE]
        self._book_cursor = (start + MAX_BOOKS_PER_CYCLE) % len(books)
        print(
            f"[WARN] {len(books)} mercados activos; se revisarán "
            f"{len(selected)} en este ciclo."
        )
        return selected

    def _guardar_disparo(self, alerta, ticker, lado, ahora):
        cambios = {
            f"{lado}_armada": False,
            "lado_disparado": lado,
            "ultima_notificacion_en": ahora.isoformat(),
            "precio_disparo": str(ticker["last"]),
            "disparada_en": ahora.isoformat(),
            "aviso_detenido": False,
        }
        otro_armado = (
            alerta.get("max_armada") if lado == "min"
            else alerta.get("min_armada")
        )
        debe_seguir_activa = bool(
            alerta.get("aviso_constante")
            or alerta.get("rearme_porcentaje") is not None
            or otro_armado
        )
        cambios["estado"] = "activa" if debe_seguir_activa else "disparada"
        return _actualizar_alerta(alerta["id"], cambios)

    def _enviar(self, alerta, ticker, lado, repeticion=False):
        filas = []
        if alerta.get("aviso_constante"):
            filas = [[{
                "texto": "🛑 Detener esta alerta",
                "data": f"crypto_stop:{alerta['id']}",
            }]]
        return enviar_mensaje_con_grid(
            alerta["chat_id"],
            _mensaje_alerta(alerta, ticker, lado, repeticion=repeticion),
            filas,
        )

    def verificar_una_vez(self):
        alertas = listar_alertas_activas()
        if not alertas:
            return {"alertas": 0, "mercados": 0, "disparadas": 0}

        por_book = {}
        for alerta in alertas:
            book = alerta["book"].lower()
            por_book.setdefault(book, []).append(normalizar_alerta(alerta))
            bitso_price_stream.suscribir(book)

        selected_books = self._books_del_ciclo(list(por_book))
        disparadas = 0
        ahora = _utc_now()
        for book in selected_books:
            try:
                ticker = obtener_precio_actual(book)
            except Exception as exc:
                print(f"[WARN] Bitso no respondió para {book}: {exc}")
                continue

            for alerta in por_book[book]:
                cambios_rearme = _aplicar_rearme(alerta, ticker["last"])
                if cambios_rearme:
                    updated = _actualizar_alerta(
                        alerta["id"], cambios_rearme
                    )
                    if updated:
                        alerta = updated

                lado = _lado_cumplido(alerta, ticker["last"])
                repeticion = False
                if not lado and _debe_repetir(
                    alerta, ticker["last"], ahora
                ):
                    lado = alerta.get("lado_disparado")
                    repeticion = True
                if not lado:
                    continue

                response = self._enviar(
                    alerta, ticker, lado, repeticion=repeticion
                )
                if not response or response.status_code != 200:
                    print(
                        f"[WARN] Telegram no confirmó criptoalerta "
                        f"{alerta.get('id')}"
                    )
                    continue
                if repeticion:
                    _actualizar_alerta(
                        alerta["id"],
                        {"ultima_notificacion_en": ahora.isoformat()},
                    )
                elif self._guardar_disparo(alerta, ticker, lado, ahora):
                    disparadas += 1

        return {
            "alertas": len(alertas),
            "mercados": len(selected_books),
            "disparadas": disparadas,
        }


monitor_criptoalertas = MonitorCriptoAlertas()


def iniciar_monitor_criptoalertas():
    monitor_criptoalertas.iniciar()


def detener_monitor_criptoalertas():
    monitor_criptoalertas.detener()
