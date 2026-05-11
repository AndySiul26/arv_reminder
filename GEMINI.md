# Manual Operativo - ARV Reminder Bot (v2)

## 📌 1. Descripción del Proyecto
ARV Reminder Bot es un bot de Telegram diseñado para gestionar recordatorios de forma interactiva y confiable. Permite a los usuarios crear tareas con fechas/horas específicas, configurar repeticiones complejas (intervalos), gestionar zonas horarias, y ofrece una interfaz moderna basada en botones inline para la edición (incluyendo selección múltiple o *batch editing*).

El sistema utiliza **Supabase** como única fuente de verdad (Single Source of Truth) para la persistencia de datos, garantizando consistencia y evitando problemas de sincronización que existían en arquitecturas previas (donde convivían SQLite local y Supabase).

## 🏗️ 2. Arquitectura del Sistema

*   **Backend:** Aplicación Python construida con Flask (para el webhook y endpoints de control) y la API nativa de Telegram (vía `requests`).
*   **Base de Datos Principal:** Supabase (PostgreSQL). Alberga todas las tablas: `recordatorios`, `chats_info`, `actualizaciones_info`, etc. Cuenta con RLS (Row Level Security) habilitado para asegurar el acceso vía `anon_key` (bot) y `service_role_key` (scripts admin).
*   **Base de Datos de Respaldo:** SQLite local (`local_backup.db`). Se actualiza periódicamente mediante un script automatizado para tener copias de seguridad offline.
*   **Despliegue:** Dockerizado. Utiliza `docker-compose` para orquestar el contenedor principal, montando volúmenes para persistir backups locales.
*   **Comunicación con Telegram:** Vía **Webhooks**. El bot expone un endpoint (`/webhook`) que recibe las actualizaciones instantáneas de Telegram.
*   **Cron/Background Jobs:** El procesamiento de recordatorios, sincronización de backups y envíos de actualizaciones a los usuarios corren en hilos en segundo plano (Background Threads) instanciados al arrancar la app.

## 📂 3. Estructura de Archivos y Responsabilidades

### Núcleo de la Aplicación
*   **`app.py`:** El punto de entrada principal. Inicia el servidor Flask, configura el webhook de Telegram y arranca los hilos en segundo plano (workers).
    *   *Funciones clave:* `cerrar_aplicacion()` (libera recursos y detiene threads limpiamente), `Modo_Tester()` (activa/desactiva el modo de mantenimiento). Dependiendo si está en modo local o producción, gestiona ngrok o el webhook remoto.
*   **`routes.py`:** Define los endpoints HTTP de la aplicación Flask.
    *   *Funciones clave:* `webhook()` (escucha POST de Telegram), `send_update()` (endpoint protegido para disparar actualizaciones manuales).
*   **`services.py`:** Capa de comunicación directa con la API de Telegram.
    *   *Funciones clave:* `enviar_telegram()` (POST base a la API de Telegram), `enviar_mensaje_con_botones()` (1 botón por fila), `enviar_mensaje_con_grid()` y `editar_mensaje_con_grid()` (claves para la interfaz de Batch Editing, ordenan botones en columnas).
*   **`conversations.py`:** El corazón de la lógica de usuario. Implementa la **máquina de estados** en memoria (`conversaciones` dict) para manejar los flujos interactivos.
    *   *Funciones clave:* `procesar_mensaje()` (el enrutador principal que decide qué hacer según el estado del usuario), `_mostrar_batch_select()` (genera la paginación y grid interactivo), `_parsear_intervalo_raw()` (entiende formatos como '2h', '1:d', '30x'), y `guardar_estado()` (serializa y envía la sesión a Supabase).
*   **`reminders.py`:** Lógica de negocio (backend cron) instanciado como el hilo principal de procesamiento.
    *   *Funciones clave:* `AdministradorRecordatorios._ejecutar()` (bucle infinito usando `schedule`), `verificar_recordatorios()` (lee Supabase, compara fechas, y decide enviar), `_enviar_recordatorio()` (notifica vía `services.py` y, si es repetible, calcula el `timedelta` o `relativedelta` para crear el próximo y guardarlo en DB).
*   **`supabase_db.py`:** Capa de abstracción de base de datos. Todas las operaciones CRUD hacia Supabase pasan por aquí.
    *   *Funciones clave:* `@con_reintentos` (decorador crucial para evitar que caídas cortas de red tumben el bot), `actualizar_estado_chat_id()` (persistencia de sesión de chat), `obtener_recordatorios_pendientes()` (query filtrado).
*   **`utilidades.py`:** Funciones de ayuda (helpers) misceláneas.
    *   *Funciones clave:* `convertir_fecha_utc_a_local()`, `analizar_fecha_hora()`, `set_webhook_local_with_ngrok()`.

### Mantenimiento y Herramientas (Scripts Admin)
*   **`backup_db.py`:** Script vital que corre en background. Periódicamente consulta todas las tablas de Supabase y hace un espejo hacia el contenedor Postgres local (antes SQLite).
    *   *Funciones clave:* `backup_tabla()` (ejecuta un TRUNCATE local seguido de un INSERT de todos los datos descargados, utilizando `SAVEPOINT fila_save` por cada registro para asegurar que si un registro falla, la tabla completa no se corrompa).
*   **`gestionar_actualizaciones.py`:** Herramienta CLI interactiva para administradores. Permite leer `Actualizaciones.txt` e insertar el texto como una nueva versión en Supabase.
*   **`Actualizaciones.txt`:** Archivo de texto plano donde se redactan las *Release Notes* (notas de la versión) antes de ejecutarlas con el script anterior.
*   **`setup_supabase.py` / `init_backup_db.sql`:** Scripts para crear esquemas de tablas tanto en Supabase como en el SQLite local.

### Configuración y Despliegue
*   **`.env`:** Variables de entorno (Tokens de Telegram, Supabase URL, anon_key, service_role_key). **Asegurar que nunca se suba a Git.**
*   **`Dockerfile` y `docker-compose.yml`:** Definen el entorno contenedorizado. Construyen la imagen instalando `requirements.txt` y exponen el puerto 5000.
*   **`entrypoint.sh` / `start.sh`:** Scripts de inicio del contenedor para asegurar la correcta ejecución del servidor (ej. usando gunicorn o python puro).

## 🔄 4. Flujos Clave del Sistema

### 4.1. Recepción de Mensajes (Webhook Flow)
1. Telegram hace un POST a `/webhook`.
2. `routes.py` recibe el JSON y lo pasa a `webhook_utils.py` o directamente al procesador.
3. Se identifica si es un comando, texto plano o un `callback_query` (botón).
4. La información se envía a `procesar_mensaje` en `conversations.py`.
5. Se consulta o inicializa el estado del usuario en el diccionario en memoria.
6. Según el estado actual (`ESTADO_CREACION_NOMBRE`, `ESTADO_BATCH_SELECT`, etc.), se ejecuta la lógica y se responde vía `services.py`.

### 4.2. Edición en Lote (Batch Editing)
1. Usuario lanza `/editar`. `conversations.py` consulta Supabase y muestra un grid de botones interactivos (`_mostrar_batch_select`).
2. Usuario toca botones: Se disparan callbacks `sel:N`. El estado cambia añadiendo o quitando items de `batch_seleccionados` (que debe ser una **lista** en memoria para correcta serialización JSON).
3. Si selecciona 2+ items, aparece el menú de Batch Actions (`ESTADO_BATCH_ACCION`).
4. Acciones como "Desactivar repetición" actualizan múltiples filas en Supabase en un bucle cerrado y devuelven el resultado final.

### 4.3. Procesamiento de Recordatorios
1. El hilo en `app.py` ejecuta `verificar_recordatorios()` cada pocos segundos.
2. Consulta Supabase: `select * from recordatorios where notificado=false and fecha_hora <= UTC_ACTUAL`.
3. Por cada registro encontrado: Envía el mensaje de telegram usando `services.py`.
4. Si `repetir` es True, calcula la nueva fecha sumando el `intervalo_repeticion` y actualiza el registro en Supabase.
5. Si `repetir` es False, marca `notificado=True` en Supabase.

## 🛠️ 5. Mantenimiento y Procedimientos

*   **Aplicar una nueva actualización para usuarios:**
    1. Escribir las novedades en `Actualizaciones.txt`.
    2. Ejecutar `py gestionar_actualizaciones.py` y elegir la opción para insertar la nueva versión.
    3. El hilo en background se encargará de enviarlo paulatinamente a los usuarios.
*   **Verificar logs del contenedor:**
    ```bash
    docker compose logs -f bot
    ```
*   **Actualizar el bot en el VPS:**
    ```bash
    git pull origin main
    docker compose build
    docker compose up -d --force-recreate
    ```
*   **Seguridad:** Si el token de Supabase se ve comprometido, rota el **JWT Secret** desde el dashboard de Supabase (Settings -> API -> JWT Keys). Esto invalidará las claves actuales. Obtén las nuevas y colócalas en el `.env` (reinicia el contenedor).

## ⚠️ 6. Consideraciones Importantes (Lecciones Aprendidas)
*   **Serialización de Estado:** El estado del usuario se guarda en Supabase mediante un volcado JSON del diccionario `conversaciones[chat_id]["datos"]`. **Nunca uses tipos de datos no serializables** como `set()` o objetos `datetime` puros dentro de este diccionario; usa listas `[]` y strings en formato ISO.
*   **Doble Base de Datos (Deprecado):** Anteriormente se sincronizaba una SQLite local con Supabase de forma bidireccional, lo que generaba "recordatorios zombies" y envíos duplicados por *race conditions*. El sistema actual es *Cloud-first*. SQLite es **solo** un backup de solo lectura.
*   **Webhooks vs Polling:** Telegram no permite ambas cosas simultáneamente. Al levantar el Docker, el script asegura establecer el Webhook. Si corres pruebas locales (con `USE_NGROK_LOCAL=true`), el código registra temporalmente el túnel ngrok.

---
*(Este archivo se actualiza conforme la arquitectura o las dependencias del bot evolucionen).*
