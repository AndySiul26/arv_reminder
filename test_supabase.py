from supabase_db import *

chat_id = os.environ.get("TELEGRAM_TEST_USER_ID")
# chat_id2 = os.environ.get("TELEGRAM_TEST_SECOND_USER_ID")
# datos = obtener_recordatorios_usuario(chat_id)

# print(datos)
# print("RECORDATORIOS PENDIENTES\n")
# recordatorios = obtener_recordatorios_pendientes()

# print(recordatorios)

cambiar_estado_aviso_detenido(chat_id=chat_id,estado= True)