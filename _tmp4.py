import pandas as pd
from coleta_bcb import bcb_odata

todas = []
for pagina in range(30):                      # ConsultaUnificada pode ser grande
    lote = bcb_odata("ConsultaUnificada",
                     **{"$select": "Modalidade", "$top": 1000, "$skip": pagina*1000})
    if lote.empty:
        break
    todas.append(lote)
    if len(lote) < 1000:
        break

df = pd.concat(todas, ignore_index=True)
mods = sorted(df["Modalidade"].unique())
print(f"linhas varridas: {len(df)} | modalidades distintas: {len(mods)}\n")
imob = [m for m in mods if "MOBIL" in m.upper() or "IMÓ" in m.upper()]
print("=== IMOBILIÁRIO em ConsultaUnificada ===")
print("\n".join(imob) if imob else "(nenhuma)")