import os
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

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
    @patch("crypto_reports.requests.get")
    def test_binance_uses_public_data_fallback_after_regional_block(self, get):
        blocked = Mock()
        blocked.raise_for_status.side_effect = crypto_reports.requests.HTTPError("451")
        fallback = Mock()
        fallback.raise_for_status.return_value = None
        fallback.json.return_value = {"symbols": []}
        get.side_effect = [blocked, fallback]

        self.assertEqual(crypto_reports._binance_get("exchangeInfo"), {"symbols": []})
        self.assertEqual(get.call_count, 2)
        self.assertIn("data-api.binance.vision", get.call_args_list[1].args[0])

    @patch("crypto_reports.crypto_strength.validar_producto")
    @patch("crypto_reports.crypto_alerts.obtener_ticker_bitso")
    @patch("crypto_reports.crypto_alerts.obtener_libros_bitso", return_value=["ada_usd"])
    def test_source_detection_keeps_exact_pair_on_both_exchanges(
        self, books, bitso_ticker, validate
    ):
        with patch("crypto_reports._binance_comparable_markets", return_value=[]):
            self.assertEqual(
                crypto_reports.detectar_fuentes("ada_usd"),
                ["bitso", "coinbase_exchange"],
            )

    @patch("crypto_reports._binance_markets")
    def test_binance_usd_request_finds_labeled_stablecoin_pairs(self, markets):
        markets.return_value = [
            {"symbol": "GALAUSDT", "baseAsset": "GALA", "quoteAsset": "USDT"},
            {"symbol": "GALATUSD", "baseAsset": "GALA", "quoteAsset": "TUSD"},
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"},
        ]
        result = crypto_reports._binance_comparable_markets("gala_usd")
        self.assertEqual([item["symbol"] for item in result], ["GALAUSDT", "GALATUSD"])

    def test_binance_comparison_discloses_non_exact_quote(self):
        text = crypto_reports._source_block({
            "provider": "Binance Spot · GALA/USDT",
            "last": Decimal("0.02"),
            "averages": {label: Decimal("0.02") for label, _ in crypto_reports.TIMEFRAMES},
            "partial": {label: False for label, _ in crypto_reports.TIMEFRAMES},
            "vwap_24h": None, "samples": 2, "coverage": 86400,
            "method": "VWAP", "quote_note": "Comparativa en USDT; no es USD exacto.",
        })
        self.assertIn("Binance Spot · GALA/USDT", text)
        self.assertIn("no es USD exacto", text)


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
