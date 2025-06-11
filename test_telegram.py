# test_telegram.py
from services import enviar_telegram
import os

# reemplaza con tu ID de Telegram (puedes obtenerlo con https://t.me/userinfobot)
chat_id = os.environ.get("TELEGRAM_TEST_USER_ID")


# Texto simple
enviar_telegram(
    chat_id=chat_id,
    tipo="texto",
    mensaje="*Recordatorio importante:* _Revisar el código antes de dormir_",
    formato="Markdown"
)

enviar_telegram(
    chat_id=chat_id,
    tipo="botones",
    mensaje="<b>¿Ya completaste tu tarea?</b>",
    botones=[{"texto": "Sí", "data": "confirmado"}, {"texto": "Aún no", "data": "pendiente"}],
    formato="HTML"
)


enviar_telegram(
    chat_id=chat_id,
    tipo="botones",
    mensaje="*¿Ya completaste tu tarea?*",
    botones=[{"texto": "Sí", "data": "confirmado"}, {"texto": "NEL PERRO", "data": "pendiente"}],
    formato="markdown"
)


