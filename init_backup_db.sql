-- Esquema de backup (réplica de las tablas principales de Supabase)
-- Este archivo se ejecuta automáticamente al crear el contenedor de Postgres backup.

CREATE TABLE IF NOT EXISTS recordatorios (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL,
    usuario TEXT,
    nombre_tarea TEXT,
    descripcion TEXT,
    fecha_hora TIMESTAMPTZ,
    creado_en TIMESTAMPTZ DEFAULT NOW(),
    notificado BOOLEAN DEFAULT FALSE,
    es_formato_utc BOOLEAN DEFAULT TRUE,
    aviso_constante BOOLEAN DEFAULT FALSE,
    aviso_detenido BOOLEAN DEFAULT FALSE,
    repetir BOOLEAN DEFAULT FALSE,
    intervalo_repeticion TEXT,
    intervalos INTEGER DEFAULT 0,
    repeticion_creada BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS chats_info (
    id SERIAL PRIMARY KEY,
    chat_id TEXT UNIQUE NOT NULL,
    nombre TEXT,
    tipo TEXT,
    zona_horaria TEXT,
    creado_en TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chats_id_estados (
    id SERIAL PRIMARY KEY,
    chat_id TEXT UNIQUE NOT NULL,
    estado_1 TEXT,
    estado_2 TEXT,
    estado_3 TEXT,
    estado_4 TEXT,
    estado_5 TEXT
);

CREATE TABLE IF NOT EXISTS reportes (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL,
    usuario TEXT,
    descripcion TEXT,
    fecha_hora TIMESTAMPTZ DEFAULT NOW(),
    estado TEXT DEFAULT 'pendiente'
);

CREATE TABLE IF NOT EXISTS actualizaciones_info (
    id SERIAL PRIMARY KEY,
    titulo TEXT,
    descripcion TEXT,
    fecha_hora TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chats_avisados_actualizaciones (
    chat_id TEXT PRIMARY KEY,
    id_ultima_actualizacion INTEGER
);

-- Tabla de metadatos de backup
CREATE TABLE IF NOT EXISTS _backup_metadata (
    id SERIAL PRIMARY KEY,
    tabla TEXT UNIQUE NOT NULL,
    registros_copiados INTEGER DEFAULT 0,
    ultimo_backup TIMESTAMPTZ DEFAULT NOW()
);
