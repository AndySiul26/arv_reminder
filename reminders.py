from datetime import datetime
import time
import threading
import schedule
from supabase_db import obtener_recordatorios_pendientes, marcar_como_notificado
from services import enviar_telegram

class AdministradorRecordatorios:
    def __init__(self):
        self.activo = False
        self.hilo = None
    
    def iniciar(self):
        """Inicia el administrador de recordatorios en un hilo separado"""
        if not self.activo:
            self.activo = True
            self.hilo = threading.Thread(target=self._ejecutar)
            self.hilo.daemon = True  # El hilo se cerrará cuando termine el programa principal
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
        # Programar la verificación de recordatorios cada minuto
        schedule.every(1).minutes.do(self.verificar_recordatorios)
        
        while self.activo:
            schedule.run_pending()
            time.sleep(1)  # Pequeña pausa para no consumir CPU innecesariamente
    
    def verificar_recordatorios(self):
        """Verifica si hay recordatorios pendientes y los envía"""
        print(f"Verificando recordatorios: {datetime.now().isoformat()}")
        recordatorios = obtener_recordatorios_pendientes()
        
        for recordatorio in recordatorios:
            self._enviar_recordatorio(recordatorio)
    
    def _enviar_recordatorio(self, recordatorio):
        """Envía un recordatorio al usuario"""
        try:
            chat_id = recordatorio["chat_id"]
            
            # Formatear fecha si existe
            fecha_hora_str = ""
            if recordatorio.get("fecha_hora"):
                try:
                    dt = datetime.fromisoformat(recordatorio["fecha_hora"])
                    fecha_hora_str = f" (programado para {dt.strftime('%d/%m/%Y a las %H:%M')})"
                except:
                    fecha_hora_str = ""
            
            # Crear mensaje de recordatorio
            mensaje = "⏰ *RECORDATORIO*\n\n"
            mensaje += f"📝 *Tarea:* {recordatorio['nombre_tarea']}\n"
            mensaje += f"📋 *Descripción:* {recordatorio['descripcion']}\n"
            mensaje += fecha_hora_str
            
            # Enviar mensaje
            enviar_telegram(chat_id, tipo="texto", mensaje=mensaje)
            
            # Marcar como notificado
            marcar_como_notificado(recordatorio["id"])
            
            print(f"Recordatorio enviado a {chat_id}: {recordatorio['nombre_tarea']}")
            
        except Exception as e:
            print(f"Error al enviar recordatorio: {e}")

# Instancia global del administrador de recordatorios
administrador_recordatorios = AdministradorRecordatorios()

def iniciar_administrador():
    """Inicia el administrador de recordatorios"""
    administrador_recordatorios.iniciar()

def detener_administrador():
    """Detiene el administrador de recordatorios"""
    administrador_recordatorios.detener()

def verificar_recordatorios_ahora():
    """Ejecuta inmediatamente una verificación de recordatorios"""
    administrador_recordatorios.verificar_recordatorios()