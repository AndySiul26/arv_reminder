# Guía de Despliegue - ARV Reminder Bot

Esta guía te ayudará a desplegar el bot en tu VPS usando Docker, ejecutándose en el puerto **5500** para evitar conflictos con EasyPanel.

## Prerrequisitos
- Acceso SSH al VPS.
- Docker y Docker Compose instalados.
- Repositorio actualizado en GitHub: `https://github.com/AndySiul26/arv_reminder`

## Paso 1: Preparar los Archivos Locales
Antes de conectarte al VPS, asegúrate de subir los archivos nuevos que creamos (`Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `.dockerignore`) a tu repositorio GitHub.

```bash
git add .
git commit -m "feat: Add Docker deployment support port 5500"
git push origin main
```

## Paso 2: Despliegue en el VPS

1.  **Conéctate por SSH**:
    ```bash
    ssh root@tu-ip-vps
    ```

2.  **Clona el repositorio** (o haz pull si ya existe):
    ```bash
    cd arv_reminder
    git pull origin main
    ```

3.  **Configura el archivo `.env`** (si no existe):
    ```bash
    nano .env
    ```
    (Asegúrate de tener las claves correctas y `LOCAL_MODE=false`)

4.  **IMPORTANTE: Crear archivo de base de datos**
    Para evitar errores con Docker, crea el archivo vacío antes de iniciar:
    ```bash
    touch local_backup.db
    ```
    *Nota: El bot sincronizará los datos desde Supabase automáticamente.*

5.  **Levanta el Contenedor**:
    ```bash
    docker compose down
    docker compose up -d --build
    ```
    
    Verifica que esté corriendo:
    ```bash
    docker logs arv_reminder_bot
    ```
    Deberías ver: `🌟 Starting Gunicorn Server on port 8443...`

## Paso 3: Configurar SSL y Dominio (El Proxy)

Dado que usas **EasyPanel** (que controla los puertos 80/443), **NO** podemos usar esos puertos directamente. Tienes dos opciones:

### Opción A: Usar EasyPanel como Proxy (Recomendado)
Configura EasyPanel para que reciba el tráfico de `arvreminder.virtualdigitalprint.com` y lo envíe a tu contenedor interno.

1.  Entra a EasyPanel.
2.  Crea una nueva **App** (o Servicio).
3.  Tipo: **Proxy** (o a veces llamado "Service" apuntando a IP interna).
4.  Dominio: `arvreminder.virtualdigitalprint.com`.
5.  Destino (Target): `http://localhost:5500` (o la IP privada del servidor:5500).
6.  EasyPanel manejará el certificado SSL automáticamente.

### Opción B: Si EasyPanel NO gestiona este dominio
Si prefieres que este dominio no pase por EasyPanel en absoluto, tendrías que usar un puerto diferente para HTTPS (ej: https://dominio:8443) lo cual es incómodo. **Recomiendo fuertemente la Opción A** para que EasyPanel gestione el SSL (Let's Encrypt) y enrute al puerto 5500.

## Verificación Final
1.  Visita `https://arvreminder.virtualdigitalprint.com/` (Debería responder el servidor, probablemente 404 si no hay ruta raíz, o 405).
2.  En Telegram, envía `/start` al bot. Si responde, ¡el Webhook y el despliegue fueron exitosos!
