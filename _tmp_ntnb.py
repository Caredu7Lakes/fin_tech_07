import pandas as pd, requests, io, urllib3
urllib3.disable_warnings()   # silencia o aviso de SSL desligado

URL = ("https://www.tesourotransparente.gov.br/ckan/dataset/"
       "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
       "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv")

r = requests.get(URL, verify=False, timeout=120)
r.raise_for_status()
df = pd.read_csv(io.StringIO(r.text), sep=";", decimal=",", nrows=5)
print("COLUNAS:", df.columns.tolist())
print(df.head().to_string())