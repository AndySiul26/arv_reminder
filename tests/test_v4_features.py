import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

import conversations
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
