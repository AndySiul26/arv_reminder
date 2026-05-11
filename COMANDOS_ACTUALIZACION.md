# Comandos para Actualizar el Bot

A continuación, tienes los pasos exactos que debes seguir para subir los cambios (lista de pendientes paginada) a GitHub y luego descargarlos en tu VPS para reiniciar el bot.

## 1. En tu Computadora Local (Subir a GitHub)
Abre tu terminal donde tienes el proyecto (asegúrate de haber detenido el bot local si lo tenías corriendo) y ejecuta estos tres comandos:

```bash
git add .
git commit -m "feat: Add paginated list for pending reminders"
git push origin main
```

## 2. En tu Servidor VPS (Descargar y Reiniciar)
Conéctate por SSH a tu servidor y entra a la carpeta del proyecto. Luego, ejecuta estos comandos para descargar los cambios y reiniciar los contenedores de Docker:

```bash
# 1. Entrar a la carpeta
cd arv_reminder

# 2. Descargar los cambios de GitHub
git pull origin main

# 3. Reiniciar el bot construyendo la nueva imagen
docker compose up -d --build
```

¡Y listo! Con eso tu bot en producción ya tendrá los botones de navegación para los recordatorios pendientes.
