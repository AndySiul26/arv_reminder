#!/bin/bash

# Iniciar el servidor con Gunicorn
echo "Iniciando ARV Reminder Bot..."

# Instalar dependencias si no están instaladas
pip install -r requirements.txt

# Verificar si existe la tabla en Supabase
python setup_supabase.py

# Configurar webhook de Telegram usando la URL de Glitch
PROJECT_NAME=$(echo "$PROJECT_DOMAIN" | tr - _)
WEBHOOK_URL="https://${PROJECT_DOMAIN}.glitch.me/webhook"
echo "Configurando webhook en: $WEBHOOK_URL"
curl -F "url=$WEBHOOK_URL" https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook

# Iniciar la aplicación con Gunicorn
# gunicorn --bind 0.0.0.0:3000 --workers 1 --threads 8 app:app

gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 app:app