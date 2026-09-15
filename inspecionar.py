"""
Inspeção pontual da API de juros — rode UMA vez antes de confiar nos filtros.

Objetivo: descobrir os nomes EXATOS de colunas e valores, para não chutar
schema. Se algo divergir do esperado, ajuste as constantes CAMPO_* / SEGMENTO_PF
no topo de coleta_bcb.py.

Uso:  python inspecionar.py
"""

import requests
import pandas as pd

API = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/"
COL = "TaxasJurosDiariaPorInicioPeriodo"


def bcb(colecao, **p):
    p["$format"] = "json"
    r = requests.get(API + colecao, params=p, timeout=60)
    r.raise_for_status()
    return pd.DataFrame(r.json()["value"])


# 1. Todas as colunas disponíveis (uma linha, transposta para leitura fácil).
print("=== COLUNAS ===")
print(bcb(COL, **{"$top": 1}).T)

# 2. Valores distintos de Segmento — confirmar se é exatamente 'PESSOA FÍSICA'.
print("\n=== SEGMENTOS ===")
print(bcb(COL, **{"$select": "Segmento", "$top": 500})["Segmento"].unique())

# 3. Valores distintos de Modalidade — confirmar os termos IMOBILIÁRIO / VEÍCULOS.
print("\n=== MODALIDADES ===")
print(bcb(COL, **{"$select": "Modalidade", "$top": 500})["Modalidade"].unique())