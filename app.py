# -*- coding: utf-8 -*-

import os
import atexit
import signal
from dotenv import load_dotenv
from flask import Flask
import utilidades

from supabase_db import inicializar_supabase, actualizar_modo_tester, leer_modo_tester
from reminders import iniciar_administrador, detener_administrador
from routes import routes  # nuestro nuevo módulo de rutas
import sys

MODO_TESTER = False

LOCAL_MODE: bool = utilidades.env_to_bool("LOCAL_MODE")

load_dotenv()

app = Flask(__name__)
app.register_blueprint(routes)

def Modo_Tester(valor:bool):
    actualizar_modo_tester(nuevo_valor=valor)

def cerrar_aplicacion():
    """Cierra correctamente los recursos al terminar la aplicación."""
    print("Cerrando aplicación...")
    detener_administrador()
    print("Recursos liberados")
    os._exit(0)

# Al arrancar la aplicación
inicializar_supabase()
iniciar_administrador()
# Registrar cierre limpio
atexit.register(cerrar_aplicacion)
signal.signal(signal.SIGINT, lambda s,f: cerrar_aplicacion())
signal.signal(signal.SIGTERM, lambda s,f: cerrar_aplicacion())

# Si deseas ejecutar con python app.py (descomenta):
if __name__ == "__main__" and LOCAL_MODE:
    USE_NGROK_LOCAL: bool = utilidades.env_to_bool("USE_NGROK_LOCAL")
    if USE_NGROK_LOCAL:
        if not utilidades.set_webhook_local_with_ngrok():
            print("❌ Falló la configuración del webhook local. Terminando el servidor.")
            sys.exit(1)
    Modo_Tester(MODO_TESTER)
    app.run(debug=True, use_reloader=False)
else:
    if not utilidades.set_webhook_remoto():
        print("❌ Falló la configuración del webhook remoto. Terminando el servidor.")
        sys.exit(1)

# IMPLEMENTAR ACTUALIZACION DE SERVIDORES CADA MINUTO PARA QUE LOS PROYECTOS NO SE DUERMAN
