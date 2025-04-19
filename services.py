import os
import requests, json
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def enviar_telegram(chat_id, tipo="texto", **kwargs):
    if tipo == "texto":
        return enviar_mensaje_texto(chat_id, kwargs.get("mensaje"), kwargs.get("formato"))
    elif tipo == "botones":
        return enviar_mensaje_con_botones(chat_id, kwargs.get("mensaje"), kwargs.get("botones"), kwargs.get("formato"))
    elif tipo == "documento":
        return enviar_documento(chat_id, kwargs.get("ruta"), kwargs.get("caption", ""), kwargs.get("formato"))
    elif tipo == "imagen":
        return enviar_imagen(chat_id, kwargs.get("ruta"), kwargs.get("caption", ""), kwargs.get("formato"))
    else:
        raise ValueError("Tipo de mensaje no soportado.")

def enviar_mensaje_texto(chat_id, mensaje, formato=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensaje
    }
    if formato:
        payload["parse_mode"] = formato
    return requests.post(url, json=payload)

def enviar_mensaje_con_botones(chat_id, mensaje, botones, formato=None):
    url = f"{BASE_URL}/sendMessage"
    keyboard = {
        "inline_keyboard": [[{"text": b["texto"], "callback_data": b["data"]}] for b in botones]
    }
    payload = {
        "chat_id": chat_id,
        "text": mensaje,
        "reply_markup": keyboard
    }
    if formato:
        payload["parse_mode"] = formato
    return requests.post(url, json=payload)

def enviar_documento(chat_id, ruta, caption="", formato=None):
    url = f"{BASE_URL}/sendDocument"
    with open(ruta, "rb") as doc:
        files = {"document": doc}
        data = {
            "chat_id": chat_id,
            "caption": caption
        }
        if formato:
            data["parse_mode"] = formato
        return requests.post(url, data=data, files=files)

def enviar_imagen(chat_id, ruta, caption="", formato=None):
    url = f"{BASE_URL}/sendPhoto"
    with open(ruta, "rb") as img:
        files = {"photo": img}
        data = {
            "chat_id": chat_id,
            "caption": caption
        }
        if formato:
            data["parse_mode"] = formato
        return requests.post(url, data=data, files=files)

def guardar_diccionario(diccionario):
    nombre_archivo = "mi_diccionario.json"
    try:
        with open(nombre_archivo, 'w', encoding="utf-8") as archivo:
            json.dump(diccionario, archivo, indent=4, ensure_ascii=False)
        print(f"El diccionario ha sido guardado exitosamente en el archivo: {nombre_archivo}")
    except Exception as e:
        print(f"Ocurrió un error al guardar el diccionario: {e}")
