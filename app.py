from flask import Flask, request, jsonify
from services import enviar_telegram
import os
from dotenv import load_dotenv
import json
import atexit
import signal

# Importar módulos personalizados
from conversations import procesar_mensaje, procesar_callback, mostrar_ayuda
from supabase_db import inicializar_supabase
from reminders import iniciar_administrador, detener_administrador

load_dotenv()

app = Flask(__name__)

# Inicializar Supabase al arrancar la aplicación
inicializar_supabase()

# Iniciar el administrador de recordatorios
iniciar_administrador()

@app.route("/")
def index():
    return "Bot ARV Reminder activo"

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    print("mensaje entrante...")
    # Manejar mensajes regulares
    if "message" in data:
        return manejar_mensaje(data)
    
    # Manejar callbacks de botones
    elif "callback_query" in data:
        return manejar_callback(data)
    
    return "ok", 200

def manejar_mensaje(data):
    """Maneja los mensajes de texto recibidos"""
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "")
    nombre = data["message"]["from"]["first_name"]
    
    # Guardar el mensaje para depuración
    guardar_mensaje_debug(data)
    
    # Comandos básicos
    if text.startswith("/start"):
        mensaje = mostrar_ayuda(nombre)
        botones = [
            {"texto": "🆕 Nuevo Recordatorio", "data": "nuevo_recordatorio"},
            {"texto": "📋 Ver Pendientes", "data": "ver_pendientes"}
        ]
        enviar_telegram(chat_id, tipo="botones", mensaje=mensaje, botones=botones)
    
    elif text.startswith("/ayuda"):
        mensaje = mostrar_ayuda(nombre)
        enviar_telegram(chat_id, tipo="texto", mensaje=mensaje)
    
    elif text.startswith("/recordatorio"):
        mensaje = procesar_mensaje(chat_id, "/recordatorio", nombre)
        enviar_telegram(chat_id, tipo="texto", mensaje=mensaje)
    
    elif text.startswith("/pendientes"):
        # Esta funcionalidad se implementará después
        enviar_telegram(chat_id, tipo="texto", mensaje="Funcionalidad de pendientes en desarrollo")
    
    else:
        # Procesar cualquier otro mensaje dentro del flujo de conversación
        mensaje = procesar_mensaje(chat_id, text, nombre)
        enviar_telegram(chat_id, tipo="texto", mensaje=mensaje)
    
    return "ok", 200

def manejar_callback(data):
    """Maneja los callbacks de los botones inline"""
    chat_id = data["callback_query"]["from"]["id"]
    callback_data = data["callback_query"]["data"]
    nombre = data["callback_query"]["from"]["first_name"]
    
    # Guardar el callback para depuración
    guardar_mensaje_debug(data, tipo="callback")
    
    # Procesar el callback
    mensaje = procesar_callback(chat_id, callback_data, nombre)
    enviar_telegram(chat_id, tipo="texto", mensaje=mensaje)
    
    return "ok", 200

def guardar_mensaje_debug(data, tipo="mensaje"):
    """Guarda los mensajes y callbacks para depuración"""
    try:
        with open(f"debug_{tipo}.json", "a") as f:
            f.write(json.dumps(data) + "\n")
    except Exception as e:
        print(f"Error al guardar debug: {e}")

def cerrar_aplicacion():
    """Cierra correctamente los recursos al terminar la aplicación"""
    print("Cerrando aplicación...")
    detener_administrador()
    print("Recursos liberados")
    exit()

# Registrar función para ejecutar al salir
atexit.register(cerrar_aplicacion)

# Registrar manejadores de señales
signal.signal(signal.SIGINT, lambda s, f: cerrar_aplicacion())
signal.signal(signal.SIGTERM, lambda s, f: cerrar_aplicacion())

# if __name__ == "__main__":
#     app.run(debug=True) 