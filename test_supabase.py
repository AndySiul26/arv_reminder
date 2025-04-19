from supabase_db import *

chat_id = os.environ.get("TELEGRAM_TEST_USER_ID")
datos = obtener_recordatorios_usuario(chat_id)

print(datos)