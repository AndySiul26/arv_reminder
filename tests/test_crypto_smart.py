import math
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

import conversations
import crypto_smart


def _alert(direction="venta", state="vigilando"):
    return {
        "id": 7,
        "chat_id": "42",
        "book": "ada_usd",
        "direccion": direction,
        "precio_objetivo": "0.30" if direction == "venta" else "0.23",
        "temporalidad": "1h",
        "periodos_promedio": 8,
        "perdida_promedio_pct": "10",
        "perdida_fuerza_pct": "40",
        "margen_precio_pct": "1.5",
        "actividad_ratio": "2",
        "confirmaciones_requeridas": 2,
        "subtemporalidades": ["30m", "10m", "5m"],
        "estado": state,
        "fuerza_pico_pct": "5",
    }


class SmartEvaluationTests(unittest.TestCase):
    def test_sell_strategy_detects_weakness_micro_confirmation_and_safety(self):
        analysis = {
            "precio": Decimal("0.295"),
            "frames": {
                "1h": {"cambio": Decimal("2"), "promedio": Decimal("5"), "actividad": Decimal("1")},
                "30m": {"cambio": Decimal("-0.2"), "promedio": Decimal("1"), "actividad": Decimal("2.5")},
                "10m": {"cambio": Decimal("0.1"), "promedio": Decimal("1"), "actividad": Decimal("2.1")},
                "5m": {"cambio": Decimal("0.5"), "promedio": Decimal("0.6"), "actividad": Decimal("1")},
            },
        }
        result = crypto_smart.evaluar(_alert(), analysis)
        self.assertEqual(result["average_loss"], Decimal("60"))
        self.assertEqual(result["force_loss"], Decimal("60"))
        self.assertTrue({"promedio", "fuerza", "micro", "seguridad"}.issubset(result["conditions"]))

    def test_buy_strategy_is_the_exact_directional_inverse(self):
        analysis = {
            "precio": Decimal("0.234"),
            "frames": {
                "1h": {"cambio": Decimal("-2"), "promedio": Decimal("-5"), "actividad": Decimal("1")},
                "30m": {"cambio": Decimal("0.1"), "promedio": Decimal("-1"), "actividad": Decimal("2.4")},
                "10m": {"cambio": Decimal("-0.1"), "promedio": Decimal("-1"), "actividad": Decimal("2.2")},
                "5m": {"cambio": Decimal("-0.6"), "promedio": Decimal("-0.7"), "actividad": Decimal("1")},
            },
        }
        result = crypto_smart.evaluar(_alert("compra"), analysis)
        self.assertEqual(result["average_loss"], Decimal("60"))
        self.assertTrue({"promedio", "fuerza", "micro", "seguridad"}.issubset(result["conditions"]))

    def test_waiting_strategy_activates_only_when_target_is_reached(self):
        alert = _alert(state="esperando")
        base = {"cambio": Decimal("1"), "promedio": Decimal("1"), "actividad": Decimal("1")}
        analysis = {"precio": Decimal("0.299"), "frames": {name: dict(base) for name in ("1h", "30m", "10m", "5m")}}
        self.assertFalse(crypto_smart.evaluar(alert, analysis)["activated"])
        analysis["precio"] = Decimal("0.30")
        result = crypto_smart.evaluar(alert, analysis)
        self.assertTrue(result["activated"])
        self.assertIn("objetivo", result["conditions"])


class SmartCalibrationTests(unittest.TestCase):
    @patch("crypto_smart._request_candles")
    def test_historical_calibration_returns_explainable_bounded_parameters(self, fetch):
        candles = []
        start = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
        for index in range(240):
            center = Decimal("100") + Decimal(str(math.sin(index / 5) * 8))
            open_price = center - Decimal(str(math.cos(index / 3)))
            candles.append({
                "time": start + index * 3600,
                "open": open_price,
                "close": center,
                "high": max(open_price, center) + Decimal("0.5"),
                "low": min(open_price, center) - Decimal("0.5"),
                "volume": Decimal(str(100 + (index % 12) * 10)),
            })
        fetch.return_value = candles
        result = crypto_smart.analizar_historico("ada_usd", "venta", "1h", "equilibrado")
        self.assertIn(result["periodos_promedio"], (4, 6, 8, 12))
        self.assertGreaterEqual(result["perdida_promedio_pct"], Decimal("8"))
        self.assertGreaterEqual(result["perdida_fuerza_pct"], Decimal("20"))
        self.assertGreaterEqual(result["margen_precio_pct"], Decimal("0.5"))
        self.assertEqual(result["confirmaciones"], 2)
        self.assertGreater(result["report"]["giros"], 0)


class SmartConversationTests(unittest.TestCase):
    def tearDown(self):
        conversations.conversaciones.clear()

    @patch("conversations._mostrar_smart_grid")
    @patch("conversations.crypto_alerts.es_usuario_premium", return_value=True)
    @patch("conversations.inicializar_conversaciones")
    def test_global_start_button_opens_smart_flow(self, initialize, premium, render):
        initialize.side_effect = lambda chat_id, user="": conversations.conversaciones.setdefault(
            chat_id, {"datos": {"usuario": user}, "estado": "", "wait_callback": False}
        )
        result = conversations.procesar_callback("42", "smart_start", "Andy", "private", 901)
        self.assertEqual(result, "")
        self.assertEqual(conversations.conversaciones["42"]["estado"], conversations.ESTADO_SMART_BOOK)
        render.assert_called_once()

    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.crypto_smart.silenciar_condicion", return_value=True)
    @patch("conversations.supabase_db.upsert_chat_info")
    def test_each_smart_condition_can_be_muted_globally(self, upsert, mute, edit):
        response = conversations.procesar_callback(
            "42", "smart_mute:7:promedio", "Andy", "private", 902
        )
        self.assertEqual(response, "")
        mute.assert_called_once_with(7, "42", "promedio")
        edit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
