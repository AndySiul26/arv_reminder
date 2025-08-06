from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import time
import requests
import webhook_utils
import dateparser

zona_servidor = os.environ.get("ZONA_SERVIDOR", "UTC")

def convertir_fecha_local_a_utc(fecha_local: datetime, zona_horaria: str) -> datetime:
    """
    Convierte un datetime naive que el usuario proporcionó, 
    asumiendo está en 'zona_horaria', a un datetime en UTC.

    Args:
      fecha_local: datetime sin tz, en la hora local del usuario.
      zona_horaria: string como 'America/Mexico_City'.

    Returns:
      datetime en UTC (tzinfo=ZoneInfo('UTC')).
    """
    try:
        tz = ZoneInfo(zona_horaria)
    except Exception:
        # si la zona no es válida, asumimos UTC directamente
        tz = ZoneInfo("UTC")

    # Asociar la zona al objeto naive
    dt_local = fecha_local.replace(tzinfo=tz)
    # Convertir a UTC
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))
    return dt_utc

def convertir_fecha_utc_a_local(fecha_utc: datetime, zona_horaria: str) -> datetime:
    """
    Convierte un datetime en UTC en la zona horaria local
    

    Args:
      fecha_utc: datetime sin tz, en la hora local del usuario.
      zona_horaria: string como 'America/Mexico_City'.

    Returns:
      datetime en UTC (tzinfo=ZoneInfo('UTC')).
    """
    try:
        tz = ZoneInfo("UTC")
    except Exception:
        # si la zona no es válida, asumimos zona_horaria directamente
        tz = ZoneInfo(zona_horaria)

    # Asociar la zona al objeto naive
    dt_utc = fecha_utc.replace(tzinfo=tz)
    # Convertir a zona local
    dt_local = dt_utc.astimezone(ZoneInfo(zona_horaria))
    return dt_local

def convertir_a_iso_utc(texto: str, datos: dict) -> str:
    """
    Toma un texto en formato "DD/MM/YYYY HH:MM" y, usando la zona horaria
    almacenada en datos["zona_horaria"], devuelve la fecha en ISO8601 UTC.
    
    Args:
      texto: cadena con fecha y hora, p.ej. "25/12/2025 14:30"
      datos: diccionario de la conversación que debe contener:
             datos["zona_horaria"] = identificador IANA, p.ej. "America/Mexico_City"
    
    Returns:
      ISO string en UTC, p.ej. "2025-12-25T20:30:00+00:00"
    """
    
    try:
      # 1) Parseo naive
      dt_local = datetime.strptime(texto, "%d/%m/%Y %H:%M")
    except Exception as e:
      print("Error en formato origen en convertir_a_iso_utc:", str(e))
      return ""
    
    try:
      # 2) Asociar zona horaria
      zona = datos.get("zona_horaria")
      tz = ZoneInfo(zona)
    except Exception as e:
      tz = ZoneInfo("UTC")
      print("Error en zona horaria en convertir_a_iso_utc:", str(e))
      
    dt_local = dt_local.replace(tzinfo=tz)
    
    # 3) Convertir a UTC
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))
    return dt_utc.isoformat()

def hora_utc_servidor_segun_zona_host()-> datetime:
    ahora = datetime.now()
    hora = convertir_fecha_local_a_utc(ahora, zona_servidor)
    return hora

def sumar_hora_servidor(zona_horaria,minutos=0, horas=0, dias=0, semanas=0)-> datetime:
  fh = hora_utc_servidor_segun_zona_host()

  fh_s = fh + timedelta(minutes=minutos)
  fh_s = fh_s + timedelta(hours=horas)
  fh_s = fh_s + timedelta(days=dias)
  fh_s = fh_s + timedelta(weeks=semanas)

  # Sumar 1 semana
  fh_l = convertir_fecha_utc_a_local(fecha_utc=fh_s, zona_horaria=zona_horaria)
  return fh_l

def extraer_numero_intervalo(raw):
    texto = raw.lower()
    unidades_tiempo_aceptadas = ["s", "x", "h", "d", "w", "m", "a"]
    
    # Caso 1: Si existe ":" en el texto
    if ":" in texto:
        num, intervalo = texto.split(":")
        if num.isdigit() and intervalo in unidades_tiempo_aceptadas:
            return {"numero": int(num), "intervalo": intervalo}
    
    # Caso 2: Si no existe ":" en el texto, comprobar desde el final
    else:
        for i, char in enumerate(reversed(texto)):
            if char in unidades_tiempo_aceptadas:
                intervalo = char
                num = texto[:-i-1]  # Todo lo que está a la izquierda del carácter
                if num.isdigit():
                    return {"numero": int(num), "intervalo": intervalo}
                break  # Si se encontró una unidad de tiempo, no seguir buscando
    
    # Si no se cumple ninguna condición
    return {}

def env_to_bool(env_var, true_values=['true', '1', 'yes']):
    valor = os.getenv(env_var, False)
    return valor in true_values
    
def lanzar_ngrok_cmd(puerto=5000):
    """
    Lanza ngrok en una nueva ventana de consola (cmd) visible.
    """
    comando = f'start cmd /k "ngrok http {puerto}"'
    os.system(comando)
    time.sleep(3)  # Le damos tiempo a que la consola arranque

def obtener_url_ngrok(reintentos=6, espera=3):
    """
    Intenta obtener la URL pública de ngrok haciendo polling a su API local.
    """
    regreso = None
    for _ in range(reintentos):
        try:
            resp = requests.get('http://127.0.0.1:4040/api/tunnels')
            data = resp.json()
            for tunel in data['tunnels']:
                if tunel['proto'] == 'https':
                    return tunel['public_url']
            regreso = data['tunnels'][0]['public_url'] if data['tunnels'] else None
            if not regreso:
                time.sleep(espera)

        except:
            time.sleep(espera)
    return None

def iniciar_ngrok_y_obtener_url(puerto=5000):
    """
    Función principal: lanza ngrok, obtiene la URL pública y la copia al portapapeles.
    """
    lanzar_ngrok_cmd(puerto)
    print("Esperando a que ngrok levante el túnel...")

    url = obtener_url_ngrok()

    if url:
        print(f"✔ URL pública de ngrok: {url}")
    else:
        print("❌ No se pudo obtener la URL pública de ngrok.")

    return url

def normalizar_fecha_a_datetime(texto_fecha: str, idioma='es', zona_horaria_local = "") -> datetime | None:
    """
    Parsea una fecha en texto y devuelve un objeto datetime normalizado (sin segundos y en formato 24h).

    :param texto_fecha: Fecha como texto (en casi cualquier formato).
    :param idioma: Idioma del texto (por defecto 'es' para español).
    :return: Objeto datetime con minutos (sin segundos) o None si no se pudo interpretar.
    """
    dt = dateparser.parse(texto_fecha, languages=[idioma])
    if dt:
        if zona_horaria_local!= "":
            # Elimina los segundos y microsegundos para coincidir con "%d/%m/%Y %H:%M"
            return convertir_fecha_local_a_utc(dt.replace(second=0, microsecond=0), zona_horaria=zona_horaria_local)
        else:
            # Elimina los segundos y microsegundos para coincidir con "%d/%m/%Y %H:%M"
            return dt.replace(second=0, microsecond=0)

    return None

def set_webhook_local_with_ngrok():
    url = iniciar_ngrok_y_obtener_url()
    if webhook_utils.set_webhook(url):
        print("Servidor ngrok corriendo y url webhook establecida...")
        return True
    else:
        print("Servidor ngrok fallo...")
        return False

def set_webhook_remoto():
    webhook_url= os.getenv("WEB_HOOK_URL_REMOTE")
    if webhook_utils.set_webhook(webhook_url):
        print("Servidor remoto corriendo y url webhook establecida...")
        return True
    else:
        print("Servidor remoto fallo al establecerse para telegram...")
        return False

if __name__ == "__main__":
    # print(hora_utc_servidor_segun_zona_host().isoformat())
    cual = 3
    match cual:
      case 1:
        # Ejemplo 1: Con ":"
        raw_con_punto_y_coma = "5:d"
        resultado_con_punto_y_coma = extraer_numero_intervalo(raw_con_punto_y_coma)
        print("Resultado con ':' :", resultado_con_punto_y_coma)

        # Ejemplo 2: Sin ":"
        raw_sin_punto_y_coma = "10h"
        resultado_sin_punto_y_coma = extraer_numero_intervalo(raw_sin_punto_y_coma)
        print("Resultado sin ':' :", resultado_sin_punto_y_coma)

        numero, intervalo = resultado_sin_punto_y_coma["numero"], resultado_sin_punto_y_coma["intervalo"]

        # Ejemplo 3: Formato Inválido
        raw_invalido = "abc"
        resultado_invalido = extraer_numero_intervalo(raw_invalido)
        print("Resultado con formato inválido :", resultado_invalido)

        if resultado_invalido:
            print("Es valido?")
        else:
            print("Es INVALIDO")
      case 2:
        print(set_webhook_remoto())
        # Ya tienes la URL pública disponible en la variable `url`
        time.sleep (6)
      case 3:
        fecha_hora = "25/06/2025 4:00 p.m."
        fh_utc_dt = normalizar_fecha_a_datetime(fecha_hora)
        if fh_utc_dt:
            fh_utc_str = fh_utc_dt.strftime("%d/%m/%Y a las %H:%M")
        print(fh_utc_str)