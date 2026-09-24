"""Alertas inteligentes multitemporales calibradas con histórico de mercado."""

from __future__ import annotations

import json
import math
import os
import statistics
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests

import crypto_alerts
import crypto_strength
from services import editar_mensaje_con_grid, enviar_mensaje_con_grid


API_URL = crypto_strength.COINBASE_EXCHANGE_URL
TIMEOUT = crypto_strength.STRENGTH_TIMEOUT_SECONDS
MONITOR_SECONDS = max(60, int(os.getenv("CRYPTO_SMART_INTERVAL_SECONDS", "60")))
REPEAT_SECONDS = max(180, int(os.getenv("CRYPTO_SMART_REPEAT_SECONDS", "300")))
HISTORY_CANDLES = max(300, min(1800, int(os.getenv("CRYPTO_SMART_HISTORY_CANDLES", "900"))))
EPSILON = Decimal("0.05")

PRIMARY_TIMEFRAMES = {
    "30m": {"seconds": 1800, "granularity": 900, "label": "30 minutos", "subs": ("10m", "5m")},
    "1h": {"seconds": 3600, "granularity": 3600, "label": "1 hora", "subs": ("30m", "10m", "5m")},
    "4h": {"seconds": 14400, "granularity": 3600, "label": "4 horas", "subs": ("1h", "30m", "10m")},
    "1d": {"seconds": 86400, "granularity": 21600, "label": "1 día", "subs": ("4h", "1h", "30m")},
}
FRAME_SECONDS = {"5m": 300, "10m": 600, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
PROFILE_LABELS = {"rapido": "Rápido", "equilibrado": "Equilibrado", "confirmado": "Confirmado"}
CONDITION_LABELS = {
    "objetivo": "🎯 Precio objetivo alcanzado",
    "promedio": "📉 Debilitamiento frente al promedio",
    "fuerza": "🧭 Pérdida fuerte de impulso",
    "micro": "⚡ Giro multitemporal con actividad elevada",
    "seguridad": "🛡 Margen de seguridad alcanzado",
}


class AnalisisInteligenteError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _headers():
    return {"User-Agent": "ARV-Reminder/4.0 smart-alerts"}


def _decimal(value, default=None):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default


def _json_dict(value):
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _percentile(values, percentile, default):
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return Decimal(str(default))
    position = (len(clean) - 1) * float(percentile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        result = clean[lower]
    else:
        result = clean[lower] + (clean[upper] - clean[lower]) * (position - lower)
    return Decimal(str(round(result, 4)))


def _request_candles(book, granularity, count, end=None):
    """Descarga velas cerradas en bloques de hasta 300, sin mirar al futuro."""
    product = crypto_strength._product_id(book)
    end = end or _now()
    remaining = int(count)
    result = {}
    while remaining > 0:
        block = min(300, remaining)
        start = end - timedelta(seconds=granularity * block)
        try:
            response = requests.get(
                f"{API_URL}/products/{product}/candles",
                params={
                    "granularity": granularity,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
                headers=_headers(),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AnalisisInteligenteError(f"No se obtuvo histórico de {product}") from exc
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            try:
                timestamp = int(item[0])
                # Coinbase: time, low, high, open, close, volume.
                result[timestamp] = {
                    "time": timestamp,
                    "low": Decimal(str(item[1])),
                    "high": Decimal(str(item[2])),
                    "open": Decimal(str(item[3])),
                    "close": Decimal(str(item[4])),
                    "volume": Decimal(str(item[5])) if len(item) > 5 else Decimal("0"),
                }
            except (IndexError, InvalidOperation, TypeError, ValueError):
                continue
        oldest = min(result) if result else int(start.timestamp())
        end = datetime.fromtimestamp(oldest, timezone.utc)
        remaining -= block
        if len(payload) < max(2, block // 3):
            break
    cutoff = int(_now().timestamp())
    return [result[key] for key in sorted(result) if key + granularity <= cutoff]


def _aggregate(candles, seconds):
    buckets = {}
    for candle in candles:
        key = int(candle["time"]) // seconds * seconds
        bucket = buckets.get(key)
        if not bucket:
            buckets[key] = {**candle, "time": key}
            continue
        bucket["high"] = max(bucket["high"], candle["high"])
        bucket["low"] = min(bucket["low"], candle["low"])
        bucket["close"] = candle["close"]
        bucket["volume"] += candle["volume"]
    return [buckets[key] for key in sorted(buckets)]


def _returns(candles):
    values = []
    for candle in candles:
        if candle["open"] <= 0:
            values.append(Decimal("0"))
        else:
            values.append((candle["close"] / candle["open"] - 1) * 100)
    return values


def _turning_samples(candles, direction, periods):
    """Mide el deterioro que existía en giros históricos confirmados a posteriori."""
    sign = Decimal("1") if direction == "venta" else Decimal("-1")
    returns = [value * sign for value in _returns(candles)]
    average_losses, peak_losses, margins = [], [], []
    radius = 3
    for index in range(max(periods, radius), len(candles) - radius):
        close = candles[index]["close"]
        neighbors = [candles[pos]["close"] for pos in range(index - radius, index + radius + 1) if pos != index]
        is_turn = close >= max(neighbors) if direction == "venta" else close <= min(neighbors)
        if not is_turn:
            continue
        history = returns[index - periods:index]
        favorable = [value for value in history if value > 0]
        if not favorable:
            continue
        average = sum(favorable, Decimal("0")) / len(favorable)
        current = returns[index]
        peak = max(favorable)
        if average >= EPSILON:
            average_losses.append(max(Decimal("0"), (average - current) / average * 100))
        if peak >= EPSILON:
            peak_losses.append(max(Decimal("0"), (peak - current) / peak * 100))
        future = candles[index + 1:index + 1 + radius]
        if future and close > 0:
            extreme = min(item["low"] for item in future) if direction == "venta" else max(item["high"] for item in future)
            adverse = (close - extreme) / close * 100 if direction == "venta" else (extreme - close) / close * 100
            margins.append(max(Decimal("0"), adverse))
    return average_losses, peak_losses, margins


def analizar_historico(book, direction, timeframe, profile="equilibrado"):
    if direction not in ("compra", "venta") or timeframe not in PRIMARY_TIMEFRAMES:
        raise ValueError("Configuración inteligente inválida")
    if profile not in PROFILE_LABELS:
        profile = "equilibrado"
    config = PRIMARY_TIMEFRAMES[timeframe]
    source = _request_candles(book, config["granularity"], HISTORY_CANDLES)
    candles = _aggregate(source, config["seconds"])
    if len(candles) < 80:
        raise AnalisisInteligenteError("No hay suficientes velas históricas para calibrar")

    best = None
    for periods in (4, 6, 8, 12):
        avg_losses, peak_losses, margins = _turning_samples(candles, direction, periods)
        score = len(avg_losses) - abs(periods - 8) * 0.15
        if best is None or score > best[0]:
            best = (score, periods, avg_losses, peak_losses, margins)
    _, periods, avg_losses, peak_losses, margins = best
    multiplier = {"rapido": Decimal("0.80"), "equilibrado": Decimal("1"), "confirmado": Decimal("1.20")}[profile]
    average_loss = max(Decimal("8"), min(Decimal("80"), _percentile(avg_losses, 0.40, 15) * multiplier))
    force_loss = max(Decimal("20"), min(Decimal("95"), _percentile(peak_losses, 0.60, 40) * multiplier))
    margin = max(Decimal("0.5"), min(Decimal("5"), _percentile(margins, 0.55, 1.5) * multiplier))

    # La actividad extraordinaria se calibra con el volumen relativo de las velas.
    volumes = [float(item["volume"]) for item in candles if item["volume"] > 0]
    volume_median = statistics.median(volumes) if volumes else 0
    ratios = [value / volume_median for value in volumes if volume_median > 0]
    activity = max(Decimal("1.3"), min(Decimal("4"), _percentile(ratios, 0.85, 2)))
    confirmations = {"rapido": 1, "equilibrado": 2, "confirmado": min(3, len(config["subs"]))}[profile]
    sample_count = len(avg_losses)
    quality = "alta" if sample_count >= 40 else "media" if sample_count >= 20 else "limitada"
    report = {
        "velas": len(candles),
        "giros": sample_count,
        "calidad": quality,
        "desde": datetime.fromtimestamp(candles[0]["time"], timezone.utc).isoformat(),
        "hasta": datetime.fromtimestamp(candles[-1]["time"], timezone.utc).isoformat(),
        "fuente": "Coinbase Exchange",
        "subtemporalidades": list(config["subs"]),
    }
    return {
        "periodos_promedio": periods,
        "perdida_promedio_pct": average_loss.quantize(Decimal("0.01")),
        "perdida_fuerza_pct": force_loss.quantize(Decimal("0.01")),
        "margen_precio_pct": margin.quantize(Decimal("0.01")),
        "actividad_ratio": activity.quantize(Decimal("0.01")),
        "confirmaciones": confirmations,
        "persistencia": {"rapido": 1, "equilibrado": 2, "confirmado": 3}[profile],
        "report": report,
    }


def _db():
    return crypto_alerts._db()


def crear_alerta(chat_id, usuario, book, direction, target, timeframe, profile, calibration):
    target = _decimal(target)
    if target is None or target <= 0:
        return None
    payload = {
        "chat_id": str(chat_id), "usuario": usuario, "book": str(book).lower(),
        "direccion": direction, "precio_objetivo": str(target), "temporalidad": timeframe,
        "perfil": profile, "periodos_promedio": calibration["periodos_promedio"],
        "perdida_promedio_pct": str(calibration["perdida_promedio_pct"]),
        "perdida_fuerza_pct": str(calibration["perdida_fuerza_pct"]),
        "margen_precio_pct": str(calibration["margen_precio_pct"]),
        "actividad_ratio": str(calibration["actividad_ratio"]),
        "confirmaciones_requeridas": calibration["confirmaciones"],
        "persistencia_requerida": calibration["persistencia"],
        "subtemporalidades": calibration["report"]["subtemporalidades"],
        "reporte_calibracion": calibration["report"], "estado": "esperando",
        "condiciones_activas": {}, "condiciones_silenciadas": {}, "conteos_condiciones": {},
        "ultimas_notificaciones": {}, "fuente": "coinbase_exchange",
    }
    try:
        rows = _db().table("cripto_alertas_inteligentes").insert(payload).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        print(f"[ERROR] No se creó alerta inteligente: {exc}")
        return None


def listar_alertas(chat_id):
    try:
        return (_db().table("cripto_alertas_inteligentes").select("*")
                .eq("chat_id", str(chat_id)).order("id", desc=True).execute().data or [])
    except Exception as exc:
        print(f"[ERROR] No se listaron alertas inteligentes: {exc}")
        return []


def obtener_alerta(alert_id, chat_id):
    try:
        rows = (_db().table("cripto_alertas_inteligentes").select("*")
                .eq("id", int(alert_id)).eq("chat_id", str(chat_id)).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception:
        return None


def _update(alert_id, values, chat_id=None):
    values["actualizado_en"] = _now().isoformat()
    query = _db().table("cripto_alertas_inteligentes").update(values).eq("id", int(alert_id))
    if chat_id is not None:
        query = query.eq("chat_id", str(chat_id))
    try:
        return bool(query.execute().data)
    except Exception as exc:
        print(f"[ERROR] No se actualizó alerta inteligente {alert_id}: {exc}")
        return False


def eliminar_alerta(alert_id, chat_id):
    try:
        return bool((_db().table("cripto_alertas_inteligentes").delete()
                     .eq("id", int(alert_id)).eq("chat_id", str(chat_id)).execute().data))
    except Exception:
        return False


def pausar_alerta(alert_id, chat_id):
    return _update(alert_id, {"estado": "pausada"}, chat_id)


def reanudar_alerta(alert_id, chat_id):
    alert = obtener_alerta(alert_id, chat_id)
    if not alert:
        return False
    target = _decimal(alert["precio_objetivo"], Decimal("0"))
    current = _decimal(alert.get("ultimo_precio"), Decimal("0"))
    activated = current >= target if alert["direccion"] == "venta" else current and current <= target
    return _update(alert_id, {
        "estado": "vigilando" if activated else "esperando",
        "condiciones_activas": {}, "condiciones_silenciadas": {}, "conteos_condiciones": {},
        "ultimas_notificaciones": {},
    }, chat_id)


def silenciar_condicion(alert_id, chat_id, condition):
    if condition not in CONDITION_LABELS:
        return False
    alert = obtener_alerta(alert_id, chat_id)
    if not alert:
        return False
    silenced = _json_dict(alert.get("condiciones_silenciadas"))
    silenced[condition] = True
    return _update(alert_id, {"condiciones_silenciadas": silenced}, chat_id)


def _trade_activity(book):
    """Compara trades/minuto recientes con los cinco minutos anteriores."""
    product = crypto_strength._product_id(book)
    try:
        response = requests.get(
            f"{API_URL}/products/{product}/trades",
            params={"limit": 1000}, headers=_headers(), timeout=TIMEOUT,
        )
        response.raise_for_status()
        trades = response.json()
    except (requests.RequestException, ValueError):
        return Decimal("1"), None
    now = _now()
    bins = [0] * 6
    oldest = None
    for trade in trades if isinstance(trades, list) else []:
        try:
            stamp = datetime.fromisoformat(str(trade["time"]).replace("Z", "+00:00"))
            age = (now - stamp).total_seconds()
        except (KeyError, TypeError, ValueError):
            continue
        oldest = age if oldest is None else max(oldest, age)
        if 0 <= age < 360:
            bins[min(5, int(age // 60))] += 1
    current = bins[0]
    baseline_bins = [value for value in bins[1:] if value > 0]
    if oldest is not None and oldest < 60 and len(trades) >= 1000:
        return Decimal("4"), current
    if not baseline_bins:
        return Decimal("1"), current
    baseline = Decimal(str(sum(baseline_bins))) / len(baseline_bins)
    return (Decimal(str(current)) / baseline if baseline > 0 else Decimal("1")), current


def _live_analysis(book, timeframe, periods, subs):
    ticker = crypto_alerts.obtener_ticker_coinbase(book)
    current = _decimal(ticker["last"])
    base = _request_candles(book, 300, 300)
    if len(base) < 30 or current is None:
        raise AnalisisInteligenteError("No hay datos recientes suficientes")
    trade_ratio, trades_minute = _trade_activity(book)
    result = {
        "precio": current, "fuente": ticker.get("provider_label", "Coinbase Spot"),
        "frames": {}, "actividad_trades": trade_ratio, "trades_ultimo_minuto": trades_minute,
    }
    for frame in set([timeframe, *subs]):
        seconds = FRAME_SECONDS[frame]
        candles = _aggregate(base, seconds)
        if len(candles) < periods + 2:
            # Para 4h/1d completamos contexto con velas de granularidad compatible.
            granularity = PRIMARY_TIMEFRAMES.get(frame, {}).get("granularity", 3600)
            candles = _aggregate(_request_candles(book, granularity, max(80, periods * 4)), seconds)
        completed = candles[:-1] if len(candles) > 1 else candles
        historical = _returns(completed[-periods:])
        current_open = candles[-1]["open"]
        change = (current / current_open - 1) * 100 if current_open > 0 else Decimal("0")
        avg = sum(historical, Decimal("0")) / len(historical) if historical else Decimal("0")
        volumes = [item["volume"] for item in completed[-periods:] if item["volume"] > 0]
        avg_volume = sum(volumes, Decimal("0")) / len(volumes) if volumes else Decimal("0")
        current_volume = candles[-1]["volume"]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else Decimal("1")
        result["frames"][frame] = {"cambio": change, "promedio": avg, "actividad": volume_ratio}
    return result


def evaluar(alert, analysis):
    direction = alert["direccion"]
    sign = Decimal("1") if direction == "venta" else Decimal("-1")
    target = _decimal(alert["precio_objetivo"])
    price = analysis["precio"]
    frame = analysis["frames"][alert["temporalidad"]]
    current_force = frame["cambio"] * sign
    average_force = frame["promedio"] * sign
    average_loss = None
    if average_force >= EPSILON:
        average_loss = (average_force - current_force) / average_force * 100
    peak_force = max(_decimal(alert.get("fuerza_pico_pct"), current_force), current_force)
    force_loss = (peak_force - current_force) / peak_force * 100 if peak_force >= EPSILON else None
    activated = alert["estado"] == "vigilando"
    reaches = price >= target if direction == "venta" else price <= target
    conditions = set()
    if not activated and reaches:
        conditions.add("objetivo")
        activated = True
    if activated:
        if average_loss is not None and average_loss >= _decimal(alert["perdida_promedio_pct"]):
            conditions.add("promedio")
        if force_loss is not None and force_loss >= _decimal(alert["perdida_fuerza_pct"]):
            conditions.add("fuerza")
        margin = _decimal(alert["margen_precio_pct"]) / 100
        safety = target * (1 - margin) if direction == "venta" else target * (1 + margin)
        if (direction == "venta" and price <= safety) or (direction == "compra" and price >= safety):
            conditions.add("seguridad")
        confirmations = 0
        activity_peak = Decimal("0")
        for sub in alert.get("subtemporalidades") or []:
            data = analysis["frames"].get(sub)
            if not data:
                continue
            directional = data["cambio"] * sign
            directional_avg = data["promedio"] * sign
            activity_peak = max(activity_peak, data["actividad"], analysis.get("actividad_trades", Decimal("1")))
            if directional <= 0 or (directional_avg >= EPSILON and directional < directional_avg * Decimal("0.70")):
                confirmations += 1
        if confirmations >= int(alert["confirmaciones_requeridas"]) and activity_peak >= _decimal(alert["actividad_ratio"]):
            conditions.add("micro")
    return {
        "conditions": conditions, "activated": activated, "current_force": current_force,
        "average_force": average_force, "average_loss": average_loss, "peak_force": peak_force,
        "force_loss": force_loss, "price": price,
    }


def _fmt_pct(value):
    return "—" if value is None else f"{Decimal(str(value)):+.2f}%"


def _notification_text(alert, analysis, result, notified, repetition=False):
    direction = "VENTA" if alert["direccion"] == "venta" else "COMPRA"
    labels = "\n".join(CONDITION_LABELS[item] for item in notified)
    sub_lines = []
    for frame in alert.get("subtemporalidades") or []:
        data = analysis["frames"].get(frame)
        if data:
            sub_lines.append(f"• {frame}: {_fmt_pct(data['cambio'])} · actividad {data['actividad']:.2f}×")
    trades_text = f"⚡ Actividad de trades: {analysis.get('actividad_trades', Decimal('1')):.2f}×"
    if analysis.get("trades_ultimo_minuto") is not None:
        trades_text += f" · {analysis['trades_ultimo_minuto']} en el último minuto"
    return (
        f"🧠 ALERTA INTELIGENTE DE {direction}{' · SEGUIMIENTO' if repetition else ''}\n\n"
        f"{labels}\n\n💎 Mercado: {crypto_alerts.nombre_book(alert['book'])}\n"
        f"💰 Precio: {crypto_alerts.formatear_precio(result['price'])}\n"
        f"🎯 Objetivo: {crypto_alerts.formatear_precio(alert['precio_objetivo'])}\n"
        f"⏱ Marco principal: {PRIMARY_TIMEFRAMES[alert['temporalidad']]['label']}\n"
        f"📊 Fuerza actual: {_fmt_pct(result['current_force'])}\n"
        f"📐 Fuerza promedio: {_fmt_pct(result['average_force'])}\n"
        f"📉 Pérdida frente al promedio: {_fmt_pct(result['average_loss'])}\n"
        f"🧭 Pérdida desde el pico de fuerza: {_fmt_pct(result['force_loss'])}\n\n"
        + "\n".join(sub_lines) + "\n\n"
        + trades_text + "\n"
        + f"🏦 Fuente: {analysis['fuente']}\n"
        + "Análisis probabilístico de mercado; no constituye asesoría financiera."
    )


def _buttons(alert_id, conditions):
    rows = []
    for condition in sorted(conditions):
        rows.append([{"texto": f"🔕 Silenciar {CONDITION_LABELS[condition].split(' ', 1)[1]}",
                      "data": f"smart_mute:{alert_id}:{condition}"}])
    rows.append([{"texto": "⏸ Suspender estrategia", "data": f"smart_pause:{alert_id}"}])
    return rows


class MonitorAlertasInteligentes:
    def __init__(self, interval_seconds=MONITOR_SECONDS):
        self.interval_seconds = max(60, int(interval_seconds))
        self.active = False
        self.thread = None
        self.stop_event = threading.Event()

    def iniciar(self):
        if self.active:
            return
        self.active = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="crypto-smart-monitor", daemon=True)
        self.thread.start()
        print(f"Monitor de alertas inteligentes iniciado (cada {self.interval_seconds}s)")

    def detener(self):
        self.active = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _run(self):
        while self.active:
            try:
                self.verificar_una_vez()
            except Exception as exc:
                print(f"[ERROR] Ciclo de alertas inteligentes: {exc}")
            self.stop_event.wait(self.interval_seconds)

    def verificar_una_vez(self):
        try:
            alerts = (_db().table("cripto_alertas_inteligentes").select("*")
                      .in_("estado", ["esperando", "vigilando"]).execute().data or [])
        except Exception as exc:
            print(f"[WARN] No se consultaron alertas inteligentes: {exc}")
            return 0
        cache, sent = {}, 0
        now = _now()
        for alert in alerts:
            key = (alert["book"], alert["temporalidad"], int(alert["periodos_promedio"]), tuple(alert.get("subtemporalidades") or []))
            try:
                if key not in cache:
                    cache[key] = _live_analysis(*key)
                analysis = cache[key]
                result = evaluar(alert, analysis)
            except Exception as exc:
                print(f"[WARN] Alerta inteligente {alert['id']} sin datos: {exc}")
                continue
            previous = set(_json_dict(alert.get("condiciones_activas")))
            silenced = _json_dict(alert.get("condiciones_silenciadas"))
            last = _json_dict(alert.get("ultimas_notificaciones"))
            counts = _json_dict(alert.get("conteos_condiciones"))
            raw = result["conditions"]
            persistence = max(1, int(alert.get("persistencia_requerida") or 2))
            for condition in CONDITION_LABELS:
                counts[condition] = int(counts.get(condition, 0)) + 1 if condition in raw else 0
            current = {
                condition for condition in raw
                if condition in ("objetivo", "seguridad") or counts.get(condition, 0) >= persistence
            }
            # Recuperarse rearma únicamente esa particularidad.
            for condition in list(silenced):
                if condition not in current:
                    silenced.pop(condition, None)
            new = current - previous
            due = set(new)
            for condition in current - set(silenced):
                previous_time = last.get(condition)
                if previous_time:
                    try:
                        if (now - datetime.fromisoformat(previous_time.replace("Z", "+00:00"))).total_seconds() >= REPEAT_SECONDS:
                            due.add(condition)
                    except (TypeError, ValueError):
                        due.add(condition)
            due -= set(silenced)
            values = {
                "estado": "vigilando" if result["activated"] else "esperando",
                "ultimo_precio": str(result["price"]), "ultima_fuerza_pct": str(result["current_force"]),
                "fuerza_promedio_pct": str(result["average_force"]), "fuerza_pico_pct": str(result["peak_force"]),
                "condiciones_activas": {item: True for item in current},
                "condiciones_silenciadas": silenced, "conteos_condiciones": counts,
                "ultima_consulta_en": now.isoformat(),
            }
            if due:
                repetition = not bool(due & new)
                response = enviar_mensaje_con_grid(
                    alert["chat_id"], _notification_text(alert, analysis, result, sorted(due), repetition),
                    _buttons(alert["id"], due),
                )
                if response and response.status_code == 200:
                    for condition in due:
                        last[condition] = now.isoformat()
                    values["ultimas_notificaciones"] = last
                    try:
                        values["ultimo_mensaje_id"] = response.json()["result"]["message_id"]
                    except (KeyError, TypeError, ValueError):
                        pass
                    sent += 1
            _update(alert["id"], values)
        return sent


monitor_inteligente = MonitorAlertasInteligentes()


def iniciar_monitor_inteligente():
    monitor_inteligente.iniciar()


def detener_monitor_inteligente():
    monitor_inteligente.detener()
