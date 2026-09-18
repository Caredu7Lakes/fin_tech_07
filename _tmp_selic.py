import requests

for desc, url in [
    ("padrao",        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json"),
    ("ultimos",       "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/5?formato=json"),
    ("com_datas",     "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial=01/01/2020&dataFinal=31/12/2020"),
    ("com_header",    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json"),
]:
    try:
        h = {"Accept":"application/json","User-Agent":"Mozilla/5.0"} if desc=="com_header" else {}
        r = requests.get(url, headers=h, timeout=30)
        print(f"{desc}: {r.status_code} | {r.text[:120]}")
    except Exception as e:
        print(f"{desc}: ERRO {e}")