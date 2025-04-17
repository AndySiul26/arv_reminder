# test_telegram.py
from services import enviar_telegram

# reemplaza con tu ID de Telegram (puedes obtenerlo con https://t.me/userinfobot)
chat_id = 6934945886  

# Texto simple
enviar_telegram(chat_id, tipo="texto", mensaje="¡Hola Luis! Esto es un recordatorio.")

# Con botones
enviar_telegram(
    chat_id,
    tipo="botones",
    mensaje="¿Quieres confirmar tu tarea?",
    botones=[
        {"texto": "✅ Sí", "data": "confirmar"},
        {"texto": "❌ No", "data": "cancelar"}
    ]
)
