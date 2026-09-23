import os
import requests
import sys
import threading
from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
WEBHOOK_GUARD_INTERVAL_SECONDS = max(
    15, int(os.getenv("WEBHOOK_GUARD_INTERVAL_SECONDS", "30"))
)

def set_webhook(webhook_url=None, certificate_path=None):
    try:
        if not webhook_url:
            webhook_url = input("WEBHOOK URL: ").strip()
        
        if "webhook" not in webhook_url:
            webhook_url += "/webhook"
        
        print(f"Usando URL: {webhook_url}")
        
        data = {
            "url": webhook_url,
            "allowed_updates": '["message","callback_query"]',
        }
        certificate_path = certificate_path or os.getenv(
            "WEBHOOK_CERT_FILE", "webhook_cert.pem"
        )
        if certificate_path and os.path.isfile(certificate_path):
            with open(certificate_path, "rb") as certificate:
                response = requests.post(
                    f"{BASE_URL}/setWebhook",
                    data=data,
                    files={"certificate": certificate},
                    timeout=10,
                )
        else:
            response = requests.post(
                f"{BASE_URL}/setWebhook", data=data, timeout=10
            )
        
        json_data = response.json()
        print("Set Webhook:", response.status_code, json_data)
        
        # Retorna True si la respuesta de Telegram fue exitosa
        return json_data.get("ok", False)
    
    except Exception as e:
        print(f"❌ Error al establecer el webhook: {e}")
        return False


def asegurar_webhook(webhook_url=None):
    """Restaura el webhook esperado si otra instalación lo reemplazó."""
    webhook_url = (webhook_url or os.getenv("WEBHOOK_URL") or "").strip()
    if not webhook_url or not BOT_TOKEN:
        return False
    if "webhook" not in webhook_url:
        webhook_url = webhook_url.rstrip("/") + "/webhook"
    try:
        response = requests.get(f"{BASE_URL}/getWebhookInfo", timeout=10)
        response.raise_for_status()
        current_url = response.json().get("result", {}).get("url", "")
    except Exception as exc:
        print(f"[WARN] No se pudo verificar el webhook de Telegram: {exc}")
        return False
    if current_url == webhook_url:
        return True
    print(
        "[WARN] Webhook de Telegram reemplazado externamente. "
        f"Restaurando {webhook_url} (anterior: {current_url or 'vacío'})."
    )
    return set_webhook(webhook_url)


class GuardianWebhook:
    def __init__(self, interval_seconds=WEBHOOK_GUARD_INTERVAL_SECONDS):
        self.interval_seconds = max(15, int(interval_seconds))
        self.activo = False
        self.hilo = None
        self._stop = threading.Event()

    def iniciar(self):
        if self.activo or not os.getenv("WEBHOOK_URL"):
            return
        self.activo = True
        self._stop.clear()
        self.hilo = threading.Thread(
            target=self._run, name="telegram-webhook-guard", daemon=True
        )
        self.hilo.start()
        print(f"Guardián de webhook iniciado (cada {self.interval_seconds}s)")

    def detener(self):
        self.activo = False
        self._stop.set()
        if self.hilo:
            self.hilo.join(timeout=2)

    def _run(self):
        while self.activo:
            asegurar_webhook()
            self._stop.wait(self.interval_seconds)


guardian_webhook = GuardianWebhook()


def iniciar_guardian_webhook():
    guardian_webhook.iniciar()


def detener_guardian_webhook():
    guardian_webhook.detener()


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
