#!/bin/bash
set -e

echo "🚀 Starting ARV Reminder Bot Container..."

# 1. Initialize Supabase Database
echo "📦 initializing database..."
python setup_supabase.py

# 2. Configure Telegram Webhook
# We use the WEBHOOK_URL environment variable properly
if [ -z "$WEBHOOK_URL" ]; then
    echo "⚠️ WARNING: WEBHOOK_URL is not set. Telegram webhook might not be configured."
else
    echo "🔗 Configuring Telegram Webhook to: $WEBHOOK_URL"
    # Assuming TELEGRAM_TOKEN is available in env
    curl -F "url=$WEBHOOK_URL" "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook"
    echo "" # New line for logs
fi

# 3. Start Gunicorn
# Bind to 0.0.0.0:5500 so it's accessible outside the container
echo "🌟 Starting Gunicorn Server on port 5500..."
exec gunicorn --bind 0.0.0.0:5500 --workers 1 --threads 8 app:app
