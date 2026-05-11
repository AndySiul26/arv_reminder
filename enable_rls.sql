-- ALERTA: Ejecuta este script en el Editor SQL de tu Dashboard de Supabase.
-- Esto habilitará RLS pero permitirá que el bot siga funcionando con su anon_key.

-- 1. Habilitar RLS en tablas principales
ALTER TABLE recordatorios ENABLE ROW LEVEL SECURITY;
ALTER TABLE chats_info ENABLE ROW LEVEL SECURITY;
ALTER TABLE actualizaciones_info ENABLE ROW LEVEL SECURITY;
ALTER TABLE chats_avisados_actualizaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE modo_tester ENABLE ROW LEVEL SECURITY;
ALTER TABLE chats_id_estados ENABLE ROW LEVEL SECURITY;
ALTER TABLE reportes ENABLE ROW LEVEL SECURITY;

-- 2. Crear políticas de ACCESO TOTAL para el rol 'anon'
-- Esto permite que el bot (usando la clave pública) siga leyendo/escribiendo sin restricciones.
-- La seguridad radica en que solo tú tienes la clave y el control del bot.

CREATE POLICY "Allow anon access" ON recordatorios FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon access" ON chats_info FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon access" ON actualizaciones_info FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon access" ON chats_avisados_actualizaciones FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon access" ON modo_tester FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon access" ON chats_id_estados FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon access" ON reportes FOR ALL TO anon USING (true) WITH CHECK (true);

-- Nota: El rol 'service_role' (usado por tus scripts admin) ignora RLS automáticamente,
-- así que no necesita políticas.
