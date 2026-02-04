#!/bin/bash
set -e

echo "🚀 Starting ARV Reminder Bot (Standalone SSL Mode)..."

# 1. Initialize Supabase Database
echo "📦 initializing database..."
python setup_supabase.py

# 2. SSL Certificate Generation (Self-Signed)
# Telegram REQUIRES the certificate to be sent if we use self-signed.
# We generate them in /tmp or app directory.
CERT_FILE="webhook_cert.pem"
KEY_FILE="webhook_pkey.pem"

if [ ! -f "$CERT_FILE" ]; then
    echo "🔐 Generating Self-Signed SSL Certificate..."
    # Important: The CN (Common Name) MUST match the domain in the webhook URL
    # We extract the domain from WEBHOOK_URL env var just to be safe, or assume the user provided one.
    # Simple extraction of host from URL:
    DOMAIN=$(echo "$WEBHOOK_URL" | awk -F/ '{print $3}' | awk -F: '{print $1}')
    
    echo "   Domain detected: $DOMAIN"
    
    openssl req -newkey rsa:2048 -sha256 -nodes -keyout "$KEY_FILE" -x509 -days 3650 \
        -out "$CERT_FILE" -subj "/C=MX/ST=State/L=City/O=Bot/CN=$DOMAIN"
        
    echo "   Certificates generated."
else
    echo "🔐 SSL Certificate found, skipping generation."
fi

# 3. Configure Telegram Webhook WITH Certificate
if [ -z "$WEBHOOK_URL" ]; then
    echo "⚠️ WARNING: WEBHOOK_URL is not set."
else
    echo "🔗 Configuring Telegram Webhook to: $WEBHOOK_URL"
    echo "   Uploading certificate: $CERT_FILE"
    
    # We MUST upload the @cert.pem file for self-signed to work
    curl -F "url=$WEBHOOK_URL" \
         -F "certificate=@$CERT_FILE" \
         "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook"
         
    echo "" # New line
fi

# 4. Start Gunicorn with SSL
# Bind to 0.0.0.0:8443 (Telegram-supported port)
echo "🌟 Starting Gunicorn Server on port 8443 (HTTPS)..."
exec gunicorn --bind 0.0.0.0:8443 \
              --workers 1 \
              --threads 8 \
              --certfile "$CERT_FILE" \
              --keyfile "$KEY_FILE" \
              app:app
