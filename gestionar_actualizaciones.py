import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY_SERVICE_ROLE")
supabase: Client = None

def inicializar_supabase():
    global supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Faltan las credenciales de Supabase.")
        return False
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        return True
    except Exception as e:
        print(f"Error al inicializar Supabase: {e}")
        return False

def insertar_actualizaciones_desde_archivo():
    if not inicializar_supabase():
        return

    archivo = "Actualizaciones.txt"
    if not os.path.exists(archivo):
        print("Archivo 'Actualizaciones.txt' no encontrado.")
        return

    with open(archivo, "r", encoding="utf-8") as f:
        contenido = f.read()

    bloques = contenido.strip().split("---")
    actualizaciones = []

    for bloque in bloques:
        lineas = bloque.strip().split("\n")
        if len(lineas) < 2:
            continue
        titulo = lineas[0].replace("TITULO:", "").strip()
        descripcion = "\n".join(lineas[1:]).replace("DESCRIPCION:", "").strip()
        actualizaciones.append({
            "titulo": titulo,
            "descripcion": descripcion,
            "fecha_hora": datetime.now().isoformat()
        })

    if actualizaciones:
        supabase.table("actualizaciones_info").insert(actualizaciones).execute()
        print(f"Se insertaron {len(actualizaciones)} actualizaciones correctamente.")
    else:
        print("No se encontraron actualizaciones válidas en el archivo.")

def registrar_chats_si_no_existen():
    if not inicializar_supabase():
        return

    try:
        response = supabase.table("recordatorios").select("chat_id").execute()
        chat_ids_recordatorios = set([r["chat_id"] for r in response.data])

        response_existentes = supabase.table("chats_avisados_actualizaciones").select("chat_id").execute()
        chat_ids_existentes = set([c["chat_id"] for c in response_existentes.data])

        nuevos_chat_ids = chat_ids_recordatorios - chat_ids_existentes

        if not nuevos_chat_ids:
            print("Todos los chat_id ya están registrados. No se insertó ninguno nuevo.")
            return

        nuevos_registros = [{"chat_id": cid, "id_ultima_actualizacion": None} for cid in nuevos_chat_ids]
        supabase.table("chats_avisados_actualizaciones").insert(nuevos_registros).execute()

        print(f"Se registraron {len(nuevos_registros)} nuevos chat_id(s) correctamente.")

    except Exception as e:
        print(f"Error al registrar nuevos chats: {e}")

def obtener_chats_para_actualizacion():
    if not inicializar_supabase():
        return

    try:
        ultima_actualizacion = supabase.table("actualizaciones_info").select("id").order("id", desc=True).limit(1).execute()
        if not ultima_actualizacion.data:
            print("No hay actualizaciones registradas aún.")
            return

        id_ultima = ultima_actualizacion.data[0]["id"]
        # Chats con id_ultima_actualizacion < id_ultima
        chats_viejos = supabase.table("chats_avisados_actualizaciones") \
            .select("chat_id") \
            .lt("id_ultima_actualizacion", id_ultima) \
            .execute().data

        # Chats con id_ultima_actualizacion NULL
        chats_null = supabase.table("chats_avisados_actualizaciones") \
            .select("chat_id") \
            .is_("id_ultima_actualizacion", None) \
            .execute().data

        # Unir ambos resultados
        chats_para_actualizar = chats_viejos + chats_null
        print(f"Chats pendientes de recibir la última actualización (ID {id_ultima}):")
        for cid in chats_para_actualizar:
            print(f"- {cid}")
        
        return [chat["chat_id"] for chat in chats_para_actualizar]

    except Exception as e:
        print(f"Error al obtener chats pendientes: {e}")

def eliminar_actualizacion_por_id():
    if not inicializar_supabase():
        return

    try:
        response = supabase.table("actualizaciones_info").select("*").order("id").execute()
        actualizaciones = response.data

        if not actualizaciones:
            print("No hay actualizaciones registradas.")
            return

        print("Actualizaciones disponibles:")
        for a in actualizaciones:
            print(f"{a['id']}: {a['titulo']} ({a['fecha_hora']})")

        id_eliminar = input("Ingrese el ID de la actualización que desea eliminar: ").strip()
        if not id_eliminar.isdigit():
            print("ID inválido.")
            return

        supabase.table("actualizaciones_info").delete().eq("id", int(id_eliminar)).execute()
        print("Actualización eliminada correctamente.")

        print("⚠️ Nota: los IDs no se renumerarán automáticamente.")

    except Exception as e:
        print(f"Error al eliminar actualización: {e}")

def actualizar_id_ultima_actualizacion_para_chat(chat_id: str, nuevo_id: int):
    """Actualiza el campo id_ultima_actualizacion para un chat dado"""
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        supabase.table("chats_avisados_actualizaciones") \
            .update({"id_ultima_actualizacion": nuevo_id}) \
            .eq("chat_id", chat_id) \
            .execute()
        print(f"Actualización de estado para {chat_id} -> id actualizado a {nuevo_id}")
    except Exception as e:
        print(f"❌ Error al actualizar id_ultima_actualizacion para {chat_id}: {e}")

def obtener_ultima_actualizacion():
    """Obtiene la última actualización registrada en la tabla actualizaciones_info"""
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        respuesta = supabase.table("actualizaciones_info") \
            .select("*") \
            .order("id", desc=True) \
            .limit(1) \
            .execute()

        data = respuesta.data
        if data and len(data) > 0:
            return data[0]  # Retorna el diccionario de la última actualización
        else:
            print("No hay actualizaciones registradas.")
            return None
    except Exception as e:
        print(f"❌ Error al obtener la última actualización: {e}")
        return None


def menu_principal():
    while True:
        print("\n--- Menú de Gestión de Actualizaciones ---")
        print("1. Insertar actualizaciones desde archivo")
        print("2. Registrar nuevos chats si no existen")
        print("3. Obtener chats pendientes de actualización")
        print("4. Eliminar una actualización por ID")
        print("5. Salir")

        opcion = input("Seleccione una opción: ").strip()

        if opcion == "1":
            insertar_actualizaciones_desde_archivo()
        elif opcion == "2":
            registrar_chats_si_no_existen()
        elif opcion == "3":
            obtener_chats_para_actualizacion()
        elif opcion == "4":
            eliminar_actualizacion_por_id()
        elif opcion == "5":
            print("Saliendo del script.")
            break
        else:
            print("Opción no válida. Intente nuevamente.")

if __name__ == "__main__":
    menu_principal()