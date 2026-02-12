import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
from zoneinfo import ZoneInfo
from utilidades import hora_utc_servidor_segun_zona_host
from services import enviar_telegram
import socket
import time

# Set global timeout for all socket operations (including Supabase HTTP requests)
# to prevent the app from hanging indefinitely during outages.
socket.setdefaulttimeout(5)

ADMIN_CHAT_ID = "6934945886"
_last_admin_notification_time = 0
NOTIFICATION_COOLDOWN = 300  # 5 minutes

load_dotenv()

# Cargar configuración de Supabase desde variables de entorno
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Inicializar cliente de Supabase
supabase: Client = None

def inicializar_supabase():
    """Inicializa la conexión con Supabase"""
    global supabase
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: No se encontraron las credenciales de Supabase en las variables de entorno")
        return False
    
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Conexión con Supabase establecida")
        return True
    except Exception as e:
        print(f"Error al conectar con Supabase: {e}")
        notificar_error_base_datos(e)
        return False

def notificar_error_base_datos(e, chat_id_usuario=None):
    """
    Notifica errores críticos de base de datos al administrador y al usuario afectado.
    Incluye rate limiting para evitar spam al admin.
    """
    global _last_admin_notification_time
    
    current_time = time.time()
    
    # 1. Notificar al Admin (con rate limit)
    if current_time - _last_admin_notification_time > NOTIFICATION_COOLDOWN:
        try:
            msg_admin = f"⚠️ *ALERTA DE BASE DE DATOS*\n\nError crítico en Supabase:\n`{str(e)}`\n\n_Notificación enviada automáticamente._"
            enviar_telegram(ADMIN_CHAT_ID, tipo="texto", mensaje=msg_admin, formato="Markdown")
            _last_admin_notification_time = current_time
            print(f"🚨 Notificación de error enviada al admin {ADMIN_CHAT_ID}")
        except Exception as err:
            print(f"Error al notificar al admin: {err}")

    # 2. Notificar al Usuario (si corresponde)
    if chat_id_usuario:
        try:
            msg_user = (
                "⚠️ *Servicio Intermitente*\n\n"
                "Lo siento, estamos teniendo problemas para conectar con nuestro servidor de datos (Supabase) en este momento.\n"
                "El equipo de desarrollo ya ha sido notificado automáticamente y estamos trabajando para solucionarlo.\n\n"
                "Por favor, intenta tu acción nuevamente en unos minutos."
            )
            enviar_telegram(chat_id_usuario, tipo="texto", mensaje=msg_user, formato="Markdown")
        except Exception as err:
            print(f"Error al notificar al usuario {chat_id_usuario}: {err}")

def guardar_recordatorio(datos):
    """Guarda un nuevo recordatorio en Supabase con todos los campos necesarios."""
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        # Preparar datos para inserción
        recordatorio = {
            "chat_id": str(datos["chat_id"]),
            "usuario": datos["usuario"],
            "nombre_tarea": datos["nombre_tarea"],
            "descripcion": datos.get("descripcion"),
            "fecha_hora": datos.get("fecha_hora"),
            "creado_en": datos["creado_en"],
            "es_formato_utc": datos.get("es_formato_utc", False),
            "notificado": False,
            "aviso_constante": datos.get("aviso_constante", False),
            "repetir": datos.get("repetir", False) in [True, "si", "yes", "y"],
            "intervalo_repeticion": datos.get("intervalo_repeticion", ""),
            "intervalos": int(datos.get("intervalos", 0)),
            "repeticion_creada": False
        }

        # Insertar en la tabla recordatorios
        response = supabase.table("recordatorios").insert(recordatorio).execute()

        if response.data:
            return True
        else:
            print("Error: No se recibieron datos de respuesta al insertar")
            return False

    except Exception as e:
        print(f"Error al guardar recordatorio en Supabase: {e}")
        notificar_error_base_datos(e, datos.get("chat_id"))
        return False


# def obtener_recordatorios_pendientes():
#     """Obtiene todos los recordatorios pendientes de notificar, incluyendo los que deben repetirse constantemente"""
#     if not supabase:
#         if not inicializar_supabase():
#             return []

#     try:
#         ahora = hora_utc_servidor_segun_zona_host().isoformat()

#         # Obtener recordatorios que:
#         # - No han sido notificados y deben ser enviados ahora o antes
#         # - O que deben enviarse constantemente (aviso_constante = true y aviso_detenido = false)
#         sql = f"""
#         SELECT * FROM recordatorios
#         WHERE 
#             (
#                 notificado = FALSE
#                 AND fecha_hora IS NOT NULL
#                 AND fecha_hora <= '{ahora}'
#             )
#             OR (
#                 aviso_constante = TRUE
#                 AND aviso_detenido = FALSE
#                 AND fecha_hora IS NOT NULL
#                 AND fecha_hora <= '{ahora}'
#             );
#         """

#         response = supabase.rpc("exec_sql", {"sql": sql}).execute()
#         if type(response.data ) != list:
#             return []
#         else:
#             return response.data

#     except Exception as e:
#         print(f"Error al obtener recordatorios pendientes: {e}")
#         return []
    
def obtener_recordatorios_por_ids(lista_ids):
    """Obtiene los recordatorios desde Supabase que coinciden con los IDs dados."""
    if not supabase:
        if not inicializar_supabase():
            return None

    if not lista_ids:
        print("La lista de IDs está vacía.")
        return []

    try:
        # Usar la cláusula `in_` para filtrar por múltiples IDs
        response = (
            supabase
            .table("recordatorios")
            .select("*")
            .in_("id", lista_ids)
            .execute()
        )

        if response.data:
            return response.data
        else:
            print("No se encontraron recordatorios con los IDs proporcionados.")
            return []

    except Exception as e:
        print(f"Error al obtener recordatorios por IDs desde Supabase: {e}")
        return None


def obtener_recordatorios_pendientes(pagina_tamano=1000):
    """Obtiene todos los recordatorios pendientes de notificar, incluyendo los que deben repetirse constantemente, con paginación."""
    if not supabase:
        if not inicializar_supabase():
            return []

    try:
        ahora = hora_utc_servidor_segun_zona_host().isoformat()
        resultados = {}

        def fetch_con_paginacion(filtros):
            pagina = 0
            while True:
                desde = pagina * pagina_tamano
                hasta = desde + pagina_tamano - 1
                query = supabase \
                    .from_("recordatorios") \
                    .select("*") \
                    .range(desde, hasta)

                # Aplicar filtros
                for columna, operador, valor in filtros:
                    if operador == "eq":
                        query = query.eq(columna, valor)
                    elif operador == "lte":
                        query = query.lte(columna, valor)

                response = query.execute()

                if not response.data:
                    break  # ya no hay más
                for r in response.data:
                    resultados[r["id"]] = r
                pagina += 1

        # Grupo 1: no notificado y fecha vencida
        fetch_con_paginacion([
            ("notificado", "eq", False),
            ("fecha_hora", "lte", ahora)
        ])

        # Grupo 2: aviso constante, no detenido, y fecha vencida
        fetch_con_paginacion([
            ("aviso_constante", "eq", True),
            ("aviso_detenido", "eq", False),
            ("fecha_hora", "lte", ahora)
        ])

        return list(resultados.values())

    except Exception as e:
        print(f"Error al obtener recordatorios pendientes: {e}")
        return []


def marcar_como_notificado(recordatorio_id):
    """Marca un recordatorio como notificado"""
    if not supabase:
        if not inicializar_supabase():
            return False
    
    try:
        response = supabase.table("recordatorios").update({"notificado": True}).eq("id", recordatorio_id).execute()
        
        if response.data:
            return True
        else:
            print(f"Error: No se pudo marcar como notificado el recordatorio {recordatorio_id}")
            return False
    
    except Exception as e:
        print(f"Error al marcar recordatorio como repeticion_creada: {e}")
        return False
    
def marcar_como_repetido(recordatorio_id):
    """Marca un recordatorio como repetido"""
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        response = supabase.table("recordatorios").update({"repeticion_creada": True}).eq("id", recordatorio_id).execute()
        
        if response.data:
            return True
        else:
            print(f"Error: No se pudo marcar como repeticion_creada en el recordatorio {recordatorio_id}")
            return False

    except Exception as e:
        print(f"Error al marcar recordatorio como repeticion_creada en el recordatorio {recordatorio_id}")
        return False
    
def cambiar_estado_aviso_detenido(chat_id, estado):
    """
    Cambia el estado de 'aviso_detenido' para todos los recordatorios de un chat_id.
    
    Parámetros:
    - chat_id: El identificador del usuario/chat.
    - estado: True o False (boolean) para activar o desactivar el aviso detenido.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        response = supabase.table("recordatorios") \
            .update({"aviso_detenido": estado}) \
            .eq("chat_id", str(chat_id)) \
            .eq("notificado", True) \
            .eq("aviso_constante", True) \
            .execute()
        
        if response.data:
            print(f"Estado 'aviso_detenido' actualizado correctamente a {estado} para el chat_id {chat_id}.")
            return True
        else:
            print(f"No se encontraron recordatorios para actualizar el estado 'aviso_detenido' de {chat_id}.")
            return False

    except Exception as e:
        print(f"Error al actualizar aviso_detenido para {chat_id}: {e}")
        return False


def obtener_recordatorios_usuario(chat_id):
    """Obtiene todos los recordatorios de un usuario específico"""
    if not supabase:
        if not inicializar_supabase():
            return []
    
    try:
        response = supabase.table("recordatorios").select("*").eq("chat_id", str(chat_id)).order("fecha_hora", desc=False).execute()
        
        return response.data
    
    except Exception as e:
        print(f"Error al obtener recordatorios del usuario: {e}")
        notificar_error_base_datos(e, chat_id)
        return []
    
def eliminar_recordatorios_finalizados():
    """
    Elimina los recordatorios que ya han sido notificados y no deben repetirse más.
    Condiciones:
    - notificado = true AND aviso_constante = false
    - OR aviso_constante = true AND aviso_detenido = true
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: Faltan las credenciales de Supabase en el archivo .env")
        return False

    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

        sql = """
        DELETE FROM recordatorios
        WHERE (notificado = TRUE AND aviso_constante = FALSE)
           OR (aviso_constante = TRUE AND aviso_detenido = TRUE);
        """

        response = supabase.rpc("exec_sql", {"sql": sql}).execute()

        print("Recordatorios eliminados exitosamente según los criterios establecidos.")
        return True

    except Exception as e:
        print(f"Error al eliminar recordatorios: {e}")
        return False

def eliminar_recordatorio_por_id(recordatorio_id):
    """Elimina un recordatorio específico por su ID"""
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        response = supabase.table("recordatorios").delete().eq("id", recordatorio_id).execute()
        
        if response.data:  # Verifica si algo fue eliminado
            print(f"✅ Recordatorio con ID {recordatorio_id} eliminado correctamente.")
            return True
        else:
            print(f"⚠️ No se encontró ningún recordatorio con ID {recordatorio_id}.")
            return False

    except Exception as e:
        print(f"❌ Error al eliminar recordatorio con ID {recordatorio_id}: {e}")
        return False


def upsert_chat_info(chat_id: str, nombre: str, tipo: str, zona_horaria: str = None):
    """Inserta un nuevo chat o actualiza zona_horaria si ya existe"""
    if not supabase:
        if not inicializar_supabase():
            return []
        
    creado_en = datetime.now().isoformat()

    try:
        # Buscar si ya existe
        consulta = supabase.table("chats_info").select("*").eq("chat_id", chat_id).execute()
        
        if not consulta.data:
            # No existe: insertar nuevo registro
            data = {
                "chat_id": chat_id,
                "nombre": nombre,
                "tipo": tipo,
                "zona_horaria": zona_horaria,
                "creado_en": creado_en
                
            }
            response = supabase.table("chats_info").insert(data).execute()
            print("✅ Nuevo chat registrado:", response)
        else:
            # Ya existe: actualizar zona_horaria si es necesario
            if zona_horaria:
                response = supabase.table("chats_info").update({"zona_horaria": zona_horaria}).eq("chat_id", chat_id).execute()
                print("🔄 Zona horaria actualizada:", response)
            else:
                print("⚠️ Ya existe el chat_id y no se proporcionó una nueva zona horaria.")
        
        return True

    except Exception as e:
        print(f"❌ Error en upsert_chat_info: {e}")
        notificar_error_base_datos(e, chat_id)
        return False

def guardar_zona_horaria_chat(chat_id: str, zona_horaria: str, nombre_chat:str, tipo:str) -> bool:
    """
    Inserta o actualiza la zona horaria de un chat en la tabla chats_info.
    - Si el chat no existe, lo crea con el campo zona_horaria.
    - Si ya existe, actualiza solo zona_horaria.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        # Intentar actualizar primero
        res = supabase.table("chats_info") \
            .update({"zona_horaria": zona_horaria}) \
            .eq("chat_id", chat_id) \
            .execute()

        if res.data:
            print(f"🔄 Zona horaria de {chat_id} actualizada a {zona_horaria}")
            return True

        # Si no había fila, insertamos
        now = datetime.now().isoformat()
        res = supabase.table("chats_info").insert({
            "chat_id":      chat_id,
            "nombre":       nombre_chat,
            "tipo":         tipo,
            "zona_horaria": zona_horaria,
            "creado_en":    now
        }).execute()
        print(f"✅ Chat {chat_id} creado con zona horaria {zona_horaria}")
        return True

    except Exception as e:
        print(f"[Error] guardar_zona_horaria_chat: {e}")
        return False


def obtener_info_chat(chat_id):
    """
    Consulta los datos del chat desde la tabla chats_info usando el chat_id.
    Retorna un diccionario con la información si existe, o None si no se encuentra.
    """

    if not supabase:
        if not inicializar_supabase():
            return []
    try:
        response = supabase.table("chats_info").select("*").eq("chat_id", chat_id).single().execute()
        if response.data:
            return response.data
        else:
            return None
    except Exception as e:
        print(f"[Error] obtener_info_chat: {e}")
        return None
    
def obtener_chat_ids_de_recordatorios():
    """Devuelve un conjunto de chat_id únicos desde la tabla 'recordatorios'."""
    try:
        response = supabase.table("recordatorios").select("chat_id").execute()
        return set([r["chat_id"] for r in response.data])
    except Exception as e:
        print(f"[Error] al obtener chat_id de recordatorios: {e}")
        return set()

def obtener_chat_ids_existentes_en_tabla(tabla):
    """Devuelve un conjunto de chat_id existentes en una tabla dada."""
    try:
        response = supabase.table(tabla).select("chat_id").execute()
        return set([c["chat_id"] for c in response.data])
    except Exception as e:
        print(f"[Error] al obtener chat_id de {tabla}: {e}")
        return set()

def obtener_todos_chats_info():
    """
    Devuelve todos los registros de la tabla 'chats_info'.
    Retorna una lista de diccionarios con las columnas:
    - chat_id
    - nombre
    - tipo
    - zona_horaria
    - creado_en
    """
    if not supabase:
        if not inicializar_supabase():
            return []

    try:
        response = supabase.table("chats_info").select("*").execute()
        return response.data or []
    except Exception as e:
        print(f"[Error] obtener_todos_chats_info: {e}")
        return []

def insertar_nuevos_chat_ids_en_avisos(nuevos_chat_ids):
    """Inserta los nuevos chat_id en la tabla 'chats_avisados_actualizaciones'."""
    try:
        nuevos_registros = [{"chat_id": cid, "id_ultima_actualizacion": None} for cid in nuevos_chat_ids]
        supabase.table("chats_avisados_actualizaciones").insert(nuevos_registros).execute()
        print(f"✅ Registrados en 'chats_avisados_actualizaciones': {len(nuevos_registros)}")
    except Exception as e:
        print(f"[Error] al insertar en 'chats_avisados_actualizaciones': {e}")

def insertar_nuevos_chat_ids_en_info(nuevos_chat_ids):
    """Registra nuevos chat_id en la tabla 'chats_info' si aún no existen."""
    existentes = obtener_chat_ids_existentes_en_tabla("chats_info")
    faltantes = nuevos_chat_ids - existentes

    if not faltantes:
        print("ℹ️ Todos los chat_id ya existen en 'chats_info'.")
        return

    ahora = hora_utc_servidor_segun_zona_host().isoformat()
    registros_info = [
        {
            "chat_id": cid,
            "nombre": "Desconocido",
            "tipo": "private",
            "zona_horaria": None,
            "creado_en": ahora
        } for cid in faltantes
    ]

    try:
        supabase.table("chats_info").insert(registros_info).execute()
        print(f"✅ Registrados en 'chats_info': {len(registros_info)}")
    except Exception as e:
        print(f"[Error] al insertar en 'chats_info': {e}")

def registrar_chats_si_no_existen():
    """Función principal que sincroniza chat_ids en ambas tablas si no existen."""
    if not inicializar_supabase():
        return

    chat_ids_recordatorios = obtener_chat_ids_de_recordatorios()
    chat_ids_avisados = obtener_chat_ids_existentes_en_tabla("chats_avisados_actualizaciones")
    chat_ids_info = obtener_chat_ids_existentes_en_tabla("chats_info")

    nuevos_chat_ids_avisados = chat_ids_recordatorios - chat_ids_avisados
    nuevos_chat_ids_info = chat_ids_recordatorios - chat_ids_info

    if not nuevos_chat_ids_avisados and not nuevos_chat_ids_info:
        print("✅ Todos los chat_id ya están registrados.")
        return
    
    if nuevos_chat_ids_avisados:
        insertar_nuevos_chat_ids_en_avisos(nuevos_chat_ids_avisados)
    
    if nuevos_chat_ids_info:
        insertar_nuevos_chat_ids_en_info(nuevos_chat_ids_info)

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

def obtener_chats_sin_zona_horaria():
    """
    Devuelve una lista de registros de 'chats_info' cuyo campo 'zona_horaria'
    sea None o cadena vacía, es decir, los chats a los que aún no se les ha
    configurado zona horaria.
    """
    # Primero traemos todos los chats
    chats = obtener_todos_chats_info()
    # Filtramos los que no tienen zona_horaria asignada
    sin_zona = [
        chat for chat in chats
        if not chat.get("zona_horaria")  # None o ""
    ]
    return sin_zona

def actualizar_recordatorios_por_chat(chat_id: str) -> bool:
    """
    Para todos los recordatorios de un chat con fecha_hora definida y es_formato_utc = false,
    convierte esa fecha de la zona local (según chats_info.zona_horaria) a UTC,
    actualiza el registro y pone es_formato_utc = true.
    Retorna True si al menos uno fue actualizado, False en caso contrario.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    # 1) Obtener zona_horaria
    info = obtener_info_chat(chat_id)
    zona = info.get("zona_horaria") if info else None
    if not zona:
        print(f"⚠️ No hay zona_horaria definida para chat_id {chat_id}")
        return False

    try:
        # 2) Traer recordatorios para este chat que aún no estén en UTC
        resp = supabase.table("recordatorios") \
            .select("id", "fecha_hora", "es_formato_utc") \
            .eq("chat_id", chat_id) \
            .not_("fecha_hora", "is", None) \
            .eq("es_formato_utc", False) \
            .execute()
        records = resp.data or []

        if not records:
            print("ℹ️ No hay recordatorios pendientes de conversión a UTC.")
            return False

        updated = 0
        for rec in records:
            # 3) Parsear y convertir a UTC
            local_dt = datetime.fromisoformat(rec["fecha_hora"])
            try:
                tz = ZoneInfo(zona)
            except Exception:
                tz = ZoneInfo("UTC")
            dt_local = local_dt.replace(tzinfo=tz)
            dt_utc = dt_local.astimezone(ZoneInfo("UTC"))
            nueva_fecha = dt_utc.isoformat()

            # 4) Actualizar fecha_hora y marcar como UTC
            supabase.table("recordatorios") \
                   .update({
                       "fecha_hora": nueva_fecha,
                       "es_formato_utc": True
                   }) \
                   .eq("id", rec["id"]) \
                   .execute()
            updated += 1

        print(f"✅ Se actualizaron {updated} recordatorio(s) de chat {chat_id} a UTC.")
        return True

    except Exception as e:
        print(f"❌ Error al actualizar recordatorios para chat {chat_id}: {e}")
        return False
    
def actualizar_campos_recordatorio(recordatorio_id: int, campos: dict) -> bool:
    """
    Actualiza los campos de un recordatorio dado su ID.
    
    Args:
      recordatorio_id: ID del recordatorio en la tabla.
      campos: diccionario {columna: valor, ...} a actualizar.
    
    Returns:
      True si se actualizó al menos un registro, False en caso contrario.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        response = supabase.table("recordatorios") \
                           .update(campos) \
                           .eq("id", recordatorio_id) \
                           .execute()
        if response.data:
            print(f"✅ Recordatorio {recordatorio_id} actualizado: {campos}")
            return True
        else:
            print(f"ℹ️ No se encontró recordatorio con ID {recordatorio_id}")
            return False

    except Exception as e:
        print(f"❌ Error al actualizar recordatorio {recordatorio_id}: {e}")
        return False
    
def leer_modo_tester()->bool:
    """
    Lee el valor actual del modo tester.
    
    Retorna:
    - El valor booleano del modo tester si existe, de lo contrario None.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        datos = supabase.from_("modo_tester").select("modo_tester").execute()
        if datos.data:            
            return datos.data[0]['modo_tester']
        else:
            return False    
        
    except Exception as e:
        print(f"❌ Error al leer el modo tester: {e}")
        return False
    
def actualizar_modo_tester(nuevo_valor: bool):
    """
    Actualiza el valor del modo tester.
    
    Parámetros:
    - nuevo_valor (bool): El nuevo valor para el modo tester.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        # Actualizamos el valor asumiendo que solo hay un registro
        supabase.from_("modo_tester").update({"modo_tester": nuevo_valor}).eq("id", 1).execute()
        print(f"✅ Modo tester actualizado correctamente a {nuevo_valor}")
    except Exception as e:
        print(f"❌ Error al actualizar el modo tester: {e}")

def leer_estados_chat_id(chat_id):
    """
    Lee todos los estados (estado_1 a estado_5) asociados a un chat_id desde la tabla 'chats_id_estados'.
    """
    if not supabase:
        if not inicializar_supabase():
            return None

    try:
        response = supabase.table("chats_id_estados") \
            .select("*") \
            .eq("chat_id", str(chat_id)) \
            .execute()

        if response.data:
            return response.data[0]  # Devuelve el primer (y único) registro
        else:
            print(f"No se encontraron estados para el chat_id {chat_id}.")
            return None

    except Exception as e:
        print(f"Error al leer estados para {chat_id}: {e}")
        return None

def leer_estado_chat_id(chat_id, numero_estado):
    """
    Lee el estado_n (1 a 5) de la tabla chats_id_estados para un chat_id dado.

    Parámetros:
    - chat_id: ID del chat del usuario.
    - numero_estado: número entre 1 y 5 para seleccionar el campo estado_n.

    Retorna:
    - El valor del estado si existe, o None si no hay registro.
    """
    if not supabase:
        if not inicializar_supabase():
            return None

    try:
        campo_estado = f"estado_{numero_estado}"
        response = supabase.table("chats_id_estados") \
            .select(campo_estado) \
            .eq("chat_id", str(chat_id)) \
            .execute()

        if response.data and response.data[0].get(campo_estado) is not None:
            return response.data[0][campo_estado]
        else:
            return None

    except Exception as e:
        print(f"Error al leer {campo_estado} para {chat_id}: {e}")
        return None


def actualizar_estado_chat_id(chat_id, numero_estado, nuevo_valor):
    """
    Actualiza el estado_n (1 a 5) del chat_id en la tabla chats_id_estados.

    Si no existe el registro, lo inserta.

    Parámetros:
    - chat_id: ID del chat del usuario.
    - numero_estado: número entre 1 y 5 indicando qué estado modificar.
    - nuevo_valor: nuevo valor para asignar al estado.
    """
    if not supabase:
        if not inicializar_supabase():
            return False

    try:
        campo_estado = f"estado_{numero_estado}"
        datos_actualizados = {
            "chat_id": str(chat_id),
            campo_estado: str(nuevo_valor)
        }

        response = supabase.table("chats_id_estados") \
            .upsert(datos_actualizados, on_conflict="chat_id") \
            .execute()

        if response.data:
            print(f"✅ {campo_estado} actualizado correctamente para {chat_id}.")
            return True
        else:
            print(f"⚠️ No se actualizó {campo_estado} para {chat_id}.")
            return False

    except Exception as e:
        print(f"❌ Error al actualizar {campo_estado} para {chat_id}: {e}")
        return False



if __name__ == "__main__":
    opciones = {
        "1": lambda: guardar_recordatorio({
            "chat_id": input("chat_id: "),
            "usuario": input("usuario: "),
            "nombre_tarea": input("nombre_tarea: "),
            "descripcion": input("descripcion: "),
            "fecha_hora": input("fecha_hora (YYYY-MM-DD HH:MM): "),
            "creado_en": datetime.now().isoformat()
        }),
        "2": lambda: print(obtener_recordatorios_pendientes()),
        "3": lambda: print(marcar_como_notificado(input("ID del recordatorio: "))),
        "4": lambda: print(cambiar_estado_aviso_detenido(input("chat_id: "), input("estado (True/False): ") == "True")),
        "5": lambda: print(obtener_recordatorios_usuario(input("chat_id: "))),
        "6": lambda: eliminar_recordatorios_finalizados(),
        "7": lambda: print(upsert_chat_info(
            chat_id=input("chat_id: "),
            nombre=input("nombre: "),
            tipo=input("tipo: "),
            zona_horaria=input("zona_horaria (opcional): ") or None
        )),
        "8": lambda: print(obtener_info_chat(input("chat_id: "))),
        "9": lambda: inicializar_supabase(),
        "10": lambda: registrar_chats_si_no_existen(),
        "11": lambda: obtener_chats_para_actualizacion(),
        "12": lambda: actualizar_recordatorios_por_chat(input("chat_id: ")),
        "13": lambda: print("Modo Tester :",  "SI" if leer_modo_tester() else "NO"),
        "14": lambda: actualizar_modo_tester(input("¿Habilitar modo tester?(si=s/no=cualquier otro caracter): ") == "s"),
        "15": lambda: print(marcar_como_repetido(input("ID del recordatorio: ")))
    }

    while True:
        print("\n--- MENÚ DE PRUEBAS Supabase ---")
        print("1. Guardar nuevo recordatorio")
        print("2. Obtener recordatorios pendientes")
        print("3. Marcar recordatorio como notificado")
        print("4. Cambiar estado 'aviso_detenido'")
        print("5. Obtener recordatorios de un usuario")
        print("6. Eliminar recordatorios finalizados")
        print("7. Insertar/Actualizar chat en chats_info")
        print("8. Obtener información de chat")
        print("9. Probar conexión Supabase")
        print("10. Registrar chats si no existen en avisos y chats_info")
        print("11. Obtener los chats_id que necesitan conocer nuevas actualizaciones")
        print("12. Actualizar recordatorios por chat")
        print("13. Leer estado Modo Tester")
        print("14. Actualizar Modo Tester")
        print("15. Marcar como repeticion_creada")
        print("0. Salir")

        opcion = input("Selecciona una opción: ")
        if opcion == "0":
            break
        accion = opciones.get(opcion)
        if accion:
            accion()
        else:
            print("Opción no válida.")