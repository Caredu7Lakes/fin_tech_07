"""
fin_tech_07 — Features macro para o modelo (NTN-B 2035 e soja)
==============================================================

Coleta duas séries que servirão de FEATURES para a fase de ML (anomalia →
previsão → classificação). Mantidas separadas do coleta_bcb.py para não inchá-lo.

  - NTN-B 2035 (Tesouro IPCA+, vencimento 2035): juro real de ~10 anos. Casa com
    o prazo do crédito imobiliário. Fonte: CSV do Tesouro Transparente (oficial).
  - Soja CBOT (ticker ZS=F): sinal de direção da cadeia do agro. UNIDADE:
    US¢/bushel (centavos de dólar por bushel) — NÃO é dólar cheio. Para
    direção de tendência, dólar ou real dão o mesmo sinal. Fonte: Yahoo (yfinance).

Ressalvas conhecidas:
  - O CSV do Tesouro (~14 MB) é baixado inteiro e filtrado localmente (não há
    endpoint por título). verify=False contorna o certificado self-signed do
    servidor .gov.br — aceitável para dado público de leitura.
  - yfinance é acesso não-oficial ao Yahoo; pode falhar sem aviso. Como é feature
    macro auxiliar, o risco é tolerável — as funções capturam falha e seguem.
"""

import io
import os
import pandas as pd
import requests
import urllib3

urllib3.disable_warnings()   # silencia aviso de SSL desligado (Tesouro)

PASTA = "dados"
os.makedirs(PASTA, exist_ok=True)

URL_TESOURO = ("https://www.tesourotransparente.gov.br/ckan/dataset/"
               "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
               "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv")

NTNB_TIPO = "Tesouro IPCA+"    # NTN-B Principal (sem juros semestrais)
NTNB_VENC = "2035"             # vencimento alvo (~10 anos)
SOJA_TICKER = "ZS=F"           # soja CBOT contínuo (Yahoo)


def _caminho(nome):
    return os.path.join(PASTA, f"{nome}.csv")


def carregar_ntnb():
    """
    Baixa o CSV do Tesouro, filtra NTN-B (IPCA+ puro) com vencimento 2035 e
    devolve DataFrame ['data', 'ntnb_2035'] (taxa real de venda, % a.a.).
    Retorna DataFrame vazio se a fonte falhar — não derruba o pipeline.
    """
    try:
        r = requests.get(URL_TESOURO, verify=False, timeout=180)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), sep=";", decimal=",")
    except Exception as e:
        print(f"[features] NTN-B: falha ao baixar/ler ({e}) — pulando.")
        return pd.DataFrame(columns=["data", "ntnb_2035"])

    eh_ntnb = df["Tipo Titulo"] == NTNB_TIPO
    venc    = df["Data Vencimento"].astype(str).str.endswith(NTNB_VENC)
    ntnb = df[eh_ntnb & venc].copy()
    if ntnb.empty:
        print("[features] NTN-B 2035: filtro vazio — confira Tipo/Vencimento.")
        return pd.DataFrame(columns=["data", "ntnb_2035"])

    ntnb["data"] = pd.to_datetime(ntnb["Data Base"], format="%d/%m/%Y")
    ntnb = (ntnb.rename(columns={"Taxa Venda Manha": "ntnb_2035"})
                [["data", "ntnb_2035"]]
                .dropna()
                .sort_values("data")
                .reset_index(drop=True))
    ntnb.to_csv(_caminho("ntnb_2035"), index=False)
    return ntnb


def carregar_soja():
    """
    Baixa a série diária da soja CBOT (ZS=F) via yfinance e devolve
    ['data', 'soja_usc_bushel'] (fechamento, em US¢/bushel — centavos de
    dólar por bushel, NÃO dólar cheio). Retorna vazio se a fonte falhar.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(SOJA_TICKER).history(period="max")
    except Exception as e:
        print(f"[features] Soja: falha no yfinance ({e}) — pulando.")
        return pd.DataFrame(columns=["data", "soja_usc_bushel"])

    if hist.empty:
        print("[features] Soja: yfinance retornou vazio — pulando.")
        return pd.DataFrame(columns=["data", "soja_usc_bushel"])

    soja = (hist.reset_index()[["Date", "Close"]]
                .rename(columns={"Date": "data", "Close": "soja_usc_bushel"}))
    soja["data"] = pd.to_datetime(soja["data"]).dt.tz_localize(None).dt.normalize()
    soja = soja.dropna().sort_values("data").reset_index(drop=True)
    # Aviso de unidade: a série está em US¢/bushel, não em dólar cheio.
    print("[features] Soja em US¢/bushel (centavos de dólar por bushel).")
    soja.to_csv(_caminho("soja_usd"), index=False)
    return soja


if __name__ == "__main__":
    n = carregar_ntnb()
    s = carregar_soja()
    print(f"ntnb_2035 → {n.shape}")
    print(f"soja_usd  → {s.shape}")