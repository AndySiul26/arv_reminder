"""
Este script crea la tabla necesaria en Supabase para almacenar los recordatorios.
Se debe ejecutar una sola vez para configurar la base de datos.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY_SERVICE_ROLE")

def crear_tabla_recordatorios():
    """Crea la tabla de recordatorios en Supabase"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: Faltan las credenciales de Supabase en el archivo .env")
        return False

    try:
        # Inicializar cliente
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Definir SQL para crear la tabla (esto se ejecutará en la API de REST de Supabase)
        sql = """
        CREATE TABLE IF NOT EXISTS recordatorios (
            id SERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT NOT NULL,
            nombre_tarea TEXT NOT NULL,
            descripcion TEXT,
            fecha_hora TIMESTAMP,
            creado_en TIMESTAMP NOT NULL,
            notificado BOOLEAN DEFAULT FALSE
        );
        
        -- Índices para mejorar el rendimiento de las consultas
        CREATE INDEX IF NOT EXISTS idx_chat_id ON recordatorios (chat_id);
        CREATE INDEX IF NOT EXISTS idx_fecha_hora ON recordatorios (fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_notificado ON recordatorios (notificado);
        """
        
        # Ejecutar SQL usando la función rpc
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        
        print("Tabla de recordatorios creada correctamente")
        return True
        
    except Exception as e:
        print(f"Error al crear tabla en Supabase: {e}")
        return False

if __name__ == "__main__":
    print("Configurando base de datos en Supabase...")
    if crear_tabla_recordatorios():
        print("✅ Configuración completada con éxito")
    else:
        print("❌ Error en la configuración")