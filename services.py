import os
import requests, json
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def enviar_telegram(chat_id, tipo="texto", **kwargs):
    ret = None
    if tipo == "texto":
        ret= enviar_mensaje_texto(chat_id, kwargs.get("mensaje"), kwargs.get("formato"))
    elif tipo == "botones":
        ret= enviar_mensaje_con_botones(chat_id, kwargs.get("mensaje"), kwargs.get("botones"), kwargs.get("formato"))
    elif tipo == "documento":
        ret= enviar_documento(chat_id, kwargs.get("ruta"), kwargs.get("caption", ""), kwargs.get("formato"))
    elif tipo == "imagen":
        ret= enviar_imagen(chat_id, kwargs.get("ruta"), kwargs.get("caption", ""), kwargs.get("formato"))
    else:
        raise ValueError("Tipo de mensaje no soportado.")
    
    # Funcion de guardado de datos 
    guardar_datos = kwargs.pop("func_guardado_data", None)
    if guardar_datos:
        guardar_datos(chat_id, ret)

    return ret

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

def editar_mensaje_texto(chat_id, message_id, nuevo_texto, formato=None, guardar_datos=None, counter_recursivity=0):
    url = f"{BASE_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": nuevo_texto
    }
    if formato:
        payload["parse_mode"] = formato
    ret= requests.post(url, json=payload)
    if ret.status_code != 200:
        if counter_recursivity<2:
            ret = editar_mensaje_texto(chat_id=chat_id, message_id=message_id, nuevo_texto=nuevo_texto, formato=None, guardar_datos=guardar_datos, counter_recursivity=counter_recursivity+1)
        else:
            return ret
        # ret = enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=nuevo_texto, formato=formato)

    # Funcion de guardado de datos 
    
    if guardar_datos:
        guardar_datos(chat_id, ret)

    return ret

def editar_mensaje_con_botones(chat_id, message_id, nuevo_mensaje, nuevos_botones, formato=None, guardar_datos= None):
    """
    Edita el texto y los botones de un mensaje previamente enviado por el bot.

    Parámetros:
    - chat_id: ID del chat donde se envió el mensaje.
    - message_id: ID del mensaje que se desea editar.
    - nuevo_mensaje: El nuevo texto del mensaje.
    - nuevos_botones: Lista de botones con estructura [{"texto": "Aceptar", "data": "accion_aceptar"}, ...].
    - formato: (Opcional) "HTML" o "MarkdownV2" para aplicar formato.
    """
    url = f"{BASE_URL}/editMessageText"
    keyboard = {
        "inline_keyboard": [[{"text": b["texto"], "callback_data": b["data"]}] for b in nuevos_botones]
    }

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": nuevo_mensaje,
        "reply_markup": keyboard
    }

    if formato:
        payload["parse_mode"] = formato

    ret = requests.post(url, json=payload)

    if guardar_datos:
        guardar_datos(chat_id, ret)

    return ret

def editar_botones_mensaje(chat_id, message_id, nuevos_botones, guardar_datos=None):
    """
    Edita únicamente los botones (inline keyboard) de un mensaje previamente enviado por el bot.

    Parámetros:
    - chat_id: ID del chat donde se envió el mensaje.
    - message_id: ID del mensaje que se desea editar.
    - nuevos_botones: Lista de botones con estructura [{"texto": "Aceptar", "data": "accion_aceptar"}, ...].
    """
    url = f"{BASE_URL}/editMessageReplyMarkup"
    keyboard = {
        "inline_keyboard": [[{"text": b["texto"], "callback_data": b["data"]}] for b in nuevos_botones]
    }

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": keyboard
    }

    ret = requests.post(url, json=payload)
    if guardar_datos:
        guardar_datos(chat_id, ret)

    return ret


def eliminar_mensaje(chat_id, message_id):
    url = f"{BASE_URL}/deleteMessage"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }
    return requests.post(url, json=payload)
