import os
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

import conversations
import crypto_reports


class CryptoReportMathTests(unittest.TestCase):
    def test_trade_average_is_weighted_by_traded_amount(self):
        result = crypto_reports._weighted_average([
            {"price": "10", "amount": "1"},
            {"price": "20", "amount": "3"},
        ])
        self.assertEqual(result, Decimal("17.5"))

    def test_large_reports_are_split_below_telegram_limit(self):
        blocks = [f"Mercado {index}\n" + ("x" * 900) for index in range(12)]
        chunks = crypto_reports.dividir_informe("Informe", blocks, limit=1800)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1800 for chunk in chunks))
        self.assertTrue(all(chunk.startswith("Informe") for chunk in chunks))

    def test_partial_bitso_windows_are_explicit(self):
        data = {
            "provider": "Bitso", "last": Decimal("1"),
            "averages": {label: Decimal("1") for label, _ in crypto_reports.TIMEFRAMES},
            "partial": {label: label in ("4h", "1d") for label, _ in crypto_reports.TIMEFRAMES},
            "vwap_24h": Decimal("1.1"), "samples": 100,
            "coverage": 3600, "method": "VWAP de trades",
        }
        text = crypto_reports._source_block(data)
        self.assertIn("4h 1*", text)
        self.assertIn("cobertura 1.0 h", text)
        self.assertIn("VWAP oficial 24 h", text)


class CryptoReportProviderTests(unittest.TestCase):
    @patch("crypto_reports.crypto_strength.validar_producto")
    @patch("crypto_reports.crypto_alerts.obtener_ticker_bitso")
    @patch("crypto_reports.crypto_alerts.obtener_libros_bitso", return_value=["ada_usd"])
    def test_source_detection_keeps_exact_pair_on_both_exchanges(
        self, books, bitso_ticker, validate
    ):
        self.assertEqual(
            crypto_reports.detectar_fuentes("ada_usd"),
            ["bitso", "coinbase_exchange"],
        )


class CryptoReportConversationTests(unittest.TestCase):
    def tearDown(self):
        conversations.conversaciones.clear()

    @patch("conversations.crypto_reports.iniciar_informe_async")
    @patch("conversations.crypto_reports.listar_mercados", return_value=["ada_usd"])
    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.supabase_db.upsert_chat_info")
    def test_report_callback_starts_background_report_without_blocking(
        self, upsert, edit, markets, start
    ):
        response = conversations.procesar_callback(
            "42", "market_report", "Andy", "private", 700
        )
        self.assertEqual(response, "")
        start.assert_called_once_with("42")
        edit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
