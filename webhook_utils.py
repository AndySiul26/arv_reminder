import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def set_webhook(webhook_url=None):
    try:
        if not webhook_url:
            webhook_url = input("WEBHOOK URL: ").strip()
        
        if "webhook" not in webhook_url:
            webhook_url += "/webhook"
        
        print(f"Usando URL: {webhook_url}")
        
        response = requests.get(
            f"{BASE_URL}/setWebhook",
            params={"url": webhook_url},
            timeout=10
        )
        
        json_data = response.json()
        print("Set Webhook:", response.status_code, json_data)
        
        # Retorna True si la respuesta de Telegram fue exitosa
        return json_data.get("ok", False)
    
    except Exception as e:
        print(f"❌ Error al establecer el webhook: {e}")
        return False


def delete_webhook():
    response = requests.get(f"{BASE_URL}/deleteWebhook")
    print("Delete Webhook:", response.status_code, response.json())

def get_webhook_info():
    response = requests.get(f"{BASE_URL}/getWebhookInfo")
    print("Webhook Info:", response.status_code, response.json())

if __name__ == "__main__":
    if len(sys.argv)>1:
        match sys.argv[1]:
            case "set":
                set_webhook()
            case "get":
                get_webhook_info()
            case "delete":
                delete_webhook()
            case _:
                print("what?")
    else:
        set_webhook()