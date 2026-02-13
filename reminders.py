from datetime import timedelta
from dateutil.relativedelta import relativedelta
# Usamos el manager para guardar, que maneja la lógica dual
from database_manager import db_manager 
# Mantenemos imports de supabase_db para funciones que aún no migramos o auxiliares
from supabase_db import (
    leer_modo_tester, 
    actualizar_estado_chat_id,
    marcar_como_repetido,
    eliminar_recordatorios_finalizados,
    obtener_chats_sin_zona_horaria
)
import json
from datetime import datetime
import time
import threading
import schedule, os, requests
import utilidades

from gestionar_actualizaciones import (
    registrar_chats_si_no_existen,
    obtener_chats_para_actualizacion,
    actualizar_id_ultima_actualizacion_para_chat,
    obtener_ultima_actualizacion
)

from services import enviar_telegram
import conversations  # Para pedir zona y actualizar recordatorios


TEST_USER_ID = os.environ.get("TELEGRAM_TEST_USER_ID") 
URL_MONITOR = os.environ.get("URL_MONITOR","") 

class AdministradorRecordatorios:
    def __init__(self):
        self.activo = False
        self.hilo = None
        self.job_corregir = None  # aquí guardaremos el Job de corrección

    def iniciar(self):
        """Inicia el administrador de recordatorios en un hilo separado"""
        if not self.activo:
            self.activo = True
            self.hilo = threading.Thread(target=self._ejecutar)
            self.hilo.daemon = True
            self.hilo.start()
            print("Administrador de recordatorios iniciado")

    def detener(self):
        """Detiene el administrador de recordatorios"""
        self.activo = False
        if self.hilo:
            self.hilo.join(timeout=1.0)
        print("Administrador de recordatorios detenido")

    def _ejecutar(self):
        """Método principal que se ejecuta en el hilo"""
        
        # Inicializar DB local
        db_manager.inicializar_db_local()

        # --- CORRECCIÓN INICIAL ---
        primero_ok = self.corregir_recordatorios()
        if not primero_ok:
            # si había chats sin zona, programamos chequeo periódico
            self.job_corregir = schedule.every(1).minutes.do(self._job_corregir)
            print("Programada corrección periódica de zonas horarias")

        # --- PROGRAMACIÓN NORMAL ---
        verificar_recordatorios_ahora()
        schedule.every(1).minutes.do(self.verificar_recordatorios)
        schedule.every(5).minutes.do(self.verificar_actualizaciones)
        
        # --- SINCRONIZACIÓN BACKGROUND ---
        # Intentar subir pendientes cada 2 minutos
        schedule.every(2).minutes.do(db_manager.sincronizar_pendientes) 

        # Bucle principal
        while self.activo:
            schedule.run_pending()
            time.sleep(1)

    def _job_corregir(self):
        """
        Job intermedio que ejecuta corregir_recordatorios y se anula
        si ya no quedan chats sin zona horaria.
        """
        hecho = self.corregir_recordatorios()
        if hecho and self.job_corregir:
            schedule.cancel_job(self.job_corregir)
            print("Corrección de zonas completada. Job cancelado.")
            self.job_corregir = None

    def verificar_recordatorios(self):
        """Verifica si hay recordatorios pendientes y los envía"""
        print(f"[{datetime.now().isoformat()}] Verificando recordatorios (Fuente: SQLite Local)...")
        # AHORA LEEMOS DE LA BD LOCAL
        pendientes = db_manager.obtener_recordatorios_pendientes()
        
        # Filtro adicional de fecha aquí, ya que el SQL trae todos los 'no notificados' 
        # (Optimizacion: mover filtro fecha al SQL en db_manager si crece mucho)
        ahora_utc = datetime.utcnow()
        
        for recordatorio in pendientes:
            # Validar fecha vencida
            try:
                fecha_str = recordatorio.get("fecha_hora")
                if not fecha_str: continue
                
                fecha_dt = datetime.fromisoformat(fecha_str)
                # Asumimos que recordatorios en DB local se guardan normalizados si es posible,
                # pero 'fecha_hora' suele venir en ISO. 
                # Comparar con UTC actual.
                
                # Si 'fecha_dt' no tiene tzinfo, asumimos que es comparable con nuestra referencia
                # La logica original usaba 'hora_utc_servidor_segun_zona_host' pero aqui simplificamos.
                # Si la fecha del recordatorio <= ahora, se envía.
                
                # Hack simple: si fecha_dt es naive, asumirla UTC para comparar con utcnow
                if fecha_dt.tzinfo is None:
                     if fecha_dt > ahora_utc:
                         continue # Aún no toca
                else:
                    if fecha_dt > datetime.now(fecha_dt.tzinfo):
                        continue

            except Exception as e:
                print(f"Error procesando fecha recordatorio {recordatorio.get('id')}: {e}")
                continue

            self._enviar_recordatorio(recordatorio)

    def _enviar_recordatorio(self, recordatorio):
        """Envía un recordatorio al usuario y, si es repetible, crea el siguiente."""
        try:
            chat_id = recordatorio["chat_id"]
            print("Buscando ", chat_id, " en las conversaciones... (Envio de recordatorio)")
            conversaciones = conversations.inicializar_conversaciones(chat_id=chat_id, nombre_usuario=recordatorio.get("usuario",""))
            
            aviso_constante = bool(recordatorio.get("aviso_constante", False))
            repetir = bool(recordatorio.get("repetir", False))
            repeticion_creada = bool(recordatorio.get("repeticion_creada", False))
            simbolo = recordatorio.get("intervalo_repeticion", "")
            num = int(recordatorio.get("intervalos", 0))
            zona_horaria = conversaciones.get(chat_id,{}).get("datos",{}).get("zona_horaria","")

            # Formatear fecha si existe
            fecha_hora_str = ""
            if recordatorio.get("fecha_hora"):
                try:
                    recordatorio_fecha_hora_utc = recordatorio["fecha_hora"]
                    recordatorio_fecha_hora_local =  utilidades.convertir_fecha_utc_a_local(fecha_utc=datetime.fromisoformat(recordatorio_fecha_hora_utc), zona_horaria=zona_horaria)
                    # dt = datetime.fromisoformat(recordatorio_fecha_hora_local)
                    fecha_hora_str = f" (programado para {recordatorio_fecha_hora_local.strftime('%d/%m/%Y a las %H:%M')})"
                except Exception as e:
                    print("Error al convertir fecha hora en local:", str(e))

            # Crear mensaje
            mensaje = "⏰ *RECORDATORIO*\n\n"
            if aviso_constante:
                mensaje += "*Programado para aviso constante 📢 (envía 'parar')*\n"
            mensaje += f"📝 *Tarea:* {recordatorio['nombre_tarea']}\n"
            mensaje += f"📋 *Descripción:* {recordatorio['descripcion']}\n"
            mensaje += fecha_hora_str

            # Enviar
            if aviso_constante:
                ret = enviar_telegram(
                    chat_id=chat_id,
                    tipo="botones",
                    mensaje=mensaje,
                    botones=[{"texto": "Detener", "data": "parar"}],
                    formato="Markdown"
                )
            else:
                ret = enviar_telegram(chat_id, tipo="texto", mensaje=mensaje, formato="Markdown")

            # RECORDATORIOS DE AVISO CONSTANTE, SE EDITARAN ESOS MENSAJES CUANDO SE DETENGAN 
            try:
                if aviso_constante:
                    res = ret.json() # Convertimos a formato de diccionario
                    if res.get("ok", False) and conversaciones:
                        data = res.get("result", None)
                        if data:
                            message_id = data["message_id"]
                            datos = recordatorio
                            datos ["last_id_message"] = message_id
                            conversaciones[chat_id]["recordatorios_aviso_constante"].update({str(recordatorio.get("id","3")): datos})
                            txt_recordatorio = json.dumps(conversaciones[chat_id]["recordatorios_aviso_constante"])
                            actualizar_estado_chat_id(chat_id=chat_id, numero_estado= conversations.CAMPO_GUARDADO_RECORDATORIO_AVISO_CONSTANTE, nuevo_valor=txt_recordatorio)

            except Exception as e: 
                print("Error al guardar datos de mensaje en enviar recordatorio:", str(e))

            # Marcar como notificado (LOCALMENTE + INTENTO SYNC)
            db_manager.marcar_como_notificado(recordatorio["id"])

            # Si debe repetirse, crear siguiente
            if repetir and recordatorio.get("fecha_hora") and simbolo and num > 0 and not repeticion_creada:
                try:
                    original_dt = datetime.fromisoformat(recordatorio["fecha_hora"])

                    # Elegir tipo de delta
                    if simbolo == "s":
                        delta = timedelta(seconds=num)
                    elif simbolo == "x":
                        delta = timedelta(minutes=num)
                    elif simbolo == "h":
                        delta = timedelta(hours=num)
                    elif simbolo == "d":
                        delta = timedelta(days=num)
                    elif simbolo == "w":
                        delta = timedelta(weeks=num)
                    elif simbolo == "m":
                        delta = relativedelta(months=num)
                    elif simbolo == "a":
                        delta = relativedelta(years=num)
                    else:
                        delta = None

                    if delta:
                        nueva_dt = original_dt + delta
                        nuevo = {
                            "chat_id":           chat_id,
                            "usuario":           recordatorio["usuario"],
                            "nombre_tarea":      recordatorio["nombre_tarea"],
                            "descripcion":       recordatorio["descripcion"],
                            "fecha_hora":        nueva_dt.isoformat(),
                            "creado_en":         datetime.now().isoformat(),
                            "es_formato_utc":    True,
                            "repetir":           True,
                            "intervalos":        num,
                            "intervalo_repeticion": simbolo,
                            "aviso_constante":   aviso_constante
                        }
                        # GUARDAR NUEVO RECORDATORIO (USANDO MANAGER)
                        db_manager.guardar_recordatorio(nuevo)
                        
                        # Marcar el recordatorio original como repeticion_creada
                        # OJO: marcar_como_repetido es update simple. 
                        # Si estamos offline, esto podría fallar si se llama directo a supabase_db.
                        # Idealmente db_manager debería manejar esto también, pero por ahora...
                        try:
                           marcar_como_repetido(recordatorio["id"])
                        except:
                           pass # Si falla marking, se reintentará luego o quedará sucio pero no critico
                           
                        print(f"Siguiente recordatorio programado para {nueva_dt.isoformat()}")
                except Exception as e:
                    print(f"Error al crear siguiente recordatorio repetido: {e}")

            # Limpiar recordatorios finalizados
            # eliminar_recordatorios_finalizados() # Desactivar limpieza agresiva si estamos offline
            print(f"Recordatorio enviado a {chat_id}")

        except Exception as e:
            print(f"Error al enviar recordatorio: {e}")

    def verificar_actualizaciones(self):
        """Verifica y envía actualizaciones de bot a los chats correspondientes y realiza un ping al servidor monitor para mantenerlo vivo"""
        ping_otro_servidor()
        print(f"[{datetime.now().isoformat()}] Verificando actualizaciones...")
        try:
            registrar_chats_si_no_existen()
            chats = obtener_chats_para_actualizacion()
            if not chats:
                print("No hay nuevos chats para actualizar")
                return

            ultima = obtener_ultima_actualizacion()
            if not ultima:
                print("No hay actualizaciones registradas")
                return

            titulo = ultima["titulo"]
            desc   = ultima["descripcion"]
            msg    = f"🆕 *Actualización*\n\n*{titulo}*\n\n{desc}"

            # BLOQUE TESTER
            if leer_modo_tester():
                if TEST_USER_ID in chats:
                    enviar_telegram(TEST_USER_ID, tipo="texto", mensaje=msg, formato="Markdown")
                    actualizar_id_ultima_actualizacion_para_chat(TEST_USER_ID, ultima["id"])
                    print(f"Actualización enviada a {TEST_USER_ID}")
                    return

            for chat_id in chats:                
                enviar_telegram(chat_id, tipo="texto", mensaje=msg, formato="Markdown")
                actualizar_id_ultima_actualizacion_para_chat(chat_id, ultima["id"])
                print(f"Actualización enviada a {chat_id}")

        except Exception as e:
            print(f"Error al verificar actualizaciones: {e}")
        


    def corregir_recordatorios(self):
        """
        Envía a cada chat sin zona horaria un pedido de la misma + 
        luego disparará su corrección de recordatorios.
        Retorna True si no queda ningún chat sin zona horaria.
        """
        chats_pendientes = obtener_chats_sin_zona_horaria()
        
        # BLOQUE TESTER
        if leer_modo_tester():
            try:
                chats_id = [chat["chat_id"] for chat in chats_pendientes]
                chat_index = chats_id.index(TEST_USER_ID)
            
                conversations.pedir_zona_horaria_y_actualizar_recordatorios(
                    chat_id=TEST_USER_ID, 
                    nombre_usuario=chats_pendientes[chat_index].get("nombre") or ""
                )
                
            except Exception as e:
                print("No estaba el tester user:", e)
            return
        

        if chats_pendientes:
            for chat in chats_pendientes:
                conversations.pedir_zona_horaria_y_actualizar_recordatorios(
                    chat_id=chat["chat_id"], 
                    nombre_usuario=chat.get("nombre") or ""
                )
            return False
        return True

# Instancia global
administrador_recordatorios = AdministradorRecordatorios()

def iniciar_administrador():
    administrador_recordatorios.iniciar()

def detener_administrador():
    administrador_recordatorios.detener()

def verificar_recordatorios_ahora():
    administrador_recordatorios.verificar_recordatorios()

def verificar_actualizaciones_ahora():
    administrador_recordatorios.verificar_actualizaciones()

def ping_otro_servidor():
    if URL_MONITOR:
        try:
            print("Esperando 60 segundos antes de llamar al otro servidor...")
            threading.Timer(60.0, lambda: requests.get(URL_MONITOR)).start()
        except Exception as e:
            print(f"Error al llamar al otro servidor: {e}")

def aceptable_en_modo_tester(chat_id):
    # Obtener información de modo
    mod_tester = leer_modo_tester()

    # Acciones segun modo
    if mod_tester and chat_id != TEST_USER_ID:
        #enviar_telegram(chat_id, tipo="texto", mensaje="BOT EN MANTENIMIENTO. Le avisaré en cuanto este disponible")
        return False

    return True    

if __name__ == "__main__":
    iniciar_administrador()
    # Mantener el hilo vivo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        detener_administrador()
