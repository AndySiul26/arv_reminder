"""Alertas de precio de criptoactivos usando la API pública de Bitso."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests
from dotenv import load_dotenv
from supabase import create_client

from services import enviar_telegram


load_dotenv()

BITSO_API_BASE_URL = os.getenv(
    "BITSO_API_BASE_URL", "https://bitso.com/api/v3"
).rstrip("/")
BITSO_TIMEOUT_SECONDS = int(os.getenv("BITSO_TIMEOUT_SECONDS", "10"))
CRYPTO_ALERT_INTERVAL_SECONDS = max(
    60, int(os.getenv("CRYPTO_ALERT_INTERVAL_SECONDS", "60"))
)
# Deja margen dentro de los 60 RPM públicos para altas y consultas interactivas.
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
    """Obtiene el último precio negociado de un mercado."""
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


def crear_alerta(chat_id, usuario, book, operador, precio_objetivo):
    client = _db()
    if not client:
        return None
    data = {
        "chat_id": str(chat_id),
        "usuario": usuario,
        "book": str(book).lower(),
        "operador": operador,
        "precio_objetivo": str(precio_objetivo),
        "estado": "activa",
        "una_vez": True,
        "fuente": "bitso",
    }
    try:
        response = client.table("cripto_alertas").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as exc:
        print(f"[ERROR] No se pudo crear criptoalerta para {chat_id}: {exc}")
        return None


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
        return response.data or []
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
        return response.data[0] if response.data else None
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
    client = _db()
    if not client:
        return False
    try:
        response = (
            client.table("cripto_alertas")
            .update(
                {
                    "estado": "activa",
                    "precio_disparo": None,
                    "disparada_en": None,
                    "actualizado_en": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .execute()
        )
        return bool(response.data)
    except Exception as exc:
        print(f"[ERROR] No se pudo reactivar criptoalerta {alerta_id}: {exc}")
        return False


def actualizar_alerta_condicion(
    alerta_id, chat_id, operador, precio_objetivo
):
    """Cambia la condición y vuelve a dejar la alerta activa."""
    client = _db()
    if not client:
        return None
    try:
        response = (
            client.table("cripto_alertas")
            .update(
                {
                    "operador": operador,
                    "precio_objetivo": str(precio_objetivo),
                    "estado": "activa",
                    "precio_disparo": None,
                    "disparada_en": None,
                    "actualizado_en": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", int(alerta_id))
            .eq("chat_id", str(chat_id))
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception as exc:
        print(f"[ERROR] No se pudo editar criptoalerta {alerta_id}: {exc}")
        return None


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
        return response.data or []
    except Exception as exc:
        print(f"[ERROR] No se pudieron consultar criptoalertas activas: {exc}")
        return []


def marcar_alerta_disparada(alerta_id, precio):
    client = _db()
    if not client:
        return False
    try:
        response = (
            client.table("cripto_alertas")
            .update(
                {
                    "estado": "disparada",
                    "precio_disparo": str(precio),
                    "disparada_en": datetime.now(timezone.utc).isoformat(),
                    "actualizado_en": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", int(alerta_id))
            .eq("estado", "activa")
            .execute()
        )
        return bool(response.data)
    except Exception as exc:
        print(f"[ERROR] No se pudo marcar criptoalerta {alerta_id}: {exc}")
        return False


def es_condicion_cumplida(operador, precio_actual, precio_objetivo):
    actual = Decimal(str(precio_actual))
    objetivo = Decimal(str(precio_objetivo))
    if operador == "gte":
        return actual >= objetivo
    if operador == "lte":
        return actual <= objetivo
    return False


def _mensaje_alerta(alerta, ticker):
    book = alerta["book"]
    quote = book.split("_", 1)[-1].upper()
    simbolo = "≥" if alerta["operador"] == "gte" else "≤"
    objetivo = formatear_precio(alerta["precio_objetivo"])
    actual = formatear_precio(ticker["last"])
    return (
        "🚨 *CRIPTOALERTA ALCANZADA*\n\n"
        f"💎 *Mercado:* {nombre_book(book)}\n"
        f"🎯 *Condición:* Precio {simbolo} {objetivo} {quote}\n"
        f"💰 *Precio detectado:* {actual} {quote}\n"
        f"🕐 *Dato de Bitso:* {ticker.get('created_at') or 'sin fecha'}\n\n"
        "Fuente: Bitso (`last`). Esta alerta es informativa y no constituye "
        "asesoría financiera."
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
            f"[WARN] {len(books)} mercados activos; se consultarán "
            f"{len(selected)} en este ciclo para respetar el límite de Bitso."
        )
        return selected

    def verificar_una_vez(self):
        alertas = listar_alertas_activas()
        if not alertas:
            return {"alertas": 0, "mercados": 0, "disparadas": 0}

        por_book = {}
        for alerta in alertas:
            por_book.setdefault(alerta["book"].lower(), []).append(alerta)

        selected_books = self._books_del_ciclo(list(por_book))
        disparadas = 0
        for book in selected_books:
            try:
                ticker = obtener_ticker_bitso(book)
            except Exception as exc:
                print(f"[WARN] Bitso no respondió para {book}: {exc}")
                continue

            for alerta in por_book[book]:
                if not es_condicion_cumplida(
                    alerta["operador"],
                    ticker["last"],
                    alerta["precio_objetivo"],
                ):
                    continue
                response = enviar_telegram(
                    alerta["chat_id"],
                    tipo="texto",
                    mensaje=_mensaje_alerta(alerta, ticker),
                    formato="Markdown",
                )
                if response and response.status_code == 200:
                    if marcar_alerta_disparada(alerta["id"], ticker["last"]):
                        disparadas += 1
                else:
                    print(
                        f"[WARN] Telegram no confirmó criptoalerta "
                        f"{alerta.get('id')}"
                    )

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
