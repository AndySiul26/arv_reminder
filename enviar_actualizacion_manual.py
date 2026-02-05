import os
from dotenv import load_dotenv
# CORRECCION: El archivo se llama gestionar_actualizaciones.py
from gestionar_actualizaciones import insertar_actualizaciones_desde_archivo, registrar_chats_si_no_existen, obtener_chats_para_actualizacion, actualizar_id_ultima_actualizacion_para_chat, obtener_ultima_actualizacion
from services import enviar_telegram
import json

# Cargar variables de entorno
load_dotenv()

# Asegurar que el contexto se ejecute correctamente
if __name__ == "__main__":
    print("🚀 Iniciando proceso de notificación de actualización...")

    # 1. Insertar la actualización desde el archivo Actualizaciones.txt
    print("1️⃣  Insertando actualización en base de datos...")
    insertar_actualizaciones_desde_archivo()

    # 2. Registrar chats nuevos
    print("2️⃣  Sincronizando chats...")
    registrar_chats_si_no_existen()

    # 3. Obtener chats pendientes
    print("3️⃣  Obteniendo destinatarios...")
    chats = obtener_chats_para_actualizacion()

    if not chats:
        print("✅ No hay usuarios pendientes de notificación.")
    else:
        # 4. Obtener datos de la ultima actualización
        ultima = obtener_ultima_actualizacion()
        if ultima:
             titulo = ultima["titulo"]
             desc   = ultima["descripcion"]
             msg    = f"🆕 *Actualización*\n\n*{titulo}*\n\n{desc}"

             print(f"📨 Enviando notificaciones a {len(chats)} usuarios...")
             
             # 5. Enviar mensajes (Simulando lo que hace reminders.py pero manual)
             for chat_id in chats:
                try:
                    enviar_telegram(chat_id, tipo="texto", mensaje=msg, formato="Markdown")
                    actualizar_id_ultima_actualizacion_para_chat(chat_id, ultima["id"])
                    print(f"   -> Enviado a {chat_id}")
                except Exception as e:
                    print(f"   ❌ Error enviando a {chat_id}: {e}")

    print("🏁 Proceso finalizado.")
