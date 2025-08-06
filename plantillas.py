class MSG:
    @staticmethod
    def EDITAR_CAMPO_REPETICION_EDITAR_INTERVALO_PREVIO(intervalo="", nombre_tarea=""):
        return f"Tienes el siguiente intervalo: {intervalo}, ¿lo quieres dejar igual?"
    
    @staticmethod
    def EDITAR_CAMPO_REPETICION_EDITAR_INTERVALO_NUEVO(nombre_recordatorio=""):
        return (f"¿Con qué frecuencia deseas que se repita el recordatorio '{nombre_recordatorio}'?\n"
                "Escribe el intervalo en el siguiente formato: `1:d o 1d`\n\n"
                "*Símbolos válidos:*\n"
                "`x` - minutos\n"
                "`h` - horas\n"
                "`d` - días\n"
                "`w` - semanas\n"
                "`m` - meses\n"
                "`a` - años\n\n"
                "*Ejemplo:* `2:h` o `2h` significa cada 2 horas")
