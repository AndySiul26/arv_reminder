import os, sys
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def set_webhook():
    WEBHOOK_URL = input("WEBHOOK URL:").strip()
    if not "webhook" in WEBHOOK_URL: WEBHOOK_URL += "/webhook"
    print(WEBHOOK_URL)
    response = requests.get(f"{BASE_URL}/setWebhook", params={"url": WEBHOOK_URL})
    print("Set Webhook:", response.status_code, response.json())

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