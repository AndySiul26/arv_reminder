from datetime import datetime
import json
import re

# Estados de conversación
ESTADO_INICIAL = "inicial"
ESTADO_NOMBRE_TAREA = "nombre_tarea"
ESTADO_DESCRIPCION_TAREA = "descripcion_tarea"
ESTADO_FECHA_HORA = "fecha_hora"
ESTADO_CONFIRMAR = "confirmar"

# Diccionario para almacenar temporalmente las conversaciones activas
# {chat_id: {"estado": estado_actual, "datos": {datos_del_recordatorio}}}
conversaciones = {}

def iniciar_recordatorio(chat_id, nombre_usuario):
    """Inicia un nuevo recordatorio para el usuario"""
    conversaciones[chat_id] = {
        "estado": ESTADO_NOMBRE_TAREA,
        "datos": {
            "usuario": nombre_usuario,
            "creado_en": datetime.now().isoformat()
        }
    }
    
    return "¿Qué tarea necesitas recordar? Por favor, escribe el nombre de la tarea."

def 

def procesar_mensaje(chat_id, texto, nombre_usuario):
    """Procesa un mensaje del usuario según el estado de la conversación"""
    # Si no hay una conversación activa, iniciarla
    if chat_id not in conversaciones:
        if texto.lower() == "/recordatorio" or texto.lower() == "recordatorio":
            return iniciar_recordatorio(chat_id, nombre_usuario)
        else:
            return mostrar_ayuda(nombre_usuario)
    
    # Procesar según el estado actual de la conversación
    estado_actual = conversaciones[chat_id]["estado"]
    
    if estado_actual == ESTADO_NOMBRE_TAREA:
        conversaciones[chat_id]["datos"]["nombre_tarea"] = texto
        conversaciones[chat_id]["estado"] = ESTADO_DESCRIPCION_TAREA
        return "¡Entendido! Ahora, por favor escribe una breve descripción de la tarea."
    
    elif estado_actual == ESTADO_DESCRIPCION_TAREA:
        conversaciones[chat_id]["datos"]["descripcion"] = texto
        conversaciones[chat_id]["estado"] = ESTADO_FECHA_HORA
        return ("¿Cuándo necesitas que te recuerde esta tarea? Por favor, indica la fecha y hora en formato DD/MM/YYYY HH:MM.\n"
                "Por ejemplo: 20/04/2025 15:30\n"
                "O escribe 'sin fecha' si no necesitas un recordatorio específico.")
    
    elif estado_actual == ESTADO_FECHA_HORA:
        if texto.lower() == "sin fecha":
            conversaciones[chat_id]["datos"]["fecha_hora"] = None
        else:
            # Intentar parsear la fecha y hora
            try:
                fecha_hora = datetime.strptime(texto, "%d/%m/%Y %H:%M")
                conversaciones[chat_id]["datos"]["fecha_hora"] = fecha_hora.isoformat()
            except ValueError:
                return ("Lo siento, no pude entender el formato de fecha y hora. Por favor, utiliza el formato DD/MM/YYYY HH:MM.\n"
                        "Por ejemplo: 20/04/2025 15:30\n"
                        "O escribe 'sin fecha' si no necesitas un recordatorio específico.")
        
        # Pasar al estado de confirmación
        conversaciones[chat_id]["estado"] = ESTADO_CONFIRMAR
        return generar_mensaje_confirmacion(chat_id)
    
    elif estado_actual == ESTADO_CONFIRMAR:
        if texto.lower() in ["sí", "si", "s", "yes", "y", "confirmar"]:
            # Guardar el recordatorio
            datos = conversaciones[chat_id]["datos"]
            resultado = guardar_recordatorio(chat_id, datos)
            
            # Limpiar la conversación
            del conversaciones[chat_id]
            
            if resultado:
                return "¡Tu recordatorio ha sido guardado exitosamente! Te avisaré cuando sea el momento."
            else:
                return "Lo siento, hubo un problema al guardar tu recordatorio. Por favor, intenta nuevamente."
        
        elif texto.lower() in ["no", "n", "cancelar"]:
            # Cancelar el recordatorio
            del conversaciones[chat_id]
            return "He cancelado la creación del recordatorio. ¿En qué más puedo ayudarte?"
        
        else:
            return "Por favor confirma con 'sí' o 'no' si los datos son correctos."
    
    return "Lo siento, no entendí tu mensaje. ¿En qué puedo ayudarte?"

def generar_mensaje_confirmacion(chat_id):
    """Genera un mensaje de confirmación con los datos del recordatorio"""
    datos = conversaciones[chat_id]["datos"]
    mensaje = "Por favor confirma los detalles de tu recordatorio:\n\n"
    mensaje += f"📝 *Tarea:* {datos['nombre_tarea']}\n"
    mensaje += f"📋 *Descripción:* {datos['descripcion']}\n"
    
    if datos.get("fecha_hora"):
        # Convertir ISO a objeto datetime y luego a formato legible
        try:
            dt = datetime.fromisoformat(datos["fecha_hora"])
            fecha_formateada = dt.strftime("%d/%m/%Y a las %H:%M")
            mensaje += f"🕒 *Fecha y hora:* {fecha_formateada}\n"
        except:
            mensaje += f"🕒 *Fecha y hora:* {datos.get('fecha_hora', 'No especificada')}\n"
    else:
        mensaje += "🕒 *Fecha y hora:* No especificada\n"
    
    mensaje += "\n¿Son correctos estos datos? Responde 'sí' para confirmar o 'no' para cancelar."
    return mensaje

def mostrar_ayuda(nombre_usuario):
    """Muestra un mensaje de ayuda al usuario"""
    mensaje = f"¡Hola {nombre_usuario}! Soy ARV Reminder y te puedo ayudar a recordar tus tareas.\n\n"
    mensaje += "Puedes usar los siguientes comandos:\n"
    mensaje += "• /recordatorio - Crear un nuevo recordatorio\n"
    mensaje += "• /pendientes - Ver tus recordatorios pendientes\n"
    mensaje += "• /ayuda - Mostrar este mensaje de ayuda\n\n"
    mensaje += "Para comenzar, escribe /recordatorio"
    
    return mensaje

def guardar_recordatorio(chat_id, datos):
    """
    Guarda el recordatorio en Supabase
    """
    try:
        # Importar el módulo de Supabase
        from supabase_db import guardar_recordatorio as guardar_en_supabase
        
        # Agregar el chat_id a los datos si no está presente
        if "chat_id" not in datos:
            datos["chat_id"] = chat_id
        
        # Guardar en Supabase
        resultado = guardar_en_supabase(datos)
        return resultado
    except Exception as e:
        print(f"Error al guardar recordatorio: {e}")
        
        # Como plan B, guardar en archivo local
        try:
            from services import guardar_diccionario
            guardar_diccionario(datos)
            print("Guardado en archivo local como respaldo")
            return True
        except:
            return False

def procesar_callback(chat_id, callback_data, nombre_usuario):
    """Procesa los callbacks de los botones inline"""
    if callback_data == "nuevo_recordatorio":
        return iniciar_recordatorio(chat_id, nombre_usuario)
    elif callback_data == "ver_pendientes":
        # Aquí implementarás la lógica para mostrar recordatorios pendientes
        return "Esta función estará disponible próximamente."
    elif callback_data == "cancelar":
        if chat_id in conversaciones:
            del conversaciones[chat_id]
        return "Operación cancelada. ¿En qué más puedo ayudarte?"
    
    return "Opción no reconocida."