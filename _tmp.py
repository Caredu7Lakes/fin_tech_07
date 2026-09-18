import pandas as pd
from coleta_bcb import bcb_odata

d = bcb_odata("TaxasJurosDiariaPorInicioPeriodo", **{"$select": "Modalidade", "$top": 1000})
todas = sorted(d["Modalidade"].unique())
print("=== TODAS AS MODALIDADES ===")
for m in todas:
    print(" -", m)
print("\n=== SÓ IMOBILIÁRIO ===")
imob = [m for m in todas if "MOBIL" in m.upper() or "IMÓ" in m.upper() or "IMO" in m.upper()]
print(imob if imob else "(nenhuma modalidade imobiliária nesta coleção)")