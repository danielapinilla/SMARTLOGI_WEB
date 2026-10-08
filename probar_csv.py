import csv
from pathlib import Path

CARPETA = Path("data")

archivos = sorted(CARPETA.glob("*.csv"))

print("=" * 60)
print("        COMPROBACIÓN DE CSV - SMARTLOGI")
print("=" * 60)

for archivo in archivos:
    try:
        with open(archivo, "r", encoding="utf-8-sig", newline="") as f:
            lector = csv.reader(f)

            encabezados = next(lector)
            cantidad = sum(1 for _ in lector)

        print(f"\n📄 {archivo.name}")
        print(f"   Registros: {cantidad}")
        print(f"   Columnas: {encabezados}")

    except Exception as e:
        print(f"\n❌ Error en {archivo.name}: {e}")

print("\n" + "=" * 60)
print("Comprobación terminada.")
print("=" * 60)