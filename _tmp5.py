import pandas as pd
from coleta_bcb import bcb_odata

d = bcb_odata("ConsultaUnificada", **{"$select": "Segmento", "$top": 1000})
print("valores de Segmento em ConsultaUnificada:")
print(d["Segmento"].unique())