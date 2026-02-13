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
            
            # Tabla de Eliminaciones Pendientes (para sincronizar bajas)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bajas_pendientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tabla TEXT NOT NULL, -- 'recordatorios'
                registro_id INTEGER, -- ID local
                supabase_id INTEGER, -- ID remoto (si tenía)
                fecha_eliminacion TEXT
            )
            ''')
            
            # --- TABLAS ADICIONALES (Espejos de Supabase) ---
            
            # actualizaciones_info
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS actualizaciones_info (
                id INTEGER PRIMARY KEY, -- ID de Supabase
                titulo TEXT,
                descripcion TEXT,
                fecha_hora TEXT
            )
            ''')

            # chats_avisados_actualizaciones
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats_avisados_actualizaciones (
                id INTEGER PRIMARY KEY, -- ID de Supabase
                chat_id TEXT,
                id_ultima_actualizacion INTEGER
            )
            ''')
            
            # chats_id_estados (Inferido)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats_id_estados (
                id INTEGER PRIMARY KEY,
                chat_id TEXT,
                estado TEXT,
                step TEXT,
                data TEXT, -- JSON string
                updated_at TEXT
            )
            ''')

            # modo_tester
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS modo_tester (
                id INTEGER PRIMARY KEY,
                activado INTEGER DEFAULT 0,
                modo_tester INTEGER DEFAULT 0, -- Posible nombre real de la columna
                descripcion TEXT
            )
            ''')
            
            conn.commit()
            logger.info("Base de datos local (SQLite) inicializada con TODAS las tablas.")

    def verificar_conexion_supabase(self) -> bool:
        """Verifica si Supabase está disponible y actualiza el estado interno."""
        # Optimización: Si falló hace poco, no reintentar inmediatamente (puedes agregar lógica de cooldown)
        try:
            if supabase_db and supabase_db.inicializar_supabase():
                self.supabase_online = True
                return True
        except:
            pass
        self.supabase_online = False
        return False

    def guardar_recordatorio(self, datos: Dict[str, Any]) -> bool:
        """
        Guarda o actualiza un recordatorio.
        1. Guarda en SQLite (siempre).
        2. Intenta guardar en Supabase.
        3. Actualiza estado de sincronización.
        """
        try:
            # Guardar localmente primero (Insert o Update)
            local_id = self._guardar_recordatorio_local(datos, sync_status='pending')
            
            exito_remoto = False
            supabase_id = None
            
            # Intentar remoto si hay conexión
            if self.verificar_conexion_supabase():
                try:
                    # Si ya tiene un supabase_id (es edicion), intentar update?
                    # Por simplicidad, el método 'guardar_recordatorio' de supabase_db actual hace INSERT siempre?
                    # Vamos a asumir que supabase_db maneja la logica de si existe o no, o lo adaptaremos.
                    # Asumimos que 'datos' tiene lo necesario.
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

    def eliminar_recordatorio(self, recordatorio_id_local: int, supabase_id: Optional[int] = None) -> bool:
        """
        Elimina un recordatorio.
        1. Elimina de SQLite.
        2. Registra en 'bajas_pendientes' si tenía ID remoto.
        3. Intenta eliminar de Supabase si hay conexión.
        """
        try:
            # 1. Obtener info antes de borrar (para saber supabase_id si no vino)
            with self.get_local_connection() as conn:
                cursor = conn.cursor()
                if not supabase_id:
                    cursor.execute("SELECT supabase_id FROM recordatorios WHERE id = ?", (recordatorio_id_local,))
                    row = cursor.fetchone()
                    if row and row['supabase_id']:
                        supabase_id = row['supabase_id']
                
                # 2. Borrar localmente
                cursor.execute("DELETE FROM recordatorios WHERE id = ?", (recordatorio_id_local,))
                
                # 3. Registrar baja pendiente si es necesario
                if supabase_id:
                    cursor.execute("INSERT INTO bajas_pendientes (tabla, registro_id, supabase_id, fecha_eliminacion) VALUES (?, ?, ?, ?)",
                                   ('recordatorios', recordatorio_id_local, supabase_id, datetime.utcnow().isoformat()))
                
                conn.commit()
                logger.info(f"Recordatorio local {recordatorio_id_local} eliminado.")

            # 4. Intentar borrar remoto inmediatamente
            if self.verificar_conexion_supabase() and supabase_id:
                try:
                    if supabase_db.eliminar_recordatorio_por_id(supabase_id):
                        # Si éxito, borrar de bajas_pendientes
                        self._eliminar_baja_pendiente(supabase_id)
                        logger.info(f"Recordatorio remoto {supabase_id} eliminado sincronizadamente.")
                except Exception as e:
                    logger.warning(f"No se pudo eliminar remoto {supabase_id} ahora. Se encoló: {e}")

            return True

        except Exception as e:
            logger.error(f"Error al eliminar recordatorio {recordatorio_id_local}: {e}")
            return False

    def _eliminar_baja_pendiente(self, supabase_id: int):
        with self.get_local_connection() as conn:
            conn.execute("DELETE FROM bajas_pendientes WHERE supabase_id = ?", (supabase_id,))
            conn.commit()

    def obtener_recordatorios_pendientes(self) -> List[Dict]:
        """Obtiene recordatorios pendientes de notificar desde LOCAL."""
        with self.get_local_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recordatorios WHERE notificado = 0")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def marcar_como_notificado(self, recordatorio_id: int):
        """Marca como notificado en local y encolar sync a remoto."""
        with self.get_local_connection() as conn:
            conn.execute("UPDATE recordatorios SET notificado = 1, sync_status = 'pending_update', last_updated = ? WHERE id = ?", 
                         (datetime.utcnow().isoformat(), recordatorio_id))
            conn.commit()
            
        # Intentar sync rápida (opcional, dejamos que el job lo haga para no frenar el hilo de envíos)
        # self.sincronizar_pendientes() 

    def _guardar_recordatorio_local(self, datos: Dict[str, Any], sync_status: str) -> int:
        # Implementación simple: si viene ID local, es update. Si no, insert.
        # Pero ojo: 'datos' suele venir del bot sin ID local si es nuevo.
        # ¿Cómo sabemos si es update? Depende de cómo lo llame el bot.
        # Por ahora asumimos insert siempre si no trae 'id' explícito o si no existe.
        
        # FIX: Para evitar duplicados en reinicios, idealmente chequearíamos por chat_id + nombre_tarea + fecha... 
        # pero es arriesgado.
        
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
            
            # Serializar fecha
            fecha_hora = datos.get("fecha_hora")
            if isinstance(fecha_hora, datetime):
                fecha_hora = fecha_hora.isoformat()
            
            creado_en = datos.get("creado_en")
            if isinstance(creado_en, datetime):
                creado_en = creado_en.isoformat()

            # Insertar
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

    def sincronizar_todo(self):
        """Ejecuta sincronización bidireccional completa."""
        if not self.verificar_conexion_supabase():
            return

        logger.info("--- Iniciando ciclo de sincronización ---")
        self.sincronizar_local_a_remoto() # Subir cambios
        self.sincronizar_remoto_a_local() # Bajar cambios
        logger.info("--- Fin ciclo de sincronización ---")

    def sincronizar_local_a_remoto(self):
        """Sube bajas pendientes y registros pendientes a Supabase."""
        with self.get_local_connection() as conn:
            # 1. Procesar Bajas (Deletions)
            cursor = conn.execute("SELECT * FROM bajas_pendientes")
            bajas = cursor.fetchall()
            for baja in bajas:
                if baja['supabase_id']:
                    try:
                        # Intentar eliminar en Supabase
                        # Nota: eliminar_recordatorio_por_id ya devuelve True/False
                        if supabase_db.eliminar_recordatorio_por_id(baja['supabase_id']):
                            conn.execute("DELETE FROM bajas_pendientes WHERE id = ?", (baja['id'],))
                            logger.info(f"Baja sincronizada: Supabase ID {baja['supabase_id']}")
                        else:
                            # Si falla porque no existe (ya borrado), también limpiamos
                            # ¿Cómo saberlo? Por ahora asumimos que si falló es por error de red.
                            pass 
                    except Exception as e:
                        logger.error(f"Error sync baja {baja['supabase_id']}: {e}")
            conn.commit()

            # 2. Procesar Altas (Inserts)
            cursor = conn.execute("SELECT * FROM recordatorios WHERE sync_status = 'pending'")
            pendientes = cursor.fetchall()
            for row in pendientes:
                datos = dict(row)
                datos_para_envio = {
                    "chat_id": datos["chat_id"],
                    "usuario": datos["usuario"],
                    "nombre_tarea": datos["nombre_tarea"],
                    "descripcion": datos["descripcion"],
                    "fecha_hora": datos["fecha_hora"],
                    "creado_en": datos["creado_en"],
                    "es_formato_utc": bool(datos["es_formato_utc"]),
                    "aviso_constante": bool(datos["aviso_constante"]),
                    "repetir": bool(datos["repetir"]),
                    "intervalo_repeticion": datos["intervalo_repeticion"],
                    "intervalos": datos["intervalos"]
                }
                
                try:
                    # Necesitamos que supabase_db nos devuelva el registro insertado para obtener el ID real
                    # Tendremos que modificar supabase_db.guardar_recordatorio o asumir insert simple por ahora
                    # y esperar que 'sincronizar_remoto_a_local' traiga el ID luego.
                    if supabase_db.guardar_recordatorio(datos_para_envio):
                        # Marcamos como synced. El ID de supabase se actualizará cuando hagamos pull.
                        self._actualizar_estado_sync_recordatorio(row['id'], 'synced')
                        logger.info(f"Insert local {row['id']} subido a Supabase.")
                except Exception as e:
                    logger.error(f"Error subiendo insert {row['id']}: {e}")

            # 3. Procesar Modificaciones (Updates - ej: notificado)
            cursor = conn.execute("SELECT * FROM recordatorios WHERE sync_status = 'pending_update'")
            pendientes = cursor.fetchall()
            for row in pendientes:
                if row['supabase_id']:
                    try:
                        # Si es solo marcar notificado
                        if row['notificado']:
                            supabase_db.marcar_como_notificado(row['supabase_id'])
                        
                        self._actualizar_estado_sync_recordatorio(row['id'], 'synced', row['supabase_id'])
                        logger.info(f"Update local {row['id']} subido a Supabase.")
                    except Exception as e:
                        logger.error(f"Error subiendo update {row['id']}: {e}")
            
            conn.commit()

    def sincronizar_remoto_a_local(self):
        """Descarga nuevos recordatorios de Supabase a Local y actualiza existentes."""
        try:
            # Traer TODO de Supabase de los chats que tenemos localmente? 
            # O traer updates recientes?
            # Para robustez inicial: Traer todos los 'pendientes' de Supabase (no notificados)
            # y actualizar nuestra BD local.
            
            remotos = supabase_db.obtener_recordatorios_pendientes(pagina_tamano=1000)
            if not remotos:
                return

            with self.get_local_connection() as conn:
                cursor = conn.cursor()
                for rem in remotos:
                    supa_id = rem['id']
                    
                    # Verificar si existe localmente (por supabase_id)
                    cursor.execute("SELECT id, last_updated FROM recordatorios WHERE supabase_id = ?", (supa_id,))
                    local_row = cursor.fetchone()

                    if local_row:
                        # Existe. ¿Actualizar?
                        # Estrategia simple: El remoto manda. (Server Authority)
                        # Salvo que local tenga cambios pendientes ('pending_update').
                        # Pero aquí simplificamos: Sobreescribir local con remoto.
                        
                        # Fix: Mapear campos de supabase a local schema
                        cursor.execute('''
                            UPDATE recordatorios SET
                                chat_id=?, usuario=?, nombre_tarea=?, descripcion=?, fecha_hora=?, 
                                notificado=?, es_formato_utc=?, aviso_constante=?, 
                                aviso_detenido=?, repetir=?, intervalo_repeticion=?, intervalos=?, 
                                repeticion_creada=?, sync_status='synced', last_updated=?
                            WHERE id=?
                        ''', (
                            str(rem["chat_id"]), rem["usuario"], rem["nombre_tarea"], rem.get("descripcion"),
                            rem.get("fecha_hora"), 1 if rem.get("notificado") else 0,
                            1 if rem.get("es_formato_utc") else 0, 1 if rem.get("aviso_constante") else 0,
                            1 if rem.get("aviso_detenido") else 0, 1 if rem.get("repetir") else 0,
                            rem.get("intervalo_repeticion"), rem.get("intervalos"),
                            1 if rem.get("repeticion_creada") else 0,
                            datetime.utcnow().isoformat(),
                            local_row['id']
                        ))
                    else:
                        # No existe localmente (por ID de supabase).
                        # ¿Verificar si fue borrado localmente?
                        cursor.execute("SELECT id FROM bajas_pendientes WHERE supabase_id = ?", (supa_id,))
                        baja = cursor.fetchone()
                        if baja:
                            logger.info(f"Registro remoto {supa_id} ignorado porque está borrado localmente.")
                            continue

                        # Insertar nuevo
                        cursor.execute('''
                            INSERT INTO recordatorios (
                                chat_id, usuario, nombre_tarea, descripcion, fecha_hora, 
                                creado_en, notificado, es_formato_utc, aviso_constante, 
                                aviso_detenido, repetir, intervalo_repeticion, intervalos, 
                                repeticion_creada, supabase_id, sync_status, last_updated
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            str(rem["chat_id"]), rem["usuario"], rem["nombre_tarea"], rem.get("descripcion"),
                            rem.get("fecha_hora"), rem.get("creado_en"),
                            1 if rem.get("notificado") else 0, 1 if rem.get("es_formato_utc") else 0,
                            1 if rem.get("aviso_constante") else 0, 1 if rem.get("aviso_detenido") else 0,
                            1 if rem.get("repetir") else 0, rem.get("intervalo_repeticion"),
                            rem.get("intervalos"), 1 if rem.get("repeticion_creada") else 0,
                            supa_id, 'synced', datetime.utcnow().isoformat()
                        ))
                        logger.info(f"Registro remoto {supa_id} importado a local.")
                
                conn.commit()

        except Exception as e:
            logger.error(f"Error en pull remoto: {e}")

    def sincronizar_pendientes(self):
        # Alias para mantener compatibilidad temporal, redirige a sincronizar_todo
        self.sincronizar_todo()


    # TODO: Implementar lógica para Chats Info y otras tablas
    
# Singleton
db_manager = DatabaseManager()
