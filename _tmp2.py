import pandas as pd
from coleta_bcb import bcb_odata

todas = []
for pagina in range(15):                      # até 15 mil linhas
    lote = bcb_odata("TaxasJurosDiariaPorInicioPeriodo",
                     **{"$select": "Modalidade", "$top": 1000, "$skip": pagina*1000})
    if lote.empty:
        break
    todas.append(lote)
    if len(lote) < 1000:
        break

df = pd.concat(todas, ignore_index=True)
mods = sorted(df["Modalidade"].unique())
print(f"total de linhas varridas: {len(df)}")
print(f"total de modalidades distintas: {len(mods)}\n")
imob = [m for m in mods if "MOBIL" in m.upper() or "IMÓ" in m.upper()]
print("=== IMOBILIÁRIO ===")
print("\n".join(imob) if imob else "(nenhuma — está em outra coleção)")