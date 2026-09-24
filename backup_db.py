"""
backup_db.py — Backup automático: Supabase → Docker Postgres
Se ejecuta como tarea programada cada 30 minutos dentro del bot.

Estrategia: TRUNCATE + INSERT (copia completa, simple y confiable).
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger("backup_db")

# Configuración del Postgres de backup
BACKUP_PG_HOST = os.getenv("BACKUP_PG_HOST", "postgres_backup")
BACKUP_PG_PORT = os.getenv("BACKUP_PG_PORT", "5432")
BACKUP_PG_DB = os.getenv("BACKUP_PG_DB", "arv_backup")
BACKUP_PG_USER = os.getenv("BACKUP_PG_USER", "arv_user")
BACKUP_PG_PASS = os.getenv("BACKUP_PG_PASS")

# Tablas a respaldar (en orden de prioridad)
TABLAS_A_RESPALDAR = [
    "recordatorios",
    "chats_info",
    "chats_id_estados",
    "actualizaciones_info",
    "chats_avisados_actualizaciones",
    "reportes",
    "cripto_premium_users",
    "cripto_alertas",
    "cripto_fuerza_alertas",
    "cripto_alertas_inteligentes",
    "cripto_mercados_usuario",
]


def _get_pg_connection():
    """Crea conexión al Postgres de backup."""
    if not BACKUP_PG_PASS:
        logger.error("BACKUP_PG_PASS no está configurada. Backup deshabilitado.")
        return None
    try:
        import psycopg2
        return psycopg2.connect(
            host=BACKUP_PG_HOST,
            port=BACKUP_PG_PORT,
            dbname=BACKUP_PG_DB,
            user=BACKUP_PG_USER,
            password=BACKUP_PG_PASS,
            connect_timeout=10
        )
    except ImportError:
        logger.error("psycopg2 no está instalado. Backup deshabilitado.")
        return None
    except Exception as e:
        logger.error(f"No se pudo conectar al Postgres de backup: {e}")
        return None


def _asegurar_esquema_cripto(conn):
    """Añade las tablas nuevas también en instalaciones de backup existentes."""
    cursor = conn.cursor()
    cursor.execute("""
        ALTER TABLE recordatorios
            ADD COLUMN IF NOT EXISTS ultimo_envio_en TIMESTAMPTZ;

        CREATE TABLE IF NOT EXISTS cripto_fuerza_alertas (
            id BIGINT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT,
            book TEXT NOT NULL,
            temporalidad TEXT NOT NULL,
            modo TEXT NOT NULL,
            umbral_pct NUMERIC(18, 8),
            cambio_min_pct NUMERIC(18, 8),
            cambio_max_pct NUMERIC(18, 8),
            cambio_referencia_pct NUMERIC(18, 8) NOT NULL,
            precio_referencia_inicial NUMERIC(38, 18) NOT NULL,
            aviso_constante BOOLEAN DEFAULT FALSE,
            aviso_detenido BOOLEAN DEFAULT FALSE,
            condicion_activa BOOLEAN DEFAULT FALSE,
            lado_activo TEXT,
            ultima_notificacion_en TIMESTAMPTZ,
            ultimo_cambio_pct NUMERIC(18, 8),
            ultima_fuerza_pct NUMERIC(18, 8),
            ultimo_precio NUMERIC(38, 18),
            ultima_consulta_en TIMESTAMPTZ,
            estado TEXT DEFAULT 'activa',
            fuente TEXT DEFAULT 'coinbase_exchange',
            creado_en TIMESTAMPTZ DEFAULT NOW(),
            actualizado_en TIMESTAMPTZ DEFAULT NOW()
        );

        ALTER TABLE cripto_fuerza_alertas
            ADD COLUMN IF NOT EXISTS cambio_min_pct NUMERIC(18, 8),
            ADD COLUMN IF NOT EXISTS cambio_max_pct NUMERIC(18, 8);

        CREATE TABLE IF NOT EXISTS cripto_alertas_inteligentes (
            id BIGINT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT,
            book TEXT NOT NULL,
            direccion TEXT NOT NULL,
            precio_objetivo NUMERIC(38, 18) NOT NULL,
            temporalidad TEXT NOT NULL,
            perfil TEXT NOT NULL,
            periodos_promedio INTEGER NOT NULL,
            perdida_promedio_pct NUMERIC(18, 8) NOT NULL,
            perdida_fuerza_pct NUMERIC(18, 8) NOT NULL,
            margen_precio_pct NUMERIC(18, 8) NOT NULL,
            actividad_ratio NUMERIC(18, 8) NOT NULL,
            confirmaciones_requeridas INTEGER DEFAULT 2,
            persistencia_requerida INTEGER DEFAULT 2,
            subtemporalidades JSONB DEFAULT '[]'::jsonb,
            reporte_calibracion JSONB DEFAULT '{}'::jsonb,
            estado TEXT DEFAULT 'esperando',
            condiciones_activas JSONB DEFAULT '{}'::jsonb,
            condiciones_silenciadas JSONB DEFAULT '{}'::jsonb,
            conteos_condiciones JSONB DEFAULT '{}'::jsonb,
            ultimas_notificaciones JSONB DEFAULT '{}'::jsonb,
            ultimo_precio NUMERIC(38, 18),
            ultima_fuerza_pct NUMERIC(18, 8),
            fuerza_promedio_pct NUMERIC(18, 8),
            fuerza_pico_pct NUMERIC(18, 8),
            ultima_consulta_en TIMESTAMPTZ,
            ultimo_mensaje_id BIGINT,
            fuente TEXT DEFAULT 'coinbase_exchange',
            creado_en TIMESTAMPTZ DEFAULT NOW(),
            actualizado_en TIMESTAMPTZ DEFAULT NOW()
        );
        ALTER TABLE cripto_alertas_inteligentes
            ADD COLUMN IF NOT EXISTS persistencia_requerida INTEGER DEFAULT 2,
            ADD COLUMN IF NOT EXISTS conteos_condiciones JSONB DEFAULT '{}'::jsonb;

        CREATE TABLE IF NOT EXISTS cripto_mercados_usuario (
            chat_id TEXT NOT NULL,
            book TEXT NOT NULL,
            fuentes_detectadas JSONB DEFAULT '[]'::jsonb,
            creado_en TIMESTAMPTZ DEFAULT NOW(),
            actualizado_en TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (chat_id, book)
        );

        CREATE TABLE IF NOT EXISTS cripto_premium_users (
            chat_id TEXT PRIMARY KEY,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            creado_en TIMESTAMPTZ DEFAULT NOW(),
              actualizado_en TIMESTAMPTZ DEFAULT NOW()
          );

        CREATE TABLE IF NOT EXISTS cripto_alertas (
            id BIGINT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            usuario TEXT,
            book TEXT NOT NULL,
            operador TEXT,
            precio_objetivo NUMERIC(38, 18),
            estado TEXT NOT NULL,
            una_vez BOOLEAN DEFAULT TRUE,
            precio_disparo NUMERIC(38, 18),
            disparada_en TIMESTAMPTZ,
            fuente TEXT,
            creado_en TIMESTAMPTZ DEFAULT NOW(),
            actualizado_en TIMESTAMPTZ DEFAULT NOW()
        );
        ALTER TABLE cripto_alertas
            ALTER COLUMN operador DROP NOT NULL,
            ALTER COLUMN precio_objetivo DROP NOT NULL;
        ALTER TABLE cripto_alertas
            ADD COLUMN IF NOT EXISTS precio_min NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS precio_max NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS min_armada BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS max_armada BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS aviso_constante BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS aviso_detenido BOOLEAN DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS rearme_porcentaje NUMERIC(8, 4),
              ADD COLUMN IF NOT EXISTS lado_disparado TEXT,
              ADD COLUMN IF NOT EXISTS ultima_notificacion_en TIMESTAMPTZ,
              ADD COLUMN IF NOT EXISTS fuente_actual TEXT,
              ADD COLUMN IF NOT EXISTS mercado_fuente TEXT,
              ADD COLUMN IF NOT EXISTS tipo_precio TEXT,
              ADD COLUMN IF NOT EXISTS fuente_candidata TEXT,
              ADD COLUMN IF NOT EXISTS lecturas_fuente_candidata INTEGER DEFAULT 0,
              ADD COLUMN IF NOT EXISTS fuente_cambio_en TIMESTAMPTZ;
    """)
    conn.commit()


def backup_tabla(supabase_client, conn, tabla):
    """Copia completa de una tabla de Supabase a Postgres local (TRUNCATE + INSERT)."""
    try:
        # 1. Leer todos los datos de Supabase
        response = supabase_client.table(tabla).select("*").execute()
        datos = response.data
        
        if not datos:
            logger.info(f"Backup [{tabla}]: 0 registros (tabla vacía en Supabase)")
            return 0

        cursor = conn.cursor()

        # 2. Obtener columnas que EXISTEN en la tabla de backup
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = %s AND table_schema = 'public'
        """, (tabla,))
        columnas_backup = {row[0] for row in cursor.fetchall()}

        # 3. Filtrar: solo columnas que existen en AMBOS lados
        columnas_supabase = set(datos[0].keys())
        columnas = sorted(columnas_supabase & columnas_backup)
        
        if not columnas:
            logger.warning(f"Backup [{tabla}]: Sin columnas en común entre Supabase y backup")
            return 0

        # 4. Truncate tabla de backup
        cursor.execute(f"TRUNCATE TABLE {tabla} CASCADE")

        # 5. Insertar registros con savepoint por fila
        placeholders = ", ".join(["%s"] * len(columnas))
        cols = ", ".join(f'"{c}"' for c in columnas)
        insert_sql = f'INSERT INTO {tabla} ({cols}) VALUES ({placeholders})'
        
        insertados = 0
        for fila in datos:
            valores = tuple(fila.get(c) for c in columnas)
            try:
                cursor.execute("SAVEPOINT fila_save")
                cursor.execute(insert_sql, valores)
                cursor.execute("RELEASE SAVEPOINT fila_save")
                insertados += 1
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT fila_save")
                logger.warning(f"Backup [{tabla}]: Error insertando fila {fila.get('id', '?')}: {e}")

        # 6. Actualizar metadatos de backup
        cursor.execute("""
            INSERT INTO _backup_metadata (tabla, registros_copiados, ultimo_backup)
            VALUES (%s, %s, %s)
            ON CONFLICT (tabla) DO UPDATE 
            SET registros_copiados = EXCLUDED.registros_copiados,
                ultimo_backup = EXCLUDED.ultimo_backup
        """, (tabla, insertados, datetime.utcnow()))

        conn.commit()
        return insertados

    except Exception as e:
        logger.error(f"Backup [{tabla}]: Error general: {e}")
        try:
            conn.rollback()
        except:
            pass
        return -1


def ejecutar_backup():
    """Ejecuta backup completo de todas las tablas. Llamado por schedule cada 30 min."""
    try:
        from supabase_db import supabase, inicializar_supabase
        
        if not supabase:
            if not inicializar_supabase():
                logger.error("Backup: No se pudo conectar a Supabase. Abortando.")
                return

        conn = _get_pg_connection()
        if not conn:
            logger.warning("Backup: Sin conexión a Postgres de backup. Saltando ciclo.")
            return

        _asegurar_esquema_cripto(conn)
        logger.info("=== Inicio de backup Supabase → Postgres ===")
        total = 0
        errores = 0

        for tabla in TABLAS_A_RESPALDAR:
            n = backup_tabla(supabase, conn, tabla)
            if n >= 0:
                total += n
                logger.info(f"Backup [{tabla}]: {n} registros copiados")
            else:
                errores += 1

        conn.close()
        logger.info(f"=== Backup completado: {total} registros, {errores} errores ===")

    except Exception as e:
        logger.error(f"Backup: Error general en ciclo de backup: {e}")
