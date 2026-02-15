
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: No se encontraron las credenciales de Supabase en las variables de entorno")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def limpiar_duplicados():
    print("🔍 Buscando recordatorios...")
    
    # 1. Obtener todos los recordatorios ordenados por fecha de creación (ascendente)
    # Paginar si es necesario, pero intentemos traer un chunk grande
    response = supabase.table("recordatorios").select("*").order("creado_en", desc=False).limit(3000).execute()
    recordatorios = response.data
    
    if not recordatorios:
        print("No se encontraron recordatorios.")
        return

    print(f"Total recordatorios encontrados: {len(recordatorios)}")
    
    # 2. Agrupar por clave única lógica
    # Clave: chat_id + nombre_tarea + fecha_hora (exacta) 
    # Si son repeticiones del mismo evento con el MISMO tiempo objetivo, son duplicados erróneos.
    grupos = {}
    
    for r in recordatorios:
        # Clave compuesta
        # Normalizar fecha_hora si es string
        clave = f"{r['chat_id']}_{r['nombre_tarea']}_{r['fecha_hora']}"
        
        if clave not in grupos:
            grupos[clave] = []
        grupos[clave].append(r)
        
    # 3. Identificar duplicados y eliminar
    eliminar_ids = []
    
    for clave, lista in grupos.items():
        if len(lista) > 1:
            print(f"⚠️ Detectado grupo duplicado: {clave} ({len(lista)} copias)")
            # Mantener el MÁS ANTIGUO (el primero de la lista, ya que ordenamos por creado_en ASC)
            original = lista[0]
            duplicados = lista[1:]
            
            for d in duplicados:
                eliminar_ids.append(d['id'])
                print(f"   -> Marcar para eliminar ID: {d['id']} (Creado: {d['creado_en']})")
                
    if not eliminar_ids:
        print("✅ No se encontraron duplicados exactos.")
        return

    print(f"\n🗑️ Eliminando {len(eliminar_ids)} registros duplicados...")
    
    # Eliminar en lotes para no saturar
    chunk_size = 100
    for i in range(0, len(eliminar_ids), chunk_size):
        chunk = eliminar_ids[i:i + chunk_size]
        try:
            supabase.table("recordatorios").delete().in_("id", chunk).execute()
            print(f"   ✅ Lote {i//chunk_size + 1} eliminado ({len(chunk)} registros).")
        except Exception as e:
            print(f"   ❌ Error eliminando lote: {e}")

    print("\n🎉 Limpieza completada.")

if __name__ == "__main__":
    limpiar_duplicados()
