import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

import conversations
import crypto_alerts
import reminders


class DurationParsingTests(unittest.TestCase):
    def test_minutes_hours_and_days(self):
        cases = {
            "5": 5,
            "45 minutos": 45,
            "10 min": 10,
            "2h": 120,
            "2 horas": 120,
            "1 día": 1440,
            "3 dias": 4320,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    conversations._parsear_duracion_aplazamiento(raw),
                    expected,
                )

    def test_invalid_or_excessive_duration(self):
        for raw in ("", "cero", "0", "-5", "2 semanas", "31 días"):
            with self.subTest(raw=raw):
                self.assertIsNone(
                    conversations._parsear_duracion_aplazamiento(raw)
                )


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {
                "id": 10,
                "nombre_tarea": "Pagar agua",
                "descripcion": "Casa principal",
                "notificado": False,
            },
            {
                "id": 11,
                "nombre_tarea": "Comprar café",
                "descripcion": "Supermercado",
                "notificado": True,
            },
            {
                "id": 12,
                "nombre_tarea": "Llamar a Andy",
                "descripcion": "Revisar el servidor",
                "notificado": False,
            },
        ]

    def test_searches_name_description_and_id_case_insensitively(self):
        self.assertEqual(
            [r["id"] for r in conversations._filtrar_recordatorios(
                self.records, busqueda="CAFÉ"
            )],
            [11],
        )
        self.assertEqual(
            [r["id"] for r in conversations._filtrar_recordatorios(
                self.records, busqueda="servidor"
            )],
            [12],
        )
        self.assertEqual(
            [r["id"] for r in conversations._filtrar_recordatorios(
                self.records, busqueda="10"
            )],
            [10],
        )

    def test_pending_filter_combines_with_search(self):
        result = conversations._filtrar_recordatorios(
            self.records,
            filtro="pendientes",
            busqueda="a",
        )
        self.assertEqual([r["id"] for r in result], [10, 12])


class CryptoPriceTests(unittest.TestCase):
    def test_parses_common_price_formats_without_float_rounding(self):
        cases = {
            "1500000": Decimal("1500000"),
            "$1,500,000 MXN": Decimal("1500000"),
            "1.500.000,25": Decimal("1500000.25"),
            "1,500,000.25": Decimal("1500000.25"),
            "0,25": Decimal("0.25"),
            "0.00001234": Decimal("0.00001234"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(crypto_alerts.parsear_precio(raw), expected)

    def test_rejects_invalid_or_non_positive_prices(self):
        for raw in ("", "cero", "0", "-10", "$"):
            with self.subTest(raw=raw):
                self.assertIsNone(crypto_alerts.parsear_precio(raw))

    def test_greater_and_lower_conditions_include_equality(self):
        self.assertTrue(
            crypto_alerts.es_condicion_cumplida("gte", "100", "100")
        )
        self.assertTrue(
            crypto_alerts.es_condicion_cumplida("lte", "100", "100")
        )
        self.assertFalse(
            crypto_alerts.es_condicion_cumplida("gte", "99.99", "100")
        )
        self.assertFalse(
            crypto_alerts.es_condicion_cumplida("lte", "100.01", "100")
        )

    def test_custom_rearm_percentage_is_validated(self):
        self.assertEqual(
            crypto_alerts.parsear_porcentaje("7,5%"),
            Decimal("7.5"),
        )
        for raw in ("", "0", "-1", "101", "mucho"):
            with self.subTest(raw=raw):
                self.assertIsNone(crypto_alerts.parsear_porcentaje(raw))

    def test_old_single_limit_alert_is_normalized(self):
        alert = crypto_alerts.normalizar_alerta({
            "estado": "activa",
            "operador": "gte",
            "precio_objetivo": "100",
        })
        self.assertEqual(alert["precio_max"], "100")
        self.assertIsNone(alert["precio_min"])
        self.assertTrue(alert["max_armada"])
        self.assertFalse(alert["min_armada"])


class CryptoMonitorTests(unittest.TestCase):
    @patch("crypto_alerts._actualizar_alerta")
    @patch("crypto_alerts.enviar_mensaje_con_grid")
    @patch("crypto_alerts.obtener_precio_actual")
    @patch("crypto_alerts.listar_alertas_activas")
    def test_groups_alerts_by_book_and_marks_only_after_telegram_success(
        self,
        list_active,
        get_price,
        send_grid,
        update_alert,
    ):
        list_active.return_value = [
            {
                "id": 1,
                "chat_id": "42",
                "book": "btc_mxn",
                "precio_max": "100",
                "precio_min": None,
                "max_armada": True,
                "min_armada": False,
            },
            {
                "id": 2,
                "chat_id": "43",
                "book": "btc_mxn",
                "precio_min": "200",
                "precio_max": None,
                "min_armada": True,
                "max_armada": False,
            },
        ]
        get_price.return_value = {
            "book": "btc_mxn",
            "last": Decimal("150"),
            "created_at": "2026-07-25T00:00:00+00:00",
        }
        send_grid.return_value = Mock(status_code=200)
        update_alert.return_value = {"id": 1}

        result = crypto_alerts.MonitorCriptoAlertas().verificar_una_vez()

        get_price.assert_called_once_with("btc_mxn")
        self.assertEqual(send_grid.call_count, 2)
        self.assertEqual(update_alert.call_count, 2)
        self.assertEqual(result["disparadas"], 2)

    @patch("crypto_alerts._actualizar_alerta")
    @patch("crypto_alerts.enviar_mensaje_con_grid")
    @patch("crypto_alerts.obtener_precio_actual")
    @patch("crypto_alerts.listar_alertas_activas")
    def test_does_not_send_when_condition_is_not_met(
        self,
        list_active,
        get_price,
        send_grid,
        update_alert,
    ):
        list_active.return_value = [{
            "id": 1,
            "chat_id": "42",
            "book": "btc_mxn",
            "precio_max": "200",
            "precio_min": None,
            "max_armada": True,
            "min_armada": False,
        }]
        get_price.return_value = {
            "book": "btc_mxn",
            "last": Decimal("150"),
            "created_at": "2026-07-25T00:00:00+00:00",
        }

        result = crypto_alerts.MonitorCriptoAlertas().verificar_una_vez()

        send_grid.assert_not_called()
        update_alert.assert_not_called()
        self.assertEqual(result["disparadas"], 0)

    @patch("crypto_alerts._actualizar_alerta")
    @patch("crypto_alerts.enviar_mensaje_con_grid")
    @patch("crypto_alerts.obtener_precio_actual")
    @patch("crypto_alerts.listar_alertas_activas")
    def test_does_not_disarm_when_telegram_rejects_notification(
        self,
        list_active,
        get_price,
        send_grid,
        update_alert,
    ):
        list_active.return_value = [{
            "id": 1,
            "chat_id": "42",
            "book": "btc_mxn",
            "precio_min": None,
            "precio_max": "100",
            "min_armada": False,
            "max_armada": True,
        }]
        get_price.return_value = {
            "book": "btc_mxn",
            "last": Decimal("101"),
            "created_at": "2026-07-25T00:00:00+00:00",
        }
        send_grid.return_value = Mock(status_code=500)

        result = crypto_alerts.MonitorCriptoAlertas().verificar_una_vez()

        update_alert.assert_not_called()
        self.assertEqual(result["disparadas"], 0)

    def test_lower_and_upper_rearm_use_hysteresis(self):
        lower = {
            "precio_min": "100",
            "precio_max": None,
            "min_armada": False,
            "max_armada": False,
            "rearme_porcentaje": "5",
            "lado_disparado": "min",
        }
        self.assertEqual(
            crypto_alerts._aplicar_rearme(lower, Decimal("104.99")),
            {},
        )
        self.assertTrue(
            crypto_alerts._aplicar_rearme(
                lower, Decimal("105")
            )["min_armada"]
        )

        upper = {
            "precio_min": None,
            "precio_max": "200",
            "min_armada": False,
            "max_armada": False,
            "rearme_porcentaje": "10",
            "lado_disparado": "max",
        }
        self.assertEqual(
            crypto_alerts._aplicar_rearme(upper, Decimal("180.01")),
            {},
        )
        self.assertTrue(
            crypto_alerts._aplicar_rearme(
                upper, Decimal("180")
            )["max_armada"]
        )

    def test_constant_alert_repeats_only_after_cooldown(self):
        now = datetime.now(timezone.utc)
        alert = {
            "aviso_constante": True,
            "aviso_detenido": False,
            "lado_disparado": "max",
            "precio_max": "100",
            "ultima_notificacion_en": (
                now - timedelta(seconds=61)
            ).isoformat(),
        }
        self.assertTrue(crypto_alerts._debe_repetir(alert, "101", now))
        alert["ultima_notificacion_en"] = now.isoformat()
        self.assertFalse(crypto_alerts._debe_repetir(alert, "101", now))
        alert["aviso_detenido"] = True
        self.assertFalse(crypto_alerts._debe_repetir(alert, "101", now))


class BitsoStreamTests(unittest.TestCase):
    def test_trade_message_updates_latest_price(self):
        stream = crypto_alerts.BitsoPriceStream()
        stream._on_message(None, (
            '{"type":"trades","book":"btc_mxn","payload":['
            '{"r":"123.45","x":"1784937600000"}]}'
        ))
        price = stream.obtener(
            "btc_mxn", max_age_seconds=10**9, permitir_rest=False
        )
        self.assertEqual(price["last"], Decimal("123.45"))
        self.assertEqual(price["source"], "websocket")


class CryptoConversationTests(unittest.TestCase):
    def tearDown(self):
        conversations.conversaciones.clear()

    @patch("conversations.crypto_alerts.es_usuario_premium")
    def test_non_premium_user_is_blocked(self, is_premium):
        is_premium.return_value = False
        response = conversations.iniciar_criptoalerta("42", "Andy")
        self.assertIn("requiere acceso premium", response)

    def test_band_rejects_crossed_limits(self):
        conversations.conversaciones["42"] = {
            "estado": conversations.ESTADO_CRIPTO_PRECIO_MAX,
            "wait_callback": False,
            "id_callback": None,
            "datos": {
                "crypto_book": "btc_mxn",
                "crypto_precio_min": Decimal("100"),
            },
        }
        response = conversations._guardar_limite_crypto(
            "42", "99", "max"
        )
        self.assertIn("debe ser mayor", response)

    @patch("conversations._iniciar_actualizador_precio_crypto")
    @patch("conversations.crypto_alerts.bitso_price_stream.suscribir")
    @patch("conversations.crypto_alerts.bitso_price_stream.iniciar")
    @patch("conversations.crypto_alerts.crear_alerta_banda")
    @patch("conversations.crypto_alerts.obtener_precio_actual")
    @patch("conversations.crypto_alerts.obtener_libros_bitso")
    @patch("conversations.crypto_alerts.es_usuario_premium")
    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.enviar_mensaje_con_grid")
    @patch("conversations.guardar_estado")
    @patch("conversations.supabase_db.upsert_chat_info")
    @patch("conversations.inicializar_conversaciones")
    def test_complete_crypto_alert_flow(
        self,
        init_conversation,
        upsert,
        save_state,
        send_grid,
        edit_grid,
        is_premium,
        get_books,
        get_price,
        create_alert,
        start_stream,
        subscribe,
        start_live,
    ):
        conversations.conversaciones["42"] = {
            "estado": "",
            "wait_callback": False,
            "id_callback": None,
            "datos": {"usuario": "Andy", "zona_horaria": "UTC"},
            "recordatorios_aviso_constante": {},
        }
        init_conversation.return_value = conversations.conversaciones
        is_premium.return_value = True
        get_books.return_value = ["btc_mxn"]
        get_price.return_value = {
            "book": "btc_mxn",
            "last": Decimal("1400000"),
            "created_at": "2026-07-25T00:00:00+00:00",
        }
        send_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"result": {"message_id": 800}},
        )
        edit_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"result": {"message_id": 800}},
        )
        create_alert.return_value = {"id": 9}

        conversations.iniciar_criptoalerta("42", "Andy")
        conversations.procesar_callback(
            "42", "crypto_book:btc_mxn", "Andy", "private", 800
        )
        conversations.procesar_callback(
            "42", "crypto_set:min", "Andy", "private", 800
        )
        conversations.procesar_mensaje("42", "1300000", "Andy")
        conversations.procesar_callback(
            "42", "crypto_set:max", "Andy", "private", 800
        )
        conversations.procesar_mensaje("42", "1500000", "Andy")
        conversations.procesar_callback(
            "42", "crypto_band_continue", "Andy", "private", 800
        )
        conversations.procesar_callback(
            "42", "crypto_mode:constant", "Andy", "private", 800
        )
        conversations.procesar_callback(
            "42", "crypto_rearm:10", "Andy", "private", 800
        )

        create_alert.assert_called_once_with(
            "42",
            "Andy",
            "btc_mxn",
            Decimal("1300000"),
            Decimal("1500000"),
            True,
            Decimal("10"),
        )
        self.assertNotIn("42", conversations.conversaciones)

    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.crypto_alerts.detener_alerta_constante")
    @patch("conversations.supabase_db.upsert_chat_info")
    def test_constant_stop_callback_is_global_and_edits_notice(
        self, upsert, stop_alert, edit_grid
    ):
        stop_alert.return_value = True
        response = conversations.procesar_callback(
            "42", "crypto_stop:9", "Andy", "private", 800
        )
        self.assertEqual(response, "")
        stop_alert.assert_called_once_with(9, "42")
        edit_grid.assert_called_once()


class UnifiedManagerTests(unittest.TestCase):
    def tearDown(self):
        conversations.conversaciones.clear()

    @patch("conversations.enviar_mensaje_con_grid")
    @patch("conversations.supabase_db.obtener_recordatorios_usuario")
    @patch("conversations.inicializar_conversaciones")
    def test_pending_command_opens_selectable_unified_list(
        self,
        init_conversation,
        get_records,
        send_grid,
    ):
        conversations.conversaciones["42"] = {
            "estado": "",
            "datos": {"zona_horaria": "UTC"},
            "recordatorios_aviso_constante": {},
        }
        init_conversation.return_value = conversations.conversaciones
        get_records.return_value = [
            {
                "id": 1,
                "nombre_tarea": "Pendiente",
                "descripcion": "Uno",
                "fecha_hora": "2026-07-25T12:00:00+00:00",
                "notificado": False,
            },
            {
                "id": 2,
                "nombre_tarea": "Terminado",
                "descripcion": "Dos",
                "fecha_hora": "2026-07-24T12:00:00+00:00",
                "notificado": True,
            },
        ]
        send_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"result": {"message_id": 500}},
        )

        conversations.iniciar_gestor_recordatorios(
            "42", "Andy", filtro="pendientes"
        )

        state = conversations.conversaciones["42"]
        self.assertEqual(state["estado"], conversations.ESTADO_GESTOR_LISTA)
        self.assertEqual(
            [r["id"] for r in state["datos"]["gestor_lista"]],
            [1],
        )
        rows = send_grid.call_args.args[2]
        self.assertEqual(rows[0][0]["data"], "gestor_detalle:0")
        self.assertTrue(
            any(
                button["data"] == "gestor_buscar"
                for row in rows
                for button in row
            )
        )

    @patch("conversations.enviar_mensaje_con_grid")
    @patch("conversations.inicializar_conversaciones")
    def test_search_prompt_saves_the_message_that_will_be_replaced(
        self,
        init_conversation,
        send_grid,
    ):
        conversations.conversaciones["42"] = {
            "estado": "",
            "datos": {"zona_horaria": "UTC"},
            "recordatorios_aviso_constante": {},
        }
        init_conversation.return_value = conversations.conversaciones
        send_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"result": {"message_id": 501}},
        )

        conversations.iniciar_gestor_recordatorios(
            "42", "Andy", iniciar_busqueda=True
        )

        self.assertEqual(
            conversations.conversaciones["42"]["datos"]["gestor_message_id"],
            501,
        )

    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.supabase_db.obtener_recordatorios_usuario")
    def test_search_shows_progress_before_replacing_it_with_results(
        self,
        get_records,
        edit_grid,
    ):
        conversations.conversaciones["42"] = {
            "estado": conversations.ESTADO_GESTOR_BUSQUEDA,
            "datos": {
                "zona_horaria": "UTC",
                "gestor_message_id": 501,
                "gestor_filtro": "todos",
            },
            "recordatorios_aviso_constante": {},
        }
        edit_grid.return_value = Mock(status_code=200)
        get_records.return_value = []

        conversations._ejecutar_busqueda_gestor("42", "agua")

        self.assertEqual(edit_grid.call_count, 2)
        self.assertIn("Buscando...", edit_grid.call_args_list[0].args[2])
        self.assertIn("Resultados: 0", edit_grid.call_args_list[1].args[2])
        self.assertEqual(edit_grid.call_args_list[0].args[1], 501)
        self.assertEqual(edit_grid.call_args_list[1].args[1], 501)


class BatchSelectionTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {
                "id": index + 1,
                "nombre_tarea": f"Recordatorio {index + 1}",
                "fecha_hora": "2026-07-25T12:00:00+00:00",
            }
            for index in range(6)
        ]
        conversations.conversaciones["42"] = {
            "estado": conversations.ESTADO_BATCH_SELECT,
            "wait_callback": True,
            "id_callback": 700,
            "datos": {
                "zona_horaria": "UTC",
                "batch_lista": self.records,
                "batch_seleccionados": [],
                "batch_pagina": 0,
                "batch_message_id": 700,
            },
            "recordatorios_aviso_constante": {},
        }

    def tearDown(self):
        conversations.conversaciones.clear()

    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.supabase_db.upsert_chat_info")
    def test_individual_taps_accumulate_and_refresh_the_grid(
        self,
        upsert,
        edit_grid,
    ):
        edit_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"result": {"message_id": 700}},
        )

        conversations.procesar_callback(
            "42", "sel:1", "Andy", "private", 700
        )
        conversations.procesar_callback(
            "42", "sel:3", "Andy", "private", 700
        )

        state = conversations.conversaciones["42"]
        self.assertEqual(state["datos"]["batch_seleccionados"], [1, 3])
        self.assertTrue(state["wait_callback"])
        rows = edit_grid.call_args.args[3]
        labels = [button["texto"] for row in rows for button in row]
        data = [button["data"] for row in rows for button in row]
        self.assertTrue(any("2." in label and "✅" in label for label in labels))
        self.assertTrue(any("4." in label and "✅" in label for label in labels))
        self.assertIn("batch_editar", data)
        self.assertTrue(
            any("Editar seleccionados (2)" in label for label in labels)
        )

    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations.supabase_db.upsert_chat_info")
    def test_pagination_keeps_previous_selections(
        self,
        upsert,
        edit_grid,
    ):
        edit_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"result": {"message_id": 700}},
        )

        conversations.procesar_callback(
            "42", "sel:1", "Andy", "private", 700
        )
        conversations.procesar_callback(
            "42", "pg:1", "Andy", "private", 700
        )

        state = conversations.conversaciones["42"]
        self.assertEqual(state["datos"]["batch_seleccionados"], [1])
        self.assertEqual(state["datos"]["batch_pagina"], 1)
        self.assertTrue(state["wait_callback"])


class SnoozeTests(unittest.TestCase):
    def tearDown(self):
        conversations.conversaciones.clear()

    @patch("conversations.editar_mensaje_con_grid")
    @patch("conversations._quitar_aviso_constante_guardado")
    @patch("conversations.supabase_db.obtener_info_chat")
    @patch("conversations.supabase_db.aplazar_recordatorio")
    @patch("conversations.supabase_db.obtener_recordatorio_por_id_y_chat")
    def test_snooze_reschedules_and_resets_notification(
        self,
        get_record,
        update_record,
        get_chat,
        clear_constant,
        edit_message,
    ):
        get_record.return_value = {
            "id": 77,
            "chat_id": "42",
            "nombre_tarea": "Prueba",
            "aviso_constante": True,
            "repeticion_creada": True,
        }
        update_record.side_effect = lambda record_id, chat_id, new_date: {
            "id": record_id,
            "chat_id": chat_id,
            "fecha_hora": new_date,
        }
        get_chat.return_value = {"zona_horaria": "UTC"}

        before = datetime.now(timezone.utc)
        conversations.aplazar_recordatorio_chat("42", 77, 10, message_id=999)
        after = datetime.now(timezone.utc)

        update_record.assert_called_once()
        new_date = datetime.fromisoformat(update_record.call_args.args[2])
        self.assertGreaterEqual(new_date, before.replace(microsecond=0))
        self.assertGreater(new_date, after)
        self.assertLessEqual((new_date - before).total_seconds(), 601)
        clear_constant.assert_called_once_with("42", 77)
        edit_message.assert_called_once()
        self.assertEqual(edit_message.call_args.args[0:2], ("42", 999))
        self.assertEqual(edit_message.call_args.args[3], [])

    @patch("conversations.aplazar_recordatorio_chat")
    @patch("conversations.supabase_db.upsert_chat_info")
    def test_snooze_callback_has_priority_over_other_open_flow(
        self,
        upsert,
        snooze,
    ):
        conversations.conversaciones["42"] = {
            "estado": conversations.ESTADO_NOMBRE_TAREA,
            "datos": {},
            "wait_callback": True,
        }

        conversations.procesar_callback(
            "42",
            "snooze:77:20",
            "Andy",
            "private",
            999,
        )

        snooze.assert_called_once_with("42", 77, 20, 999)


class ReminderButtonTests(unittest.TestCase):
    @patch("reminders.supabase_db.marcar_como_notificado")
    @patch("reminders.enviar_mensaje_con_grid")
    @patch("reminders.conversations.inicializar_conversaciones")
    def test_normal_reminder_contains_all_snooze_buttons(
        self,
        init_conversation,
        send_grid,
        mark_notified,
    ):
        init_conversation.return_value = {
            "42": {"datos": {"zona_horaria": "UTC"}}
        }
        send_grid.return_value = Mock(status_code=200)
        record = {
            "id": 25,
            "chat_id": "42",
            "usuario": "Andy",
            "nombre_tarea": "Pagar servicio",
            "descripcion": "Prueba",
            "fecha_hora": "2026-07-24T12:00:00+00:00",
            "aviso_constante": False,
            "repetir": False,
            "repeticion_creada": False,
            "intervalo_repeticion": "",
            "intervalos": 0,
        }

        reminders.AdministradorRecordatorios()._enviar_recordatorio(record)

        rows = send_grid.call_args.args[2]
        callback_data = [
            button["data"]
            for row in rows
            for button in row
        ]
        self.assertEqual(
            callback_data,
            [
                "snooze:25:5",
                "snooze:25:10",
                "snooze:25:20",
                "snooze_custom:25",
            ],
        )
        mark_notified.assert_called_once_with(25)

    @patch("reminders.actualizar_estado_chat_id")
    @patch("reminders.supabase_db.marcar_como_notificado")
    @patch("reminders.enviar_mensaje_con_grid")
    @patch("reminders.conversations.inicializar_conversaciones")
    def test_constant_reminder_also_contains_stop_button(
        self,
        init_conversation,
        send_grid,
        mark_notified,
        save_state,
    ):
        init_conversation.return_value = {
            "42": {
                "datos": {"zona_horaria": "UTC"},
                "recordatorios_aviso_constante": {},
            }
        }
        send_grid.return_value = Mock(
            status_code=200,
            json=lambda: {"ok": True, "result": {"message_id": 600}},
        )
        record = {
            "id": 26,
            "chat_id": "42",
            "usuario": "Andy",
            "nombre_tarea": "Alarma",
            "descripcion": "Constante",
            "fecha_hora": "2026-07-24T12:00:00+00:00",
            "aviso_constante": True,
            "repetir": False,
            "repeticion_creada": False,
            "intervalo_repeticion": "",
            "intervalos": 0,
        }

        reminders.AdministradorRecordatorios()._enviar_recordatorio(record)

        rows = send_grid.call_args.args[2]
        self.assertEqual(rows[-1][0]["data"], "parar")
        mark_notified.assert_called_once_with(26)


if __name__ == "__main__":
    unittest.main()
