import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

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
        return False

def guardar_recordatorio(datos):
    """Guarda un nuevo recordatorio en Supabase"""
    if not supabase:
        if not inicializar_supabase():
            return False
    
    try:
        # Preparar datos para inserción
        recordatorio = {
            "chat_id": str(datos["chat_id"]),
            "usuario": datos["usuario"],
            "nombre_tarea": datos["nombre_tarea"],
            "descripcion": datos["descripcion"],
            "fecha_hora": datos.get("fecha_hora"),
            "creado_en": datos["creado_en"],
            "notificado": False
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
        return False

def obtener_recordatorios_pendientes():
    """Obtiene todos los recordatorios pendientes de notificar"""
    if not supabase:
        if not inicializar_supabase():
            return []
    
    try:
        ahora = datetime.now().isoformat()
        
        # Obtener recordatorios que:
        # 1. No han sido notificados
        # 2. Tienen fecha_hora (no son None)
        # 3. La fecha_hora es menor o igual a la actual
        response = supabase.table("recordatorios").select("*").eq("notificado", False).not_.is_("fecha_hora", "null").lte("fecha_hora", ahora).execute()
        
        return response.data
    
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
        print(f"Error al marcar recordatorio como notificado: {e}")
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
        return []