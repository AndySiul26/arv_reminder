"""
Utilidades para configurar el webhook de Telegram.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def configurar_webhook(webhook_url):
    """
    Configura el webhook para el bot de Telegram.
    
    Args:
        webhook_url (str): URL completa del webhook (por ejemplo, 'https://tu-dominio.com/webhook')
    
    Returns:
        bool: True si se configuró correctamente, False en caso contrario.
    """
    if not TELEGRAM_TOKEN:
        print("Error: No se encontró el token de Telegram en las variables de entorno")
        return False
    
    try:
        # Eliminar webhook existente
        requests.get(f"{BASE_URL}/deleteWebhook")
        
        # Configurar nuevo webhook
        response = requests.post(
            f"{BASE_URL}/setWebhook",
            json={"url": webhook_url}
        )
        
        if response.status_code == 200 and response.json().get("ok"):
            print(f"Webhook configurado correctamente en: {webhook_url}")
            return True
        else:
            print(f"Error al configurar webhook: {response.text}")
            return False
    
    except Exception as e:
        print(f"Error al configurar webhook: {e}")
        return False

def obtener_info_webhook():
    """
    Obtiene información sobre el webhook actual.
    
    Returns:
        dict: Información del webhook o None si hay error.
    """
    if not TELEGRAM_TOKEN:
        print("Error: No se encontró el token de Telegram en las variables de entorno")
        return None
    
    try:
        response = requests.get(f"{BASE_URL}/getWebhookInfo")
        
        if response.status_code == 200:
            webhook_info = response.json()
            print(f"Información del webhook: {webhook_info}")
            return webhook_info
        else:
            print(f"Error al obtener información del webhook: {response.text}")
            return None
    
    except Exception as e:
        print(f"Error al obtener información del webhook: {e}")
        return None

if __name__ == "__main__":
    # Script para configurar el webhook manualmente
    webhook_url = input("Introduce la URL del webhook (por ejemplo, https://tu-dominio.com/webhook): ")
    
    if configurar_webhook(webhook_url):
        print("✅ Webhook configurado correctamente")
    else:
        print("❌ Error al configurar el webhook")
    
    # Obtener información del webhook
    obtener_info_webhook()