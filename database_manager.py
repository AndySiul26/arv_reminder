import sqlite3
import json
import logging
from datetime import datetime
import os
from contextlib import contextmanager
from typing import Dict, Any, List, Optional
import time

# Intentamos importar supabase_db, pero manejamos si falla
try:
    import supabase_db
except ImportError:
    supabase_db = None

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DatabaseManager")

DB_NAME = "local_backup.db"

class DatabaseManager:
    def __init__(self):
        self.local_db_path = DB_NAME
        self.inicializar_db_local()
        # Estado de conexión con Supabase (se actualiza dinámicamente)
        self.supabase_online = False 

    @contextmanager
    def get_local_connection(self):
        conn = sqlite3.connect(self.local_db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def inicializar_db_local(self):
        """Crea las tablas locales en SQLite si no existen."""
        with self.get_local_connection() as conn:
            cursor = conn.cursor()
            
            # Tabla Recordatorios (Espejo de Supabase + columnas de sinc)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS recordatorios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                usuario TEXT,
                nombre_tarea TEXT NOT NULL,
                descripcion TEXT,
                fecha_hora TEXT,
                creado_en TEXT,
                notificado INTEGER DEFAULT 0, -- BOOLEAN
                es_formato_utc INTEGER DEFAULT 0,
                aviso_constante INTEGER DEFAULT 0,
                aviso_detenido INTEGER DEFAULT 0,
                repetir INTEGER DEFAULT 0,
                intervalo_repeticion TEXT,
                intervalos INTEGER DEFAULT 0,
                repeticion_creada INTEGER DEFAULT 0,
                
                -- Columnas de Sincronización
                supabase_id INTEGER, -- ID real en Supabase
                sync_status TEXT DEFAULT 'pending', -- 'synced', 'pending', 'failed'
                last_updated TEXT
            )
            ''')
            
            # Tabla Chats Info
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats_info (
                chat_id TEXT PRIMARY KEY,
                nombre TEXT,
                tipo TEXT,
                zona_horaria TEXT,
                creado_en TEXT,
                sync_status TEXT DEFAULT 'pending',
                last_updated TEXT
            )
            ''')
            
            conn.commit()
            logger.info("Base de datos local (SQLite) inicializada.")

    def verificar_conexion_supabase(self) -> bool:
        """Verifica si Supabase está disponible y actualiza el estado interno."""
        if supabase_db and supabase_db.inicializar_supabase():
            self.supabase_online = True
            return True
        self.supabase_online = False
        return False

    def guardar_recordatorio(self, datos: Dict[str, Any]) -> bool:
        """
        Guarda un recordatorio.
        1. Guarda en SQLite (siempre).
        2. Intenta guardar en Supabase.
        3. Actualiza estado de sincronización.
        """
        try:
            # Guardar localmente primero
            local_id = self._guardar_recordatorio_local(datos, sync_status='pending')
            
            exito_remoto = False
            supabase_id = None
            
            # Intentar remoto si hay conexión
            if self.verificar_conexion_supabase():
                try:
                    # supabase_db.guardar_recordatorio devuelve True/False
                    if supabase_db.guardar_recordatorio(datos):
                        exito_remoto = True
                except Exception as e:
                    logger.error(f"Fallo al guardar en Supabase: {e}")
            
            # Actualizar estado local
            if exito_remoto:
                self._actualizar_estado_sync_recordatorio(local_id, 'synced', supabase_id)
                logger.info(f"Recordatorio {local_id} guardado y sincronizado.")
            else:
                logger.warning(f"Recordatorio {local_id} guardado SOLO LOCALMENTE. Se sincronizará después.")
                
            return True
        except Exception as e:
            logger.error(f"Error CRÍTICO al guardar recordatorio localmente: {e}")
            return False

    def obtener_recordatorios_pendientes(self) -> List[Dict]:
        """
        Obtiene recordatorios pendientes de notificar desde LOCAL.
        La fuente de verdad para 'qué notificar' ahora es SQLite para velocidad y offline.
        """
        with self.get_local_connection() as conn:
            cursor = conn.cursor()
            # Seleccionar recordatorios no notificados y cuya fecha sea <= ahora
            # Nota: Almacenamos fechas como ISO string en UTC o local segun el flag.
            # Para simplificar, traemos los que no están notificados y el filtro de fecha lo hace el scheduler
            # O mejor, filtramos por 'notificado = 0'.
            cursor.execute("SELECT * FROM recordatorios WHERE notificado = 0")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def marcar_como_notificado(self, recordatorio_id: int):
        """Marca como notificado en local y encolar sync a remoto."""
        with self.get_local_connection() as conn:
            conn.execute("UPDATE recordatorios SET notificado = 1, sync_status = 'pending_update', last_updated = ? WHERE id = ?", 
                         (datetime.utcnow().isoformat(), recordatorio_id))
            conn.commit()
            
        # Intentar sync inmediata si hay red
        if self.verificar_conexion_supabase():
            try:
                # Recuperar el ID de supabase (si existe) para actualizar allá
                # Por complejidad, esto requerirá que supabase_db tenga un método de update por chat_id+fecha o similar
                # Ojo: La implementación original de 'marcar_como_notificado' en supabase_db recibía el ID de la BD.
                # Aquí tenemos un ID local que NO es el de Supabase.
                pass 
            except Exception:
                pass

    def _guardar_recordatorio_local(self, datos: Dict[str, Any], sync_status: str) -> int:
        with self.get_local_connection() as conn:
            cursor = conn.cursor()
            
            # Convertir booleanos/tipos para SQLite
            notificado = 1 if datos.get("notificado") else 0
            es_utc = 1 if datos.get("es_formato_utc") else 0
            constante = 1 if datos.get("aviso_constante") else 0
            detenido = 1 if datos.get("aviso_detenido") else 0
            
            # Manejo robusto de 'repetir'
            repetir_raw = datos.get("repetir")
            if isinstance(repetir_raw, bool):
                repetir = 1 if repetir_raw else 0
            elif isinstance(repetir_raw, str):
                repetir = 1 if repetir_raw.lower() in ['true', 'si', 'yes', 'y'] else 0
            else:
                repetir = 0

            rep_creada = 1 if datos.get("repeticion_creada") else 0
            
            # Serializar fecha si es objeto datetime
            fecha_hora = datos.get("fecha_hora")
            if isinstance(fecha_hora, datetime):
                fecha_hora = fecha_hora.isoformat()
            
            creado_en = datos.get("creado_en")
            if isinstance(creado_en, datetime):
                creado_en = creado_en.isoformat()

            cursor.execute('''
                INSERT INTO recordatorios (
                    chat_id, usuario, nombre_tarea, descripcion, fecha_hora, 
                    creado_en, notificado, es_formato_utc, aviso_constante, 
                    aviso_detenido, repetir, intervalo_repeticion, intervalos, 
                    repeticion_creada, sync_status, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(datos["chat_id"]),
                datos["usuario"],
                datos["nombre_tarea"],
                datos.get("descripcion"),
                fecha_hora,
                creado_en,
                notificado,
                es_utc,
                constante,
                detenido,
                repetir,
                datos.get("intervalo_repeticion", ""),
                datos.get("intervalos", 0),
                rep_creada,
                sync_status,
                datetime.utcnow().isoformat()
            ))
            local_id = cursor.lastrowid
            conn.commit()
            return local_id

    def _actualizar_estado_sync_recordatorio(self, local_id: int, status: str, supabase_id: Optional[int] = None):
        with self.get_local_connection() as conn:
            cursor = conn.cursor()
            if supabase_id:
                cursor.execute('UPDATE recordatorios SET sync_status = ?, supabase_id = ? WHERE id = ?', (status, supabase_id, local_id))
            else:
                cursor.execute('UPDATE recordatorios SET sync_status = ? WHERE id = ?', (status, local_id))
            conn.commit()

    def sincronizar_pendientes(self):
        """Busca registros locales pendientes y los sube a Supabase."""
        if not self.verificar_conexion_supabase():
            return

        with self.get_local_connection() as conn:
            # Obtener pendientes de creación
            cursor = conn.execute("SELECT * FROM recordatorios WHERE sync_status = 'pending'")
            pendientes = cursor.fetchall()
            
            for row in pendientes:
                datos = dict(row)
                logger.info(f"Sincronizando recordatorio pendiente ID local: {datos['id']}")
                
                # Reconstruir diccionario para Supabase
                datos_para_envio = {
                    "chat_id": datos["chat_id"],
                    "usuario": datos["usuario"],
                    "nombre_tarea": datos["nombre_tarea"],
                    "descripcion": datos["descripcion"],
                    "fecha_hora": datos["fecha_hora"], # Supabase espera string ISO o datetime
                    "creado_en": datos["creado_en"],
                    "es_formato_utc": bool(datos["es_formato_utc"]),
                    "aviso_constante": bool(datos["aviso_constante"]),
                    "repetir": bool(datos["repetir"]),
                    "intervalo_repeticion": datos["intervalo_repeticion"],
                    "intervalos": datos["intervalos"]
                }
                
                try:
                    if supabase_db.guardar_recordatorio(datos_para_envio):
                        self._actualizar_estado_sync_recordatorio(row['id'], 'synced')
                        logger.info(f"--> Sincronizado exitosamente.")
                except Exception as e:
                    logger.error(f"Error sincronizando ID {row['id']}: {e}")


    # TODO: Implementar lógica para Chats Info y otras tablas
    
# Singleton
db_manager = DatabaseManager()
