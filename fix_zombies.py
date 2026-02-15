
import os
import sqlite3
from dotenv import load_dotenv
from supabase_db import obtener_todos_los_ids_recordatorios, inicializar_supabase
import logging

# Config logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FixZombies")

DB_NAME = "local_backup.db"

def fix_zombies():
    logger.info("🧟 Iniciando protocolo: Matar Zombis...")
    
    # 1. Obtener IDs Remotos (La Verdad)
    if not inicializar_supabase():
        logger.error("❌ No se pudo conectar a Supabase. Abortando misión.")
        return

    ids_remotos = obtener_todos_los_ids_recordatorios()
    if ids_remotos is None: # Error
        logger.error("❌ Error obteniendo IDs remotos.")
        return
    
    set_remotos = set(ids_remotos)
    logger.info(f"📋 IDs en Supabase: {len(set_remotos)}")

    # 2. Obtener IDs Locales que tienen enlace a Supabase
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, supabase_id FROM recordatorios WHERE supabase_id IS NOT NULL")
    locales = cursor.fetchall()
    
    zombis = []
    
    for row in locales:
        supa_id = row['supabase_id']
        if supa_id not in set_remotos:
            zombis.append(row['id'])
            
    logger.info(f"🧟 Zombis detectados: {len(zombis)}")
    
    if not zombis:
        logger.info("✅ No hay zombis. El sistema está limpio.")
        conn.close()
        return

    # 3. Eliminar Zombis
    logger.info(f"🔫 Eliminando {len(zombis)} zombis locales...")
    
    # Chunking para SQLite (limitación de variables en IN clause)
    CHUNK_SIZE = 900
    eliminados_total = 0
    
    for i in range(0, len(zombis), CHUNK_SIZE):
        batch = zombis[i:i+CHUNK_SIZE]
        placeholders = ','.join(['?'] * len(batch))
        try:
            cursor.execute(f"DELETE FROM recordatorios WHERE id IN ({placeholders})", batch)
            eliminados_total += cursor.rowcount
            conn.commit()
            logger.info(f"   💥 Lote eliminado ({len(batch)})")
        except Exception as e:
            logger.error(f"   ❌ Error eliminando lote: {e}")
            
    conn.close()
    logger.info(f"🎉 Misión cumplida. {eliminados_total} registros zombi eliminados.")

if __name__ == "__main__":
    fix_zombies()
