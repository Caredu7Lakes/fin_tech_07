import pandas as pd
from coleta_bcb import bcb_odata

# ConsultaUnificada: coleção diferente da mesma API taxaJuros
try:
    d = bcb_odata("ConsultaUnificada", **{"$top": 5})
    print("=== COLUNAS de ConsultaUnificada ===")
    print(d.columns.tolist())
    print("\n=== amostra ===")
    print(d.head().to_string())
except Exception as e:
    print("ConsultaUnificada falhou:", repr(e))