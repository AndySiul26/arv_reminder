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
BACKUP_PG_PASS = os.getenv("BACKUP_PG_PASS", "arv_secure_pass")

# Tablas a respaldar (en orden de prioridad)
TABLAS_A_RESPALDAR = [
    "recordatorios",
    "chats_info",
    "chats_id_estados",
    "actualizaciones_info",
    "chats_avisados_actualizaciones",
    "reportes",
]


def _get_pg_connection():
    """Crea conexión al Postgres de backup."""
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

        # 2. Truncate tabla de backup
        cursor.execute(f"TRUNCATE TABLE {tabla} CASCADE")

        # 3. Insertar todos los registros
        columnas = list(datos[0].keys())
        placeholders = ", ".join(["%s"] * len(columnas))
        cols = ", ".join(f'"{c}"' for c in columnas)
        insert_sql = f'INSERT INTO {tabla} ({cols}) VALUES ({placeholders})'

        for fila in datos:
            valores = tuple(fila.get(c) for c in columnas)
            try:
                cursor.execute(insert_sql, valores)
            except Exception as e:
                logger.warning(f"Backup [{tabla}]: Error insertando fila {fila.get('id', '?')}: {e}")
                continue

        # 4. Actualizar metadatos de backup
        cursor.execute("""
            INSERT INTO _backup_metadata (tabla, registros_copiados, ultimo_backup)
            VALUES (%s, %s, %s)
            ON CONFLICT (tabla) DO UPDATE 
            SET registros_copiados = EXCLUDED.registros_copiados,
                ultimo_backup = EXCLUDED.ultimo_backup
        """, (tabla, len(datos), datetime.utcnow()))

        conn.commit()
        return len(datos)

    except Exception as e:
        logger.error(f"Backup [{tabla}]: Error general: {e}")
        conn.rollback()
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
