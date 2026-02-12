import threading
# ... el resto de tus importaciones mod detener avisos
from datetime import datetime, timedelta
from services import enviar_telegram, editar_botones_mensaje, editar_mensaje_con_botones, editar_mensaje_texto
import supabase_db
from supabase_db import actualizar_campos_recordatorio  # IMPORT
import utilidades, os
import json


import plantillas

# Guarda la última vez (UTC) que pedimos zona para cada chat
_last_zona_request: dict[str, datetime] = {}

# — NUEVOS ESTADOS PARA EDICIÓN —
ESTADO_EDITAR_INICIAL        = "editar_inicial"
ESTADO_EDITAR_SELECCION      = "editar_seleccion"
ESTADO_EDITAR_CAMPO          = "editar_campo"
ESTADO_EDITAR_VALOR          = "editar_valor"
# Estados de conversación
ESTADO_INICIAL = "inicial"
ESTADO_NOMBRE_TAREA = "nombre_tarea"
ESTADO_DESCRIPCION_TAREA = "descripcion_tarea"
ESTADO_ZONA_HORARIA = "zona_horaria"
ESTADO_ZONA_HORARIA_CONFIRMAR = "zona_horaria_confirmar"
ESTADO_FECHA_HORA = "fecha_hora"
ESTADO_REPETIR = "repetir"
ESTADO_INTERVALO_REPETICION = "intervalos"
ESTADO_AVISO_CONSTANTE = "aviso_constante"
ESTADO_CONFIRMAR = "confirmar"

CAMPO_GUARDADO_PETICION_ZONA_HORARIA = 1
CAMPO_GUARDADO_ESTADO = 2
CAMPO_GUARDADO_DATOS = 3
CAMPO_GUARDADO_RECORDATORIO_AVISO_CONSTANTE = 4

# Zonas horarias disponibles
ZONAS_HORARIAS = {
    "America/Mexico_City":       "Ciudad de México",
    "America/Argentina/Buenos_Aires": "Buenos Aires",
    "America/Bogota":            "Bogotá",
    "America/Lima":              "Lima",
    "America/Santiago":          "Santiago",
    "America/Caracas":           "Caracas",
    "Europe/Madrid":             "Madrid",
    "Europe/London":             "Londres",
    "Asia/Tokyo":                "Tokio",
    "Asia/Kolkata":              "Nueva Delhi"
}

# Mapa para mostrar nombre de campo amigable
FIELD_LABELS = {
    "nombre_tarea":        "nombre de la tarea",
    "descripcion":         "descripción",
    "fecha_hora":          "fecha y hora",
    "repetir":             "repetición automática",
    "intervalo_repeticion":"tipo de intervalo",
    "intervalos":          "número de intervalos",
}

tester_chat_id = os.environ.get("TELEGRAM_TEST_USER_ID")

# Diccionario para almacenar temporalmente las conversaciones activas
# {chat_id: {"estado": estado_actual, "datos": {datos_del_recordatorio}}}
conversaciones = {}

def inicializar_conversaciones(chat_id, nombre_usuario=""):
    """Inicializa los estados de conversaciones del chat_id"""
    if not chat_id in conversaciones:
        info_chat = supabase_db.obtener_info_chat(chat_id)
        info_estado = supabase_db.leer_estado_chat_id(chat_id=chat_id, numero_estado=CAMPO_GUARDADO_ESTADO)
        info_datos = supabase_db.leer_estado_chat_id(chat_id=chat_id, numero_estado=CAMPO_GUARDADO_DATOS)
        info_recordatorios_avisos_constantes = supabase_db.leer_estado_chat_id(chat_id=chat_id, numero_estado=CAMPO_GUARDADO_RECORDATORIO_AVISO_CONSTANTE)
        
        if info_datos:
            datos = json.loads(info_datos)
            conversaciones[chat_id] = {
                "datos": datos,
                "estado": info_estado or ""
            }
        else:
            conversaciones[chat_id] = {
                "datos": {},
                "estado": info_estado or ""
            }

        if info_recordatorios_avisos_constantes:
            conversaciones[chat_id]["recordatorios_aviso_constante"] = json.loads(info_recordatorios_avisos_constantes)
        else:
            conversaciones[chat_id]["recordatorios_aviso_constante"] = {}

        conversaciones[chat_id]["datos"].update ({
                "usuario": nombre_usuario,
                "creado_en": utilidades.hora_utc_servidor_segun_zona_host().isoformat(),
                "tipo":  info_chat.get("tipo") or "",
                "zona_horaria":  info_chat.get("zona_horaria") or "",
                "es_formato_utc": False,
                "wait_callback":False # todas las funciones que terminen en enviar un mensaje con botones al usuario deben tener esta bandera en true, para que el manejo de callback lo mande al flujo general de conversaciones
            })
        
    return conversaciones

def obtener_recordatorios_aviso_constante(chat_id) -> bool:
    global conversaciones
    try:
        info_recordatorios_avisos_constantes = supabase_db.leer_estado_chat_id(chat_id=chat_id, numero_estado=CAMPO_GUARDADO_RECORDATORIO_AVISO_CONSTANTE)
        if info_recordatorios_avisos_constantes:
            conversaciones[chat_id]["recordatorios_aviso_constante"] = json.loads(info_recordatorios_avisos_constantes)
        else:
            conversaciones[chat_id]["recordatorios_aviso_constante"] = {}
            return False
    except Exception as e:
        print("Error al obtener los recordatorios de aviso constante: ", str(e))
        return False

    return True

        
def iniciar_recordatorio(chat_id, nombre_usuario):
    """Inicia un nuevo recordatorio para el usuario"""
    info_chat = supabase_db.obtener_info_chat(chat_id)
    conversaciones[chat_id].update({
        "estado": ESTADO_NOMBRE_TAREA,
        "creacion_recordatorio":True})
    conversaciones[chat_id]["datos"].update({
            "usuario": nombre_usuario,
            "creado_en": utilidades.hora_utc_servidor_segun_zona_host().isoformat(),
            "tipo":  info_chat.get("tipo") or "",
            "zona_horaria":  info_chat.get("zona_horaria") or "",
            "es_formato_utc": False,
            "wait_callback":False # todas las funciones que terminen en enviar un mensaje con botones al usuario deben tener esta bandera en true, para que el manejo de callback lo mande al flujo general de conversaciones
        }
    )
    
    return "¿Qué tarea necesitas recordar? Por favor, escribe el nombre de la tarea."

def iniciar_edicion(chat_id, nombre_usuario):
    """Inicia el flujo de edición de recordatorio, verificando zona antes."""
    
    # 1) Comprobar zona horaria
    info = supabase_db.obtener_info_chat(chat_id)
    if not info or not info.get("zona_horaria"):
        # Pedimos zona antes de editar
        enviar_telegram(chat_id, tipo="texto",
            mensaje="Para editar recordatorios necesito conocer tu zona horaria primero.", func_guardado_data=guardar_info_mensaje_enviado)
        return pedir_zona_horaria_y_actualizar_recordatorios(chat_id, nombre_usuario)

    # 2) Si hay zona, continuamos con la lista
    recordatorios = supabase_db.obtener_recordatorios_usuario(chat_id)
    if not recordatorios:
        enviar_telegram(chat_id, tipo="texto", mensaje="No tienes recordatorios para editar.", func_guardado_data=guardar_info_mensaje_enviado)
        return ""

    texto = "Selecciona el número del recordatorio que quieres editar:\n\n"
    for i, rec in enumerate(recordatorios, start=1):
        texto += f"{i}. {rec['nombre_tarea']}\n"
    texto += "\nEnvía el número correspondiente."

    conversaciones[chat_id].update({
        "estado": ESTADO_EDITAR_SELECCION, "wait_callback": True})
    
    conversaciones[chat_id]["datos"].update({
            "usuario": nombre_usuario,
            "zona_horaria": info.get("zona_horaria") ,
            "lista_editar": recordatorios
        })

    enviar_telegram(chat_id, tipo="texto", mensaje=texto)
    return ""

def guardar_info_mensaje_enviado(chat_id, info, nuevas_conversaciones=None):
    global conversaciones
    if nuevas_conversaciones:
        conversaciones = nuevas_conversaciones
    try:
        res = info.json() # Convertimos a formato de diccionario
        if res.get("ok", False):
            data = res.get("result", None)
            if data:
                message_id = data["message_id"]
                conversaciones[chat_id]["datos"]["last_id_message"] = message_id
                guardar_datos(chat_id=chat_id)
                return conversaciones
    except Exception as e:
        print("Error al guardar info de mensaje enviado:", str(e))
    return None

def guardar_datos(chat_id, nuevas_conversaciones = None, guardar_zona_horaria = False):
    # Usable fuera de este modulo
    global conversaciones
    if nuevas_conversaciones:
        conversaciones = nuevas_conversaciones
        
    if chat_id in conversaciones:
        if "datos" in conversaciones[chat_id]:
            if guardar_zona_horaria:
                supabase_db.guardar_zona_horaria_chat(
                    chat_id=chat_id,
                    zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],
                    nombre_chat=conversaciones[chat_id]["datos"]["usuario"],
                    tipo="private"
                )
            txt_datos = json.dumps(conversaciones[chat_id]["datos"], indent=4)  # `indent=4` para una salida más legible
            supabase_db.actualizar_estado_chat_id(chat_id=chat_id, numero_estado= CAMPO_GUARDADO_DATOS, nuevo_valor=txt_datos)
            return True
        
    return False

def mostrar_recordatorios(chat_id, nombre_usuario, solo_pendientes:bool):
    # [{'id': 23, 'chat_id': '54655066', 'usuario': 'Andy', 'nombre_tarea': 'Ir por licencia', 'descripcion': 'Documentacion', 'fecha_hora': '2025-06-06T09:06:00', 'creado_en': '2025-06-06T09:04:10.873179', 'notificado': True, 'aviso_constante': True, 'aviso_detenido': True, 'repetir': False, 'intervalo_repeticion': '', 'intervalos': 0, 'es_formato_utc': False}] 
    global conversaciones
    recordatorios=None
    data=None
    try:
        recordatorios = supabase_db.obtener_recordatorios_usuario(chat_id=chat_id)
        datos_msg = enviar_telegram(chat_id=chat_id, tipo="texto", mensaje="Revisando tus recordatorios...", formato="markdown").json()
        data = datos_msg.get("result", None)
        mensaje = ""
    except Exception as e:
        err_msg= f"Error al obtener recordatorios para mostrar lista al usuario ({chat_id})... Errores: " + str(e)
        # Informar al admin
        enviar_telegram(chat_id=tester_chat_id,tipo="texto", mensaje=err_msg)
        print(err_msg)

    if recordatorios:
        if solo_pendientes:
            pendientes = [r for r in recordatorios if not r.get("notificado", False)]
            listado = pendientes
            mensaje = f"*{nombre_usuario}, tus pendientes son:*\n\n" if listado else f"*{nombre_usuario}, no tienes recordatorios pendientes.*"
        else:
            listado = recordatorios
            mensaje = f"*{nombre_usuario}, todos tus recordatorios:*\n\n" if listado else f"*{nombre_usuario}, no tienes recordatorios.*"

        try:
            zona_horaria = conversaciones.get(chat_id, {}).get("datos", {}).get("zona_horaria", None)

            for r in listado:
                # Formato ISO esperado: '2025-06-06T09:06:00'
                try:
                    fecha_hora_recordatorio = datetime.strptime(r["fecha_hora"], "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    # Intentar con milisegundos si falla
                    fecha_hora_recordatorio = datetime.fromisoformat(r["fecha_hora"])

                if zona_horaria:
                    fecha_hora_local = utilidades.convertir_fecha_utc_a_local(fecha_utc=fecha_hora_recordatorio, zona_horaria=zona_horaria)
                else:
                    fecha_hora_local = fecha_hora_recordatorio

                mensaje += f"• *{r['nombre_tarea']}*: {r['descripcion']}\n"
                mensaje += f"  📅 {fecha_hora_local.strftime('%d/%m/%Y a las %H:%M')}\n"
                mensaje += f"  🔁 Repetible: {'Sí' if r['repetir'] else 'No'}\n"
                if r['repetir']:
                    mensaje += f"  ⌚ Intervalo: Cada {r['intervalos']} {significado_tiempo(r['intervalo_repeticion'], (r['intervalos'] > 1))}\n"
                mensaje += f"  🔔 Aviso constante: {'Sí' if r['aviso_constante'] else 'No'}\n\n"
                
        except Exception as e:
            print(f"Error al mostrar los recordatorios del usuario {chat_id}:", str(e))
            texto_error = "Error al mostrar los recordatorios, error informado al administrador. Disculpe las molestias."
            if data:
                editar_mensaje_texto(chat_id=chat_id, message_id=data["message_id"], nuevo_texto=texto_error, formato="markdown")
            else:
                enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=texto_error, formato="markdown")
            return "" # Finalizar ejecución si hubo error

        # Finalmente, editar el mensaje original con los resultados
        if data:
            editar_mensaje_texto(chat_id=chat_id, message_id=data["message_id"], nuevo_texto=mensaje, formato="markdown")
        else:
            enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=mensaje, formato="markdown")

    else:
        mensaje = f"{nombre_usuario}, no tienes recordatorios registrados aún."
        if data:
            editar_mensaje_texto(chat_id=chat_id, message_id=data["message_id"], nuevo_texto=mensaje, formato="markdown")
        else:
            enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=mensaje, formato="markdown")

def comprobacion_asignacion_fecha_hora(chat_id, raw):
    texto = raw.lower()
    
    # Caso 1: Si existe ":" en el texto
    if ":" in texto:
        num, intervalo = texto.split(":")
        if num.isdigit() and intervalo in ["s", "x", "h", "d", "w", "m", "a"]:
            numero = int(num)
            # Pasar al estado de aviso constante
            conversaciones[chat_id]["datos"]["intervalos"] = numero
            conversaciones[chat_id]["datos"]["intervalo_repeticion"] = intervalo
            guardar_estado(chat_id=chat_id, estado=ESTADO_AVISO_CONSTANTE)
            return True, generar_mensaje_aviso_constante(chat_id)
    
    # Caso 2: Si no existe ":" en el texto, comprobar desde el final
    else:
        unidades_tiempo_aceptadas = ["s", "x", "h", "d", "w", "m", "a"]
        for i, char in enumerate(reversed(texto)):
            if char in unidades_tiempo_aceptadas:
                intervalo = char
                num = texto[:-i-1]  # Todo lo que está a la izquierda del carácter
                if num.isdigit():
                    numero = int(num)
                    # Asignar a conversaciones
                    conversaciones[chat_id]["datos"]["intervalos"] = numero
                    conversaciones[chat_id]["datos"]["intervalo_repeticion"] = intervalo
                    guardar_estado(chat_id=chat_id, estado=ESTADO_AVISO_CONSTANTE)
                    return True, generar_mensaje_aviso_constante(chat_id)
                break  # Si se encontró una unidad de tiempo, no seguir buscando
    
    # Si no se cumple ninguna condición
    return False, "Error, sintaxis incorrecta, escribe el intervalo como por ejemplo 1:d (simbolos: s=segundos, x=minutos, h=horas, d=dias, m=meses, a=años)"

def guardar_estado (chat_id, estado,guardar_zona_horaria=False):
    conversaciones[chat_id]["estado"] = estado
    supabase_db.actualizar_estado_chat_id(chat_id=chat_id,numero_estado=CAMPO_GUARDADO_ESTADO, nuevo_valor=estado)
    guardar_datos(chat_id=chat_id, guardar_zona_horaria=guardar_zona_horaria)

def procesar_mensaje(chat_id, texto:str, nombre_usuario, es_callback=False, tipo = "Private", id_message = None, id_callback=None):
    """Procesa un mensaje del usuario según el estado de la conversación"""
    # Registra al chat_id 
    supabase_db.upsert_chat_info(chat_id=chat_id, nombre=nombre_usuario, tipo=tipo)
    inicializar_conversaciones(chat_id=chat_id, nombre_usuario=nombre_usuario)

    conversaciones[chat_id]["id_callback"]= id_callback if id_callback else conversaciones[chat_id]["datos"].get("last_id_message", None)
    
    # Si no hay conversación activa, chequeamos comandos globales

    if texto.lower() in ["/editar", "editar"]:
        return iniciar_edicion(chat_id, nombre_usuario)
    if texto.lower() in ["/recordatorio", "recordatorio"]:
        return iniciar_recordatorio(chat_id, nombre_usuario)
    if texto.lower() in ["/pendientes", "pendiente"]:
        return mostrar_recordatorios(chat_id, nombre_usuario, solo_pendientes=True)
    if texto.lower() in ["/recordatorios", "recordatorios"]:
        return mostrar_recordatorios(chat_id, nombre_usuario, solo_pendientes=False)
    if texto.lower() in ["/cancelar", "cancelar"]:
        if "editar" in conversaciones[chat_id].get("estado",""):
            msg = "La edición del recordatorio ha sido cancelada"
        elif conversaciones[chat_id].get("creacion_recordatorio", False):
            msg = "La creación del recordatorio ha sido cancelada"
        else:
            msg = "Acción cancelada"
        if conversaciones[chat_id]["id_callback"]:
            ret = editar_mensaje_texto(chat_id=chat_id,
                                 message_id=conversaciones[chat_id]["id_callback"],
                                 nuevo_texto=msg)
            if ret:
                if ret.ok:
                    msg =""

        guardar_estado(chat_id=chat_id, estado="")
        return msg
    elif texto.lower().strip() in ["parar","detener","alto"]:             
        return detener_avisos(chat_id)
    elif conversaciones[chat_id].get("estado", "") == "":            
        return mostrar_ayuda(nombre_usuario)
    
    
    # Procesar según el estado actual de la conversación
    estado_actual = conversaciones[chat_id]["estado"]

     # — FLUJO DE SELECCIÓN PARA EDICIÓN —
    if estado_actual == ESTADO_EDITAR_SELECCION:
        # esperamos un número
        try:
            idx = int(texto.strip()) - 1
            lista = conversaciones[chat_id]["datos"]["lista_editar"]
            rec = lista[idx]
        except Exception:
            enviar_telegram(chat_id, tipo="texto", mensaje="Número inválido. Por favor envía el número de la lista.", func_guardado_data=guardar_info_mensaje_enviado)
            return ""

        # Guardamos qué record vamos a editar
        conversaciones[chat_id]["datos"].update({
            "record_id": rec["id"],
            "record_data": rec
        })
        
        guardar_estado(chat_id=chat_id,estado= ESTADO_EDITAR_CAMPO)

        # Preguntamos qué campo
        botones = [
            {"texto": "Nombre de Tarea",         "data": "campo_nombre_tarea"},
            {"texto": "Descripción",   "data": "campo_descripcion"},
            {"texto": "Fecha/Hora",    "data": "campo_fecha_hora"},
            {"texto": "Repetir",       "data": "campo_repetir"},
            {"texto": "Intervalo",     "data": "campo_intervalo"},
            {"texto": "Aviso Const.",  "data": "campo_aviso_constante"},
            {"texto": "Eliminar",  "data": "campo_eliminar"},
            {"texto": "Cancelar",  "data": "cancelar"},
        ]
        enviar_telegram(
            chat_id, tipo="botones",
            mensaje="¿Qué campo deseas editar?",
            botones=botones, func_guardado_data=guardar_info_mensaje_enviado
        )
        conversaciones[chat_id]["wait_callback"] = True
        return ""

    # — FLUJO DE ELECCIÓN DE CAMPO — (llega por callback)
    if estado_actual == ESTADO_EDITAR_CAMPO:
        datos = conversaciones[chat_id]["datos"]
        record_id = datos["record_id"]
        if texto == "campo_eliminar":
            supabase_db.eliminar_recordatorio_por_id(recordatorio_id=record_id)
            if conversaciones[chat_id]["id_callback"]:
                editar_mensaje_texto(chat_id=chat_id, message_id= conversaciones[chat_id]["id_callback"], nuevo_texto="¡Recordatorio eliminado!", formato="Markdown")
            else:
                enviar_telegram(chat_id=chat_id, tipo="texto", mensaje="¡Recordatorio eliminado!", formato="Markdown")

            del conversaciones[chat_id]
            return ""
        campo_sel = texto  # ej. "campo_nombre_tarea"
        conversaciones[chat_id]["datos"]["campo_sel"] = campo_sel
        guardar_estado(chat_id=chat_id,estado= ESTADO_EDITAR_VALOR)
        # Pedimos nuevo valor
        
        prompt = {
            "campo_nombre_tarea": "Escribe el *nuevo nombre* de la tarea:",
            "campo_descripcion":  "Escribe la *nueva descripción*:",
            "campo_fecha_hora":   "Escribe la *nueva fecha y hora* (Ej: `25/12/2026 4:00 pm` o `25/12/2026 16:00`).\n*Nota:* Se guardará en formato de 24 horas.",
            "campo_repetir":      "¿Repetir? (si/no):",
            "campo_intervalo":     (
                                        "¿Con qué frecuencia deseas que se repita el recordatorio?\n"
                                        "Escribe el intervalo en el siguiente formato: `1:d o 1d`\n\n"
                                        "*Símbolos válidos:*\n"
                                        "`x` - minutos\n"
                                        "`h` - horas\n"
                                        "`d` - días\n"
                                        "`w` - semanas\n"
                                        "`m` - meses\n"
                                        "`a` - años\n\n"
                                        "*Ejemplo:* `2:h` o `2h` significa cada 2 horas"
                                    ),
        }.get(campo_sel, "Escribe el nuevo valor:")
        # enviar_telegram(chat_id, tipo="texto", mensaje=prompt, func_guardado_data=guardar_info_mensaje_enviado, formato="markdown")
        editar_mensaje_texto(chat_id=chat_id, message_id= conversaciones[chat_id]["id_callback"], nuevo_texto=prompt, formato="markdown",guardar_datos=guardar_info_mensaje_enviado)
        return ""

     # — FLUJO DE RECEPCIÓN DE NUEVO VALOR —
    if estado_actual == ESTADO_EDITAR_VALOR:
        datos = conversaciones[chat_id]["datos"]
        record_id = datos["record_id"]
        campo    = datos["campo_sel"]
        raw      = texto.strip()

        # Mapear campo a columna en BD y convertir valor
        col_val_mapping = {
            "campo_nombre_tarea":    ("nombre_tarea", raw),
            "campo_descripcion":     ("descripcion", raw),
            "campo_fecha_hora":      ("fecha_hora",
                                      utilidades.convertir_a_iso_utc(raw, datos)),
            "campo_repetir":         ("repetir", raw.lower() in ["si","s","yes","y"]),
            "campo_intervalo":       ("intervalo_repeticion", raw),
            "campo_aviso_constante": ("aviso_constante", raw.lower() in ["si","s","yes","y"]),
            "campo_repeticion_intervalo_confirmar_previo": ("confirmar", raw.lower() in ["si","s","yes","y"])
        }
        col, val = col_val_mapping.get(campo, (None, None))
        
        if not col:
            enviar_telegram(chat_id, tipo="texto", mensaje="Error de campo. Intenta de nuevo.",func_guardado_data=guardar_info_mensaje_enviado)
            return ""

        nombre_tarea = conversaciones[chat_id].get('datos', {}).get('record_data',{}).get('nombre_tarea', "")
        # — ACTUALIZAR CON FUNCIÓN CENTRALIZADA —
        if campo == "campo_repetir":
            try:

                exito = actualizar_campos_recordatorio(record_id, {col: val})
                
                if exito and val:
                    intervalo_repeticion = conversaciones[chat_id].get('datos', {}).get('record_data',{}).get('intervalo_repeticion', "")
                    intervalos = conversaciones[chat_id].get('datos', {}).get('record_data',{}).get('intervalos', 0)

                    if intervalo_repeticion!="":
                        conversaciones[chat_id]["datos"]["campo_sel"] = "campo_repeticion_intervalo_confirmar_previo"
                        msg_intervalo_confirmacion = f"*cada* {intervalos} {significado_tiempo(intervalo_repeticion, (intervalos > 1))}"
                        enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=plantillas.MSG.EDITAR_CAMPO_REPETICION_EDITAR_INTERVALO_PREVIO(intervalo=msg_intervalo_confirmacion),func_guardado_data=guardar_info_mensaje_enviado, formato="markdown")
                    else:
                        conversaciones[chat_id]["datos"]["campo_sel"] = "campo_intervalo"
                        enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=plantillas.MSG.EDITAR_CAMPO_REPETICION_EDITAR_INTERVALO_NUEVO(nombre_recordatorio=nombre_tarea),func_guardado_data=guardar_info_mensaje_enviado)
                    
                    return ""

            except Exception as e:
                print(f"Error al editar campo_repetir con el usuario {chat_id}: {str(e)}")
                return f"Error al editar el campo de repetición del recordatorio"
        elif campo=="campo_repeticion_intervalo_confirmar_previo":
            if not val:
                conversaciones[chat_id]["datos"]["campo_sel"] = "campo_intervalo"
                enviar_telegram(chat_id=chat_id, tipo="texto", mensaje=plantillas.MSG.EDITAR_CAMPO_REPETICION_EDITAR_INTERVALO_NUEVO(nombre_recordatorio=nombre_tarea),func_guardado_data=guardar_info_mensaje_enviado)
                return ""
            else:
                exito=True
        elif campo=="campo_intervalo":
            try:
                    datos = utilidades.extraer_numero_intervalo(texto)
                    if datos:
                        numero, intervalo = datos["numero"], datos["intervalo"]
                        conversaciones[chat_id]["datos"]["intervalos"] = numero
                        conversaciones[chat_id]["datos"]["intervalo_repeticion"] = intervalo
                        # Pasar al estado de aviso constante
                        exito = actualizar_campos_recordatorio(recordatorio_id=record_id,campos= {"intervalos": numero, "intervalo_repeticion": intervalo})
                    else:
                        print("Errores en la actualización de los campos de repeticion de intervalo")
                        return "Error, sintaxis incorrecta, escribe el intervalo como por ejemplo 1:d (simbolos: s=segundos, x=minutos, h=horas, d=dias, m=meses, a=años)"        
            except Exception as e:
                print("Errores en la actualización de los campos de repeticion de intervalo: ", str(e))
                return "Error, sintaxis incorrecta, escribe el intervalo como por ejemplo 1:d (simbolos: s=segundos, x=minutos, h=horas, d=dias, m=meses, a=años)"
        elif campo == "campo_fecha_hora":
            # Comprobación de que la fecha y hora sea mayor que la actual
            try:
                
                fecha_hora = utilidades.normalizar_fecha_a_datetime(raw)
                fecha_hora_utc = utilidades.normalizar_fecha_a_datetime(raw, zona_horaria_local= conversaciones[chat_id]["datos"]["zona_horaria"])
                if not fecha_hora_utc or not fecha_hora:
                    raise ValueError(f"No se pudo interpretar la fecha: '{raw}'")
                # Comprobar si la hora y fecha elegida son mayores a las actuales
                fecha_hora_utc_servidor = utilidades.hora_utc_servidor_segun_zona_host()
                if fecha_hora_utc_servidor < fecha_hora_utc: # Es importante que la fecha del recordatorio sea estrictamente mayor
                    conversaciones[chat_id]["datos"]["fecha_hora"] = fecha_hora_utc.isoformat()
                    conversaciones[chat_id]["datos"]["fecha_hora_local"] = fecha_hora.isoformat()
                    exito = actualizar_campos_recordatorio(record_id, {
                                                            col: conversaciones[chat_id]["datos"]["fecha_hora"],
                                                            "notificado": False,
                                                            "aviso_detenido": False
                                                            })
                else:
                    # La fecha y hora del recordatorio es pasada o actual.
                    return ("Lo siento, la fecha y hora para el recordatorio debe ser en el futuro. Por favor, elige una fecha y hora posterior a la actual.\n"
                            "Por ejemplo: " + utilidades.sumar_hora_servidor(zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],minutos=10).strftime("%d/%m/%Y %I:%M %p")) 
            except ValueError:
                # Este mensaje se mantiene para cuando el formato de fecha es incorrecto
                return ("Lo siento, no pude entender el formato de fecha y hora. Puedes usar formatos como `DD/MM/YYYY 4:00 PM` o `16:00`.\n"
                        "Por ejemplo: " + utilidades.sumar_hora_servidor(zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],minutos=10).strftime("%d/%m/%Y %I:%M %p")) 
        else:
            exito = actualizar_campos_recordatorio(record_id, {col: val})

        if exito:
            enviar_telegram(chat_id, tipo="texto", mensaje="✅ Recordatorio actualizado correctamente.",func_guardado_data=guardar_info_mensaje_enviado)
        else:
            enviar_telegram(chat_id, tipo="texto", mensaje="❌ No se pudo actualizar. Intenta más tarde.", func_guardado_data=guardar_info_mensaje_enviado)

        guardar_estado(chat_id=chat_id, estado="")

        del conversaciones[chat_id]
        return ""
    
    if estado_actual == ESTADO_NOMBRE_TAREA:
        conversaciones[chat_id]["datos"]["nombre_tarea"] = texto
        guardar_estado(chat_id=chat_id,estado= ESTADO_DESCRIPCION_TAREA) 
        return "¡Entendido! Ahora, por favor escribe una breve descripción de la tarea."
    
    elif estado_actual == ESTADO_DESCRIPCION_TAREA:
        conversaciones[chat_id]["datos"]["descripcion"] = texto
        datos_chat_db = supabase_db.obtener_info_chat(chat_id=chat_id)

        if datos_chat_db:
            # Revisar si tiene la zona horaria y si no pedirsela al usuario
            if not conversaciones[chat_id]["datos"]["zona_horaria"]:
                guardar_estado(chat_id=chat_id,estado= ESTADO_ZONA_HORARIA)  
                pedir_zona_horaria(chat_id=chat_id)
                return ""
        else:
            enviar_telegram(tester_chat_id,tipo="texto",mensaje="ATENCIÓN, NO SE ESTA GUARDANDO INFO DEL CHAT_ID " + chat_id, formato="", func_guardado_data=guardar_info_mensaje_enviado)
            
        guardar_estado(chat_id=chat_id,estado= ESTADO_FECHA_HORA)
        return ("¿Cuándo necesitas que te recuerde esta tarea? Por favor, indica la fecha y hora (Ej: `25/12/2026 4:00 pm`).\n"
                "Por ejemplo: " +  utilidades.sumar_hora_servidor(zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],minutos=10).strftime("%d/%m/%Y %I:%M %p")) 
    
    elif estado_actual == ESTADO_ZONA_HORARIA:
        if texto in ZONAS_HORARIAS:
            conversaciones[chat_id]["datos"]["zona_horaria"] = texto
            guardar_estado(chat_id=chat_id,estado= ESTADO_ZONA_HORARIA_CONFIRMAR)
            return generar_mensaje_confirmacion_zona_horaria(chat_id=chat_id)
        else:
            pedir_zona_horaria(chat_id=chat_id)
            return ""

    elif estado_actual == ESTADO_ZONA_HORARIA_CONFIRMAR:
        if texto.lower() in ["si", "yes", "y", "s", "zona_confirmar"]:

            # Si venimos de nuestro flujo especial...
            if conversaciones[chat_id]["datos"].get("accion_post_zona") == "actualizar_recordatorios":
                # 1) Guardar la zona en Supabase
                supabase_db.guardar_zona_horaria_chat(chat_id=chat_id,zona_horaria= conversaciones[chat_id]["datos"]["zona_horaria"], nombre_chat=nombre_usuario, tipo=tipo)
                # 2) Ejecutar la conversión de todos sus recordatorios
                actualizado = supabase_db.actualizar_recordatorios_por_chat(chat_id)
                # 3) Notificar al usuario
                msg = "✅ Todos tus recordatorios han sido reconvertidos a UTC." \
                    if actualizado else "ℹ️ No había recordatorios pendientes de conversión."
                enviar_telegram(chat_id, tipo="texto", mensaje=msg, func_guardado_data=guardar_info_mensaje_enviado)
                # 4) Limpiar el flujo
                del conversaciones[chat_id]
                return msg
            

            # si no era ese flujo, continuar normalmente…
            guardar_estado(chat_id=chat_id,estado= ESTADO_FECHA_HORA, guardar_zona_horaria=True)
            return ("¿Cuándo necesitas que te recuerde esta tarea? Por favor, indica la fecha y hora "
                    "(Ej: `25/12/2026 4:00 pm` o `16:00`).\n"
                    "Por ejemplo: " + utilidades.sumar_hora_servidor(zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],minutos=10).strftime("%d/%m/%Y %I:%M %p")) 

        else:
            # usuario quiere cambiarla
            guardar_estado(chat_id=chat_id,estado= ESTADO_ZONA_HORARIA)
            return pedir_zona_horaria(chat_id)
        
    elif estado_actual == ESTADO_FECHA_HORA:
            
            # Intentar parsear la fecha y hora y convertirla a UTC desde la fecha y hora local que se nos proporciono
            try:
                fecha_hora = utilidades.normalizar_fecha_a_datetime(texto)
                fecha_hora_utc = utilidades.normalizar_fecha_a_datetime(texto, zona_horaria_local= conversaciones[chat_id]["datos"]["zona_horaria"])
                if not fecha_hora_utc or not fecha_hora:
                    raise ValueError(f"No se pudo interpretar la fecha: '{texto}'")
                
                # Comprobar si la hora y fecha elegida son mayores a las actuales
                fecha_hora_utc_servidor = utilidades.hora_utc_servidor_segun_zona_host()
                if fecha_hora_utc_servidor < fecha_hora_utc: # Es importante que la fecha del recordatorio sea estrictamente mayor
                    conversaciones[chat_id]["datos"]["fecha_hora"] = fecha_hora_utc.isoformat()
                    conversaciones[chat_id]["datos"]["fecha_hora_local"] = fecha_hora.isoformat()
                else:
                    return ("Lo siento, la fecha y hora para el recordatorio debe ser en el futuro. Por favor, elige una fecha y hora posterior a la actual.\n"
                            "Por ejemplo: " + utilidades.sumar_hora_servidor(zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],minutos=10).strftime("%d/%m/%Y %I:%M %p")) 

            except ValueError:
                # Este mensaje se mantiene para cuando el formato de fecha es incorrecto
                return ("Lo siento, no pude entender el formato de fecha y hora. Puedes usar formatos como `DD/MM/YYYY 4:00 PM` o `16:00`.\n"
                        "Por ejemplo: " + utilidades.sumar_hora_servidor(zona_horaria=conversaciones[chat_id]["datos"]["zona_horaria"],minutos=10).strftime("%d/%m/%Y %I:%M %p")) 
            
            # Pasar al estado de confirmación
            guardar_estado(chat_id=chat_id,estado= ESTADO_REPETIR)
            return generar_mensaje_repetir(chat_id)
    elif estado_actual == ESTADO_REPETIR:
        
        if texto.lower() in ["sí", "si", "s", "yes", "y", "confirmar"]:

            conversaciones[chat_id]["datos"]["repetir"] = "si"
            guardar_estado(chat_id=chat_id,estado= ESTADO_INTERVALO_REPETICION)
            return generar_mensaje_intervalo_repeticion(chat_id)

        elif texto.lower() in ["no", "n", "cancelar"]:
            conversaciones[chat_id]["datos"]["repetir"] = "no"
            guardar_estado(chat_id=chat_id,estado= ESTADO_AVISO_CONSTANTE)
            return generar_mensaje_aviso_constante(chat_id)
        else:
            return "Disculpa, no entendi tu respuesta, ¿puedes volver a escribirla?"

    elif estado_actual == ESTADO_INTERVALO_REPETICION:
        realizado, msg = comprobacion_asignacion_fecha_hora(chat_id=chat_id, raw=texto)
        return msg
    elif estado_actual == ESTADO_AVISO_CONSTANTE:
        if texto.lower() in ["sí", "si", "s", "yes", "y", "confirmar"]:
            conversaciones[chat_id]["datos"]["aviso_constante"] = True
        else:
            conversaciones[chat_id]["datos"]["aviso_constante"] = False

        # Pasar al estado de confirmación
        guardar_estado(chat_id=chat_id,estado= ESTADO_CONFIRMAR)  
        generar_mensaje_confirmacion(chat_id)
        return ""
    elif estado_actual == ESTADO_CONFIRMAR:
        msg=""
        si = ["sí", "si", "s", "yes", "y", "confirmar"]
        no = ["no", "n", "cancelar"]
        if texto.lower() in si:
            # Guardar el recordatorio
            datos = conversaciones[chat_id]["datos"]
            resultado = guardar_recordatorio(chat_id, datos)
            
                        
            if resultado:
                generar_mensaje_registro_recordatorio(chat_id)
            else:
                generar_mensaje_error_registro_recordatorio(chat_id)
                
                enviar_telegram(tester_chat_id,tipo="texto",mensaje="ATENCIÓN, NO SE ESTA GUARDANDO RECORDATORIO DEL CHAT_ID " + chat_id, formato="", func_guardado_data=guardar_info_mensaje_enviado)

            guardar_estado(chat_id=chat_id, estado="")
            # Limpiar la conversación
            del conversaciones[chat_id]
        elif texto.lower() in no:
            # Cancelar el recordatorio
            guardar_estado(chat_id=chat_id, estado="")
            msg = generar_mensaje_cancelacion(chat_id=chat_id)
            del conversaciones[chat_id]
            
        else:
            msg = generar_mensaje_confirmacion(chat_id=chat_id)
        
        return msg
    # elif estado_actual == ESTADO_MOSTRAR_INFO_RECORDATORIO:
    if es_callback:
        return ""
    else:
        return "Lo siento, no entendí tu mensaje. ¿En qué puedo ayudarte?"

def generar_mensaje_registro_recordatorio(chat_id):
    mensaje = "*¡Tu recordatorio ha sido guardado exitosamente!* Te avisaré cuando sea el momento."
    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
            chat_id=chat_id,
            tipo="texto",
            mensaje= mensaje,
            formato= "markdown"
        )
    else:
        editar_mensaje_texto(
            chat_id=chat_id,
            message_id=conversaciones[chat_id]["id_callback"],
            nuevo_texto= mensaje,
            formato="markdown"
        )
    return ""

def generar_mensaje_error_registro_recordatorio(chat_id):
    mensaje = "Lo siento, hubo un problema al guardar tu recordatorio. Por favor, intenta nuevamente."
    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
            chat_id=chat_id,
            tipo="texto",
            mensaje= mensaje,
            formato= "markdown"
        )
    else:
        editar_mensaje_texto(
            chat_id=chat_id,
            message_id=conversaciones[chat_id]["id_callback"],
            nuevo_texto= mensaje,
            formato="markdown"
        )
    return ""

def generar_mensaje_cancelacion(chat_id):
    mensaje = "He cancelado la creación del recordatorio. ¿En qué más puedo ayudarte?"
    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
            chat_id=chat_id,
            tipo="texto",
            mensaje= mensaje,
            formato= "markdown"
        )
    else:
        editar_mensaje_texto(
            chat_id=chat_id,
            message_id=conversaciones[chat_id]["id_callback"],
            nuevo_texto= mensaje,
            formato="markdown"
        )
    return ""

def generar_mensaje_reiterativo_confirmacion(chat_id):
    mensaje = "Por favor confirma con 'sí' o 'no' si los datos son correctos."
    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
            chat_id=chat_id,
            tipo="texto",
            mensaje= mensaje,
            formato= "markdown"
        )
    else:
        editar_mensaje_texto(
            chat_id=chat_id,
            message_id=conversaciones[chat_id]["id_callback"],
            nuevo_texto= mensaje,
            formato="markdown"
        )
    return ""

def generar_mensaje_repetir(chat_id):
    conversaciones[chat_id]["wait_callback"] = True
    enviar_telegram(
    chat_id=chat_id,
    tipo="botones",
    mensaje="*¿Deseas repetir la tarea?*",
    botones=[{"texto": "Sí", "data": "si"}, {"texto": "No", "data": "no"}],
    formato="markdown"
    )

    return ""

def significado_tiempo(simbolo, plural =False):
    if plural:
        significados = {"s":"segundos", "x" : "minutos", "h":"horas", "d":"dias", "w":"semanas", "m":"meses", "a":"años"}
    else:
        significados = {"s":"segundo", "x" : "minuto", "h":"hora", "d":"dia", "w":"semana", "m":"mes", "a":"año"}
    
    return significados.get(simbolo)

def generar_mensaje_confirmacion(chat_id):
    """Genera un mensaje de confirmación con los datos del recordatorio"""
    datos = conversaciones[chat_id]["datos"]
    mensaje = "Por favor confirma los detalles de tu recordatorio:\n\n"

    mensaje += f"📝 *Tarea:* {datos['nombre_tarea']}\n"
    mensaje += f"📋 *Descripción:* {datos['descripcion']}\n"
    mensaje += f"📢 *Aviso constante* {'Sí' if datos['aviso_constante'] else 'No'}\n"
    mensaje += f"📢 *Repetir:* {datos['repetir']}\n"
    if datos['repetir'] =="si":
        try:
            intervalo_repeticion = datos['intervalo_repeticion']
            intervalos = datos['intervalos']
            mensaje += f"   *Cada* {intervalos} {significado_tiempo(intervalo_repeticion, (intervalos > 1))} \n"
        except Exception as e:
            print("Error en los intervalos de repeticion:", str(e))
        

    if datos.get("fecha_hora"):
        # Convertir ISO a objeto datetime y luego a formato legible
        try:
            dt = datetime.fromisoformat(datos.get("fecha_hora_local", datos["fecha_hora"]))
            fecha_formateada = dt.strftime("%d/%m/%Y a las %H:%M")
            mensaje += f"🕒 *Fecha y hora:* {fecha_formateada}\n"
        except:
            mensaje += f"🕒 *Fecha y hora:* {datos.get('fecha_hora', 'No especificada')}\n"
    else:
        mensaje += "🕒 *Fecha y hora:* No especificada\n"
    
    mensaje += "\n¿Son correctos estos datos? Responde 'sí' para confirmar o 'no' para cancelar."
    
    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
            chat_id=chat_id,
            tipo="texto",
            mensaje=mensaje,
            botones=[{"texto": "Sí", "data": "si"}, {"texto": "No", "data": "no"}],
            formato="markdown",
            func_guardado_data=guardar_info_mensaje_enviado
            )
    else:
        editar_mensaje_con_botones(
            chat_id=chat_id,
            message_id= conversaciones[chat_id]["id_callback"],
            nuevo_mensaje=mensaje,
            nuevos_botones=[{"texto": "Sí", "data": "si"}, {"texto": "No", "data": "no"}],
            formato="Markdown"
        )
    return ""

def mostrar_ayuda(nombre_usuario):
    """Muestra un mensaje de ayuda al usuario"""
    mensaje = f"¡Hola {nombre_usuario}! Soy ARV Reminder y te puedo ayudar a recordar tus tareas.\n\n"
    mensaje += "Puedes usar los siguientes comandos:\n"
    mensaje += "• /recordatorio - Crear un nuevo recordatorio\n"
    mensaje += "• /editar - Editar un recordatorio\n"
    mensaje += "• /pendientes - Ver tus recordatorios pendientes\n"
    mensaje += "• /recordatorios - Ver todos tus recordatorios registrados\n"
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
        
def modificar_mensajes_avisos_a_detenidos(chat_id):
    global conversaciones
    if "recordatorios_aviso_constante" in conversaciones[chat_id]:
        # Obtener ultimos recordatorios del servidor
        if not obtener_recordatorios_aviso_constante(chat_id=chat_id):
            return False
        recordatorios = conversaciones[chat_id]["recordatorios_aviso_constante"]
        for r in recordatorios:
            recordatorio = recordatorios[r]
            last_id_message = recordatorio["last_id_message"]
            # usuario = recordatorio["usuario"]
            nombre_tarea = recordatorio["nombre_tarea"]
            descripcion = recordatorio["descripcion"]
            texto = f'El recordatorio con el nombre de {nombre_tarea} y descripción "{descripcion}", ¡ha sido detenido exitosamente!'
            # print(f"Modificando aviso de {usuario} llamado '{nombre_tarea}': ")
            editar_mensaje_texto (chat_id=chat_id, message_id=last_id_message, 
                                  nuevo_texto= texto)
        # Todos los recordatorios avisados
        supabase_db.actualizar_estado_chat_id(chat_id=chat_id, numero_estado= CAMPO_GUARDADO_RECORDATORIO_AVISO_CONSTANTE, nuevo_valor="{}")
        conversaciones[chat_id]["recordatorios_aviso_constante"] = {}
            
# NUEVA FUNCIÓN PARA EJECUTAR EN SEGUNDO PLANO
def _detener_avisos_background(chat_id, message_id):
    """
    Esta función contiene la lógica lenta que se ejecutará en un hilo separado.
    """
    from supabase_db import cambiar_estado_aviso_detenido

    # 1. Actualiza la base de datos para detener futuros avisos
    exito = cambiar_estado_aviso_detenido(chat_id, True)

    if exito:
        # 2. Edita los mensajes que ya fueron enviados
        modificar_mensajes_avisos_a_detenidos(chat_id)
        # 3. Edita el mensaje de "Procesando..." para confirmar que todo terminó
        editar_mensaje_texto(chat_id, message_id, "✅ ¡Listo! Todos los avisos constantes han sido detenidos.")
    else:
        # Informa al usuario si algo salió mal
        editar_mensaje_texto(chat_id, message_id, "❌ Hubo un error al intentar detener los avisos.")


# FUNCIÓN PRINCIPAL MODIFICADA
def detener_avisos(chat_id):
    """
    Detiene los avisos del usuario de forma asíncrona.
    """
    # 1. Envía un mensaje inmediato para que el usuario sepa que recibimos la orden.
    #    Guardamos la respuesta para obtener el message_id y poder editarlo después.
    respuesta_inicial = enviar_telegram(chat_id, tipo="texto", mensaje="⌛ Deteniendo avisos, por favor espera...")
    
    if respuesta_inicial and respuesta_inicial.ok:
        try:
            message_id = respuesta_inicial.json()["result"]["message_id"]

            # 2. Crea y arranca el hilo para el trabajo pesado
            thread = threading.Thread(
                target=_detener_avisos_background,
                args=(chat_id, message_id)
            )
            thread.start()
        except (KeyError, ValueError) as e:
            print(f"Error al obtener message_id para detener avisos: {e}")
            return "Ocurrió un error al procesar tu solicitud."

    # 3. Retorna una cadena vacía para no enviar un segundo mensaje desde el flujo principal.
    return ""

def procesar_callback(chat_id, callback_data, nombre_usuario, tipo, id_callback):
    """Procesa los callbacks de los botones inline"""
    
    if chat_id in conversaciones:
        if conversaciones[chat_id].get("wait_callback", False):
            conversaciones[chat_id]["wait_callback"]=False
            return procesar_mensaje(chat_id=chat_id, texto=callback_data, nombre_usuario=nombre_usuario, es_callback=True,tipo=tipo, id_callback= id_callback)
        
    if callback_data == "nuevo_recordatorio":
        return iniciar_recordatorio(chat_id, nombre_usuario)
    elif callback_data == "ver_pendientes":
        # Aquí implementarás la lógica para mostrar recordatorios pendientes
        return "Esta función estará disponible próximamente."
    elif callback_data == "cancelar":
        if chat_id in conversaciones:
            del conversaciones[chat_id]
        return "Operación cancelada. ¿En qué más puedo ayudarte?"
    else: # Si no se encuentra entre opciones de callback se puede buscar como respuesta comun de mensaje de texto
        
        mensaje = procesar_mensaje(chat_id=chat_id, texto=callback_data, nombre_usuario=nombre_usuario, es_callback=True,tipo= tipo, id_callback= id_callback)
        
        if mensaje!="": # Si tiene respuesta se envia            
            return mensaje
        elif chat_id == tester_chat_id: # Si no y aparte el chat_id corresponde al tester entonces se le envia la información del nuevo comando callback que esta desarrollando
            enviar_telegram(f"DATO DE PRUEBA CALLBACK RETORNADO: {callback_data}")

        return ""
        
    # Si el mensaje es vacio de la sección else anterior entonces solo se le envia al usuario "Opción no reconicida"
    return "Opción no reconocida."

def pedir_zona_horaria(chat_id, actualizacion_recordatorios = False):
    """
    Se le pide al usuario que seleccione su zona horaria
    """
    conversaciones[chat_id]["wait_callback"] = True
    if actualizacion_recordatorios:
        mensaje ="Selecciona tu zona horaria para actualizar el horario de tus recordatorios:"
    else:
        mensaje = "Selecciona tu zona horaria:"
    botones = [{"texto": nombre, "data": zona} for zona, nombre in ZONAS_HORARIAS.items()]
    enviar_telegram(chat_id, tipo="botones", mensaje=mensaje, botones=botones)

def generar_mensaje_confirmacion_zona_horaria(chat_id):
    """
    Pide al usuario confirmar la zona horaria recién seleccionada.
    Se basa en el valor almacenado en conversaciones[chat_id]['datos']['zona_horaria'].
    """
    conversaciones[chat_id]["wait_callback"] = True
    zona = conversaciones[chat_id]["datos"]["zona_horaria"]
    nombre_zona = ZONAS_HORARIAS.get(zona, zona)
    mensaje = (
        f"Has seleccionado la zona horaria:\n\n"
        f"*{nombre_zona}*\n\n"
        "¿Es correcta?"
    )
    botones = [
        {"texto": "Sí, es correcta", "data": "zona_confirmar"},
        {"texto": "No, quiero cambiarla", "data": "zona_rechazar"}
    ]
    enviar_telegram(
        chat_id=chat_id,
        tipo="botones",
        mensaje=mensaje,
        botones=botones,
        formato="Markdown"
    )
    return ""

def generar_mensaje_intervalo_repeticion(chat_id):
    conversaciones[chat_id]["wait_callback"] = False
    mensaje = (
        "¿Con qué frecuencia deseas que se repita el recordatorio?\n"
        "Escribe el intervalo en el siguiente formato: `1:d o 1d`\n\n"
        "*Símbolos válidos:*\n"
        "`x` - minutos\n"
        "`h` - horas\n"
        "`d` - días\n"
        "`w` - semanas\n"
        "`m` - meses\n"
        "`a` - años\n\n"
        "*Ejemplo:* `2:h` o `2h` significa cada 2 horas"
    )

    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
                chat_id=chat_id,
                tipo="texto",
                mensaje= mensaje,
                formato= "markdown"
            )
    else:
        editar_mensaje_texto(chat_id=chat_id,
                             message_id=conversaciones[chat_id]["id_callback"],
                             nuevo_texto=mensaje,
                             formato="markdown"
                             )
    conversaciones[chat_id]["datos"]["last_id_message"] = None
    return ""

def generar_mensaje_aviso_constante(chat_id):
    conversaciones[chat_id]["wait_callback"] = True
    if not conversaciones[chat_id].get("id_callback", False):
        enviar_telegram(
            chat_id=chat_id,
            tipo="botones",
            mensaje=(
                "*¿Deseas que te avise de forma constante hasta que marques la tarea como completada?*\n\n"
                "Esto puede ayudarte a no olvidarla si no la realizas justo cuando se activa el recordatorio."
            ),
            botones=[{"texto": "Sí", "data": "si"}, {"texto": "No", "data": "no"}],
            formato="markdown",
            func_guardado_data=guardar_info_mensaje_enviado
        )
    else:
        editar_mensaje_con_botones(
                chat_id=chat_id,
                message_id=conversaciones[chat_id]["id_callback"],
                nuevo_mensaje=(
                    "*¿Deseas que te avise de forma constante hasta que marques la tarea como completada?*\n\n"
                    "Esto puede ayudarte a no olvidarla si no la realizas justo cuando se activa el recordatorio."
                ),
                nuevos_botones= [{"texto": "Sí", "data": "si"}, {"texto": "No", "data": "no"}],
                formato="markdown"
            )

    return ""

def pedir_zona_horaria_y_actualizar_recordatorios(chat_id, nombre_usuario):
    """
    Pide la zona horaria al usuario y luego actualiza sus recordatorios.
    Sólo envía la petición si han pasado 8h desde la última vez (basado en estado_1).
    """

    # Intentar leer el estado_1 del chat_id (último timestamp de solicitud de zona)
    estado_actual = supabase_db.leer_estado_chat_id(chat_id, numero_estado=CAMPO_GUARDADO_PETICION_ZONA_HORARIA)

    ahora = utilidades.hora_utc_servidor_segun_zona_host()

    try:
        if estado_actual:
            # Parsear fecha si existe
            ultima_fecha = datetime.fromisoformat(estado_actual)
            if (ahora - ultima_fecha) < timedelta(hours=8):
                # Si no ha pasado suficiente tiempo, no pedimos de nuevo
                return
    except Exception as e:
        print(f"⚠️ Error al procesar la fecha almacenada en estado_1: {e}")

    # Actualizamos estado_1 con la hora actual UTC
    supabase_db.actualizar_estado_chat_id(chat_id, numero_estado=CAMPO_GUARDADO_PETICION_ZONA_HORARIA, nuevo_valor=ahora.isoformat())

    # Registramos el chat (si no existe) en supabase
    supabase_db.upsert_chat_info(
        chat_id=chat_id,
        nombre=nombre_usuario,
        tipo="private"
    )

    # Iniciamos flujo de zona horaria
    conversaciones[chat_id] = {
        "estado": ESTADO_ZONA_HORARIA,
        "datos": {
            "usuario": nombre_usuario,
            "accion_post_zona": "actualizar_recordatorios"
        },
        "wait_callback": False
    }

    # Envío real de botones
    return pedir_zona_horaria(chat_id, actualizacion_recordatorios=True)


if __name__ == "__main__":
    chat_id = 4541
    conversaciones[chat_id]={
        "datos": {}
    }
    texto = "1h"
    comprobacion_asignacion_fecha_hora(chat_id=chat_id, raw=texto)