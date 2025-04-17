# ARV Reminder Bot

Un bot de Telegram para la gestión de recordatorios construido con Flask y Supabase.

## Características

- Creación de recordatorios con nombre, descripción y fecha/hora
- Sistema automatizado de notificaciones
- Almacenamiento persistente en Supabase
- Interfaz conversacional a través de Telegram

## Estructura del Proyecto

```
proyecto-bot-reminder/
├── app.py                     # Aplicación principal de Flask
├── conversations.py           # Manejo de conversaciones con usuarios
├── reminders.py               # Sistema de verificación y envío de recordatorios
├── services.py                # Servicios para enviar mensajes a Telegram
├── setup_supabase.py          # Script para crear tablas en Supabase
├── supabase_db.py             # Interacción con la base de datos Supabase
└── webhook_utils.py           # Utilidades para configurar webhook
```

## Requisitos Previos

- Python 3.8+
- Una cuenta de Telegram y un bot creado mediante BotFather
- Una cuenta de Supabase con un proyecto creado

## Configuración

1. **Clonar el repositorio**:
   ```bash
   git clone https://github.com/tu-usuario/arv-reminder-bot.git
   cd arv-reminder-bot
   ```

2. **Crear un entorno virtual**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # En Windows: .venv\Scripts\activate
   ```

3. **Instalar dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno**:
   Crea un archivo `.env` basado en `.env.example` y completa con tus credenciales:
   ```
   TELEGRAM_TOKEN=tu_token_de_telegram
   SUPABASE_URL=https://tu-id-proyecto.supabase.co
   SUPABASE_KEY=tu_llave_de_supabase
   ```

5. **Configurar la base de datos**:
   ```bash
   python setup_supabase.py
   ```

## Despliegue Local

1. **Iniciar ngrok** (opcional, para desarrollo local):
   ```bash
   ngrok http 5000
   ```

2. **Configurar webhook**:
   ```bash
   python webhook_utils.py
   # Introduce la URL de ngrok o tu URL de despliegue cuando se solicite
   ```

3. **Iniciar la aplicación**:
   ```bash
   python app.py
   ```

## Despliegue en Glitch

1. Crear nuevo proyecto en Glitch
2. Subir los archivos del proyecto
3. Añadir las variables de entorno en el panel de Glitch
4. La aplicación se iniciará automáticamente con el archivo `start.sh`

## Uso

1. Inicia una conversación con tu bot en Telegram
2. Usa `/start` para recibir el mensaje de bienvenida
3. Usa `/recordatorio` para crear un nuevo recordatorio
4. Sigue las instrucciones del bot para completar la información

## Licencia

[MIT](LICENSE)