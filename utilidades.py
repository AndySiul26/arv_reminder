from datetime import datetime
from zoneinfo import ZoneInfo
import os

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

if __name__ == "__main__":
    print(hora_utc_servidor_segun_zona_host().isoformat())