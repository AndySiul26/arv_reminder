-- Seguridad para una aplicación exclusivamente backend.
-- El bot del VPS usa service_role; anon/authenticated no deben acceder.

DO $security$
DECLARE
    tabla TEXT;
BEGIN
    FOREACH tabla IN ARRAY ARRAY[
        'recordatorios', 'chats_info', 'actualizaciones_info',
        'chats_avisados_actualizaciones', 'modo_tester', 'chats_id_estados',
        'reportes', 'cripto_premium_users', 'cripto_alertas',
        'cripto_fuerza_alertas'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tabla);
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM anon, authenticated',
            tabla
        );
        EXECUTE format(
            'GRANT ALL PRIVILEGES ON TABLE public.%I TO service_role', tabla
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS %I ON public.%I', 'Allow anon access', tabla
        );
    END LOOP;
END
$security$;

REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM anon, authenticated;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO service_role;

REVOKE EXECUTE ON FUNCTION public.exec_sql(TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.exec_sql(TEXT) TO service_role;
REVOKE EXECUTE ON FUNCTION public.reclamar_envio_recordatorio(
    BIGINT, TEXT, INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reclamar_envio_recordatorio(
    BIGINT, TEXT, INTEGER
) TO service_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

NOTIFY pgrst, 'reload schema';
