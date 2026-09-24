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
    repeticion_creada BOOLEAN DEFAULT FALSE,
    ultimo_envio_en TIMESTAMPTZ
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

CREATE TABLE IF NOT EXISTS cripto_premium_users (
    chat_id TEXT PRIMARY KEY,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMPTZ DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cripto_alertas (
    id BIGINT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    usuario TEXT,
    book TEXT NOT NULL,
    operador TEXT,
    precio_objetivo NUMERIC(38, 18),
    estado TEXT NOT NULL,
    una_vez BOOLEAN DEFAULT TRUE,
    precio_disparo NUMERIC(38, 18),
    disparada_en TIMESTAMPTZ,
    precio_min NUMERIC(38, 18),
    precio_max NUMERIC(38, 18),
    min_armada BOOLEAN DEFAULT TRUE,
    max_armada BOOLEAN DEFAULT TRUE,
    aviso_constante BOOLEAN DEFAULT FALSE,
    aviso_detenido BOOLEAN DEFAULT FALSE,
    rearme_porcentaje NUMERIC(8, 4),
    lado_disparado TEXT,
    ultima_notificacion_en TIMESTAMPTZ,
    fuente TEXT,
    fuente_actual TEXT,
    mercado_fuente TEXT,
    tipo_precio TEXT,
    fuente_candidata TEXT,
    lecturas_fuente_candidata INTEGER DEFAULT 0,
    fuente_cambio_en TIMESTAMPTZ,
    creado_en TIMESTAMPTZ DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cripto_fuerza_alertas (
    id BIGINT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    usuario TEXT,
    book TEXT NOT NULL,
    temporalidad TEXT NOT NULL,
    modo TEXT NOT NULL,
    umbral_pct NUMERIC(18, 8),
    cambio_min_pct NUMERIC(18, 8),
    cambio_max_pct NUMERIC(18, 8),
    cambio_referencia_pct NUMERIC(18, 8) NOT NULL,
    precio_referencia_inicial NUMERIC(38, 18) NOT NULL,
    aviso_constante BOOLEAN DEFAULT FALSE,
    aviso_detenido BOOLEAN DEFAULT FALSE,
    condicion_activa BOOLEAN DEFAULT FALSE,
    lado_activo TEXT,
    ultima_notificacion_en TIMESTAMPTZ,
    ultimo_cambio_pct NUMERIC(18, 8),
    ultima_fuerza_pct NUMERIC(18, 8),
    ultimo_precio NUMERIC(38, 18),
    ultima_consulta_en TIMESTAMPTZ,
    estado TEXT DEFAULT 'activa',
    fuente TEXT DEFAULT 'coinbase_exchange',
    creado_en TIMESTAMPTZ DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cripto_alertas_inteligentes (
    id BIGINT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    usuario TEXT,
    book TEXT NOT NULL,
    direccion TEXT NOT NULL,
    precio_objetivo NUMERIC(38, 18) NOT NULL,
    temporalidad TEXT NOT NULL,
    perfil TEXT NOT NULL,
    periodos_promedio INTEGER NOT NULL,
    perdida_promedio_pct NUMERIC(18, 8) NOT NULL,
    perdida_fuerza_pct NUMERIC(18, 8) NOT NULL,
    margen_precio_pct NUMERIC(18, 8) NOT NULL,
    actividad_ratio NUMERIC(18, 8) NOT NULL,
    confirmaciones_requeridas INTEGER DEFAULT 2,
    persistencia_requerida INTEGER DEFAULT 2,
    subtemporalidades JSONB DEFAULT '[]'::jsonb,
    reporte_calibracion JSONB DEFAULT '{}'::jsonb,
    estado TEXT DEFAULT 'esperando',
    condiciones_activas JSONB DEFAULT '{}'::jsonb,
    condiciones_silenciadas JSONB DEFAULT '{}'::jsonb,
    conteos_condiciones JSONB DEFAULT '{}'::jsonb,
    ultimas_notificaciones JSONB DEFAULT '{}'::jsonb,
    ultimo_precio NUMERIC(38, 18),
    ultima_fuerza_pct NUMERIC(18, 8),
    fuerza_promedio_pct NUMERIC(18, 8),
    fuerza_pico_pct NUMERIC(18, 8),
    ultima_consulta_en TIMESTAMPTZ,
    ultimo_mensaje_id BIGINT,
    fuente TEXT DEFAULT 'coinbase_exchange',
    creado_en TIMESTAMPTZ DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de metadatos de backup
CREATE TABLE IF NOT EXISTS _backup_metadata (
    id SERIAL PRIMARY KEY,
    tabla TEXT UNIQUE NOT NULL,
    registros_copiados INTEGER DEFAULT 0,
    ultimo_backup TIMESTAMPTZ DEFAULT NOW()
);
