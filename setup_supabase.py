"""
Este script crea las tablas necesarias en Supabase:
- recordatorios
- actualizaciones_info
- chats_avisados_actualizaciones
- usuarios_info
Se debe ejecutar una sola vez para configurar la base de datos.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

import socket

load_dotenv()

# Set global timeout for all socket operations (including Supabase HTTP requests)
# to prevent the script from hanging indefinitely during outages.
socket.setdefaulttimeout(5)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY_SERVICE_ROLE")

def crear_cliente():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: Faltan las credenciales de Supabase en el archivo .env")
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def crear_tabla_recordatorios(supabase: Client) -> bool:
    """
    Crea la tabla 'recordatorios' con todas las columnas necesarias,
    incluyendo 'es_formato_utc'. Si la tabla ya existe, añade
    'es_formato_utc' sólo si no está presente.
    """
    try:
        sql = """
        -- Tabla principal: recordatorios
        CREATE TABLE IF NOT EXISTS recordatorios (
            id SERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT NOT NULL,
            nombre_tarea TEXT NOT NULL,
            descripcion TEXT,
            fecha_hora TIMESTAMP,
            creado_en TIMESTAMP NOT NULL,
            notificado BOOLEAN DEFAULT FALSE,
            es_formato_utc BOOLEAN DEFAULT FALSE
        );

        -- Añadir columnas extra si no existen
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='aviso_constante'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN aviso_constante BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='aviso_detenido'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN aviso_detenido BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='repetir'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN repetir BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='intervalo_repeticion'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN intervalo_repeticion TEXT DEFAULT '';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='intervalos'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN intervalos INTEGER DEFAULT 0;
            END IF;

            -- Nueva columna es_formato_utc
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='es_formato_utc'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN es_formato_utc BOOLEAN DEFAULT FALSE;
            END IF;

            -- Nueva columna repeticion_creada
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='recordatorios' AND column_name='repeticion_creada'
            ) THEN
                ALTER TABLE recordatorios ADD COLUMN repeticion_creada BOOLEAN DEFAULT FALSE;
            END IF;
        END $$;

        -- Índices útiles
        CREATE INDEX IF NOT EXISTS idx_chat_id ON recordatorios (chat_id);
        CREATE INDEX IF NOT EXISTS idx_fecha_hora ON recordatorios (fecha_hora);
        CREATE INDEX IF NOT EXISTS idx_notificado ON recordatorios (notificado);
        """
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        print(response)
        print("🛠️ Tabla 'recordatorios' creada o actualizada correctamente.")
        return True

    except Exception as e:
        print(f"❌ Error al crear o actualizar la tabla 'recordatorios': {e}")
        return False

def crear_tablas_actualizaciones(supabase: Client):
    try:
        sql = """
        CREATE TABLE IF NOT EXISTS actualizaciones_info (
            id SERIAL PRIMARY KEY,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha_hora TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS chats_avisados_actualizaciones (
            chat_id TEXT PRIMARY KEY,
            id_ultima_actualizacion INTEGER,
            FOREIGN KEY (id_ultima_actualizacion) REFERENCES actualizaciones_info(id) ON DELETE SET NULL
        );

        ALTER TABLE chats_avisados_actualizaciones
        ALTER COLUMN id_ultima_actualizacion DROP NOT NULL;
        """
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        print("✅ Tablas de actualizaciones creadas correctamente.")
    except Exception as e:
        print(f"❌ Error al crear las tablas de actualizaciones: {e}")

def crear_tabla_chats_info(supabase: Client):
    """Crea la tabla chats_info que almacena información general de chats (usuarios o grupos)"""
    sql = """
    CREATE TABLE IF NOT EXISTS chats_info (
        chat_id TEXT PRIMARY KEY,
        nombre TEXT,
        tipo TEXT,
        zona_horaria TEXT DEFAULT NULL,
        creado_en TIMESTAMP NOT NULL
    );

    -- Añadir la columna creado_en si no existe
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'chats_info' AND column_name = 'creado_en'
        ) THEN
            ALTER TABLE chats_info ADD COLUMN creado_en TIMESTAMP NOT NULL DEFAULT now();
        END IF;
    END $$;


    """

    try:
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        print("✅ Tabla chats_info creada correctamente")
        print("✅ Response:", response)
        return True
    except Exception as e:
        print(f"❌ Error al crear la tabla chats_info: {e}")

def crear_tabla_modo_tester(supabase: Client):
    """
    Crea una tabla para almacenar el modo tester con un único registro booleano.
    """
    try:
        sql = """
        CREATE TABLE IF NOT EXISTS modo_tester (
            id SERIAL PRIMARY KEY,
            modo_tester BOOLEAN DEFAULT FALSE
        );

        -- Insertar un registro por defecto si la tabla está vacía
        INSERT INTO modo_tester (modo_tester) 
        SELECT FALSE 
        WHERE NOT EXISTS (SELECT 1 FROM modo_tester);
        """
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        print("✅ Tabla de modo tester creada correctamente.")
        return response
    except Exception as e:
        print(f"❌ Error al crear la tabla de modo tester: {e}")

def crear_tabla_chats_id_estados(supabase: Client):
    """
    Crea una tabla llamada 'chats_id_estados' para almacenar estados adicionales asociados a un chat_id.
    El campo 'chat_id' es clave primaria, por lo que no se permitirán valores repetidos.
    """
    try:
        sql = """
        CREATE TABLE IF NOT EXISTS chats_id_estados (
            chat_id TEXT PRIMARY KEY,  -- No se permiten chat_id duplicados
            estado_1 TEXT,
            estado_2 TEXT,
            estado_3 TEXT,
            estado_4 TEXT,
            estado_5 TEXT
        );
        """
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        print("✅ Tabla 'chats_id_estados' creada o verificada correctamente.")
        return response
    except Exception as e:
        print(f"❌ Error al crear la tabla 'chats_id_estados': {e}")

def crear_tabla_reportes(supabase: Client):
    """Crea la tabla de reportes de usuarios en Supabase."""
    try:
        sql = """
        CREATE TABLE IF NOT EXISTS reportes (
            id SERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT,
            descripcion TEXT NOT NULL,
            fecha_hora TIMESTAMP DEFAULT NOW(),
            estado TEXT DEFAULT 'pendiente'
        );
        """
        response = supabase.rpc("exec_sql", {"sql": sql}).execute()
        print("✅ Tabla 'reportes' creada correctamente.")
    except Exception as e:
        print(f"❌ Error al crear la tabla 'reportes': {e}")


def crear_tablas_criptoalertas(supabase: Client):
    """Crea las alertas de mercado y la lista de usuarios premium."""
    try:
        sql = """
        CREATE TABLE IF NOT EXISTS cripto_premium_users (
            chat_id TEXT PRIMARY KEY,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS cripto_alertas (
            id BIGSERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT,
            book TEXT NOT NULL,
            operador TEXT NOT NULL CHECK (operador IN ('gte', 'lte')),
            precio_objetivo NUMERIC(38, 18) NOT NULL CHECK (precio_objetivo > 0),
            estado TEXT NOT NULL DEFAULT 'activa'
                CHECK (estado IN ('activa', 'disparada')),
            una_vez BOOLEAN NOT NULL DEFAULT TRUE,
            precio_disparo NUMERIC(38, 18),
            disparada_en TIMESTAMPTZ,
            fuente TEXT NOT NULL DEFAULT 'bitso',
            creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_cripto_alertas_chat
            ON cripto_alertas (chat_id);
        CREATE INDEX IF NOT EXISTS idx_cripto_alertas_estado_book
            ON cripto_alertas (estado, book);
        """
        supabase.rpc("exec_sql", {"sql": sql}).execute()

        admin_chat_id = os.getenv("TELEGRAM_TEST_USER_ID")
        if admin_chat_id:
            supabase.table("cripto_premium_users").upsert(
                {"chat_id": str(admin_chat_id), "activo": True},
                on_conflict="chat_id",
            ).execute()

        print("✅ Tablas de criptoalertas creadas correctamente.")
        return True
    except Exception as e:
        print(f"❌ Error al crear tablas de criptoalertas: {e}")
        return False


if __name__ == "__main__":
    print("Configurando base de datos en Supabase...")
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
             print("⚠️  Advertencia: Definiendo cliente nulo por falta de credenciales.")
             cliente = None
        else:
             cliente = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        if cliente:
            crear_tabla_recordatorios(cliente)
            crear_tablas_actualizaciones(cliente)
            crear_tabla_chats_info(cliente)
            crear_tabla_modo_tester(cliente)
            crear_tabla_chats_id_estados(cliente)
            crear_tabla_reportes(cliente)
            crear_tablas_criptoalertas(cliente)
            print("✅ Configuración completada con éxito")
        else:
             print("⚠️ Salto de configuración por cliente nulo.")

    except Exception as e:
        print(f"⚠️  Advertencia: Falló la configuración inicial de Supabase (posible caída del servicio).")
        print(f"   Detalle: {e}")
        print("   -> Continuando ejecución para permitir arranque en Modo Mantenimiento.")
        # No hacemos exit(1) para que el contenedor NO se detenga.
