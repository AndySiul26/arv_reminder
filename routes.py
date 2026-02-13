# -*- coding: utf-8 -*-

import json, os
from flask import Blueprint, request
import threading
from supabase_db import leer_modo_tester
from services import enviar_telegram
from conversations import procesar_mensaje, procesar_callback, mostrar_ayuda
from reminders import ping_otro_servidor

routes = Blueprint('routes', __name__)
TEST_USER_ID = os.environ.get("TELEGRAM_TEST_USER_ID")

@routes.route("/")
def index():
    return "Bot ARV Reminder activo"

@routes.route("/active", methods=["GET"])
def monitor_activo():
    print("Se recibio ping del monitor que mantiene activo este proyecto.")
    ping_otro_servidor()
    return "ok", 200

@routes.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    print("Mensaje entrante...")

    # --- MODO MANTENIMIENTO ---
    # Si la app arrancó sin base de datos, interceptamos todo aquí.
    from flask import current_app
    if current_app.config.get('MAINTENANCE_MODE'):
        print("⚠️ MODO MANTENIMIENTO ACTIVO")
        # Permitir solo webhook verification (si data es vacía o rara) o comandos básicos si se desea
        # Pero para simplicidad, chequeamos el contenido del mensaje
        if "message" in data:
            msg = data["message"]
            chat_id = str(msg["chat"]["id"])
            text = msg.get("text", "")
            
            # Permitir /ayuda o /start para que el usuario no sienta que el bot murió
            if text.startswith("/ayuda") or text.startswith("/start"):
                # Dejamos pasar para que 'manejar_mensaje' lo procese (que no usa DB para esto)
                pass 
            else:
                 # Responder con mensaje de mantenimiento y cortar
                enviar_telegram(chat_id, tipo="texto", mensaje="⚠️ *Servicio en Mantenimiento*\n\nEstamos experimentando problemas de conexión con la base de datos. El equipo ya está trabajando en ello.\n\nPor favor intenta más tarde.")
                return "ok", 200
        elif "callback_query" in data:
             # Responder a callbacks con alerta
             cb = data["callback_query"]
             chat_id = str(cb["from"]["id"])
             enviar_telegram(chat_id, tipo="texto", mensaje="⚠️ Servicio en mantenimiento. Intenta más tarde.")
             return "ok", 200
    
    if "message" in data:
        return manejar_mensaje(data)
    elif "callback_query" in data:
        return manejar_callback(data)

    return "ok", 200

def manejar_mensaje(data):
    msg = data["message"]
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text", "")
    nombre = msg["from"].get("first_name", "Usuario")

    # Revisar si es modo tester y si no o si el chat_id correspondiente al tester se continua
    if not rev_mod_tester_and_continue(chat_id=chat_id):
        return "ok", 200

    # Debug
    with open("debug_mensaje.json", "a", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False); f.write("\n")

    # Comandos predefinidos
    if text.startswith("/start"):
        enviar_telegram(
            chat_id, tipo="botones",
            mensaje=mostrar_ayuda(nombre),
            botones=[
                {"texto": "🆕 Nuevo Recordatorio", "data": "nuevo_recordatorio"},
                {"texto": "📋 Ver Pendientes",    "data": "ver_pendientes"}
            ]
        )
    elif text.startswith("/ayuda"):
        enviar_telegram(chat_id, tipo="texto", mensaje=mostrar_ayuda(nombre))
    
    # elif text.startswith("/pendientes"):
    #     enviar_telegram(chat_id, tipo="texto", mensaje="Pendientes en desarrollo")
    else:
        resp=None
        try:
            resp = procesar_mensaje(chat_id, text, nombre)
        
        except Exception as e:
            print("Error al manejar mensaje (desde rutas catched error):", str(e))
        finally:
            if resp:
                enviar_telegram(chat_id, tipo="texto", mensaje=resp)
        

    return "ok", 200

def manejar_callback(data):
    cb = data["callback_query"]
    chat_id = (str) (cb["from"]["id"])
    callback_data = cb["data"]
    nombre = cb["from"].get("first_name", "Usuario")
    tipo_chat = cb["message"]["chat"]["type"]
    message_id = cb["message"]["message_id"]

    # Debug
    with open("debug_callback.json", "a", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False); f.write("\n")

    resp = procesar_callback(chat_id, callback_data, nombre, tipo=tipo_chat, id_callback= message_id)
    if resp:
        enviar_telegram(chat_id, tipo="texto", mensaje=resp)

    return "ok", 200

def rev_mod_tester_and_continue(chat_id) -> bool:
    # Obtener información de modo
    mod_tester = leer_modo_tester()

    # Acciones segun modo
    if mod_tester and chat_id != (TEST_USER_ID):
        enviar_telegram(chat_id, tipo="texto", mensaje="BOT EN MANTENIMIENTO. Le avisaré en cuanto este disponible")
        return False

    return True