"""
fin_tech_07 — Estágio 1 do ML: detecção de anomalias (rotulador)
================================================================

Detecta SALTOS anômalos de um dia para o outro em cada série. Primeiro estágio
do pipeline: as anomalias servirão de rótulos para os estágios seguintes.

DIFERENÇA-CHAVE: cada série é lida no SEU histórico completo (não da base diária
unificada, que fica limitada ao tamanho do ranking). Assim o dólar (1995+),
a NTN-B (2010+) e a soja (2000+) são avaliados sobre milhares de dias, enquanto
o spread (~14 dias) participa desde já, marcado como "aquecendo".

Método: z-score sobre janela móvel adaptativa, aplicado à VARIAÇÃO diária.
  variação = valor de hoje − de ontem
  z = (variação_hoje − média da janela) / desvio-padrão da janela
  anomalia se |z| > LIMIAR

Parâmetros:
  JANELA_ALVO = 54   MIN_DIAS = 7   LIMIAR = 3.0

Saída: dados/anomalias.csv — (data, serie, variacao, z_score, aquecendo).
"""

import os
import pandas as pd

PASTA = "dados"
JANELA_ALVO = 54
MIN_DIAS    = 7
LIMIAR      = 3.0


def _spread_diario():
    """Spread de veículos por dia (max−min do ranking), do histórico do ranking."""
    csv = os.path.join(PASTA, "historico_ranking_veiculos.csv")
    if not os.path.exists(csv):
        return None
    h = pd.read_csv(csv, parse_dates=["InicioPeriodo"])
    s = (h.groupby("InicioPeriodo")["TaxaJurosAoAno"]
           .agg(lambda x: x.max() - x.min())
           .reset_index()
           .rename(columns={"InicioPeriodo": "data", "TaxaJurosAoAno": "valor"}))
    return s.sort_values("data").reset_index(drop=True)


def _ler_serie(nome, col_data, col_valor):
    """Lê uma série longa do seu CSV original -> DataFrame ['data','valor']."""
    csv = os.path.join(PASTA, f"{nome}.csv")
    if not os.path.exists(csv):
        return None
    df = pd.read_csv(csv, parse_dates=[col_data])
    if col_valor not in df.columns:          # coluna ausente -> deixa o chamador tentar outra
        return None
    return (df[[col_data, col_valor]]
            .rename(columns={col_data: "data", col_valor: "valor"})
            .dropna().sort_values("data").reset_index(drop=True))


def _detectar_serie(serie, nome):
    """Aplica z-score móvel adaptativo à variação diária de uma série."""
    if serie is None or len(serie) < MIN_DIAS + 1:
        return []
    variacao = serie["valor"].diff()
    achados = []
    for i in range(1, len(serie)):
        if pd.isna(variacao.iloc[i]):
            continue
        janela = variacao.iloc[max(1, i - JANELA_ALVO):i].dropna()
        if len(janela) < MIN_DIAS:
            continue
        mu, sigma = janela.mean(), janela.std()
        if sigma == 0 or pd.isna(sigma):
            continue
        z = (variacao.iloc[i] - mu) / sigma
        if abs(z) > LIMIAR:
            achados.append({
                "data": serie["data"].iloc[i],
                "serie": nome,
                "variacao": round(float(variacao.iloc[i]), 4),
                "z_score": round(float(z), 2),
                "aquecendo": len(janela) < JANELA_ALVO,
            })
    return achados


def detectar():
    """Roda a detecção em cada série no seu histórico completo."""
    fontes = {
        "spread_veiculos": _spread_diario(),
        "dolar":     _ler_serie("dolar", "dataHoraCotacao", "cotacaoVenda"),
        "ntnb_2035": _ler_serie("ntnb_2035", "data", "ntnb_2035"),
        "soja":      _ler_serie("soja_usd", "data",
                                "soja_usc_bushel"),   # nome novo da coluna
    }
    # soja: tolera CSV antigo com coluna 'soja_usd'
    if fontes["soja"] is None:
        fontes["soja"] = _ler_serie("soja_usd", "data", "soja_usd")

    achados = []
    for nome, serie in fontes.items():
        achados += _detectar_serie(serie, nome)

    anomalias = pd.DataFrame(achados)
    if not anomalias.empty:
        anomalias = anomalias.sort_values(["serie", "data"]).reset_index(drop=True)
    anomalias.to_csv(os.path.join(PASTA, "anomalias.csv"), index=False)
    return anomalias


if __name__ == "__main__":
    a = detectar()
    print(f"anomalias → {a.shape}")
    if not a.empty:
        # resumo por série + as 15 mais fortes
        print("\npor série:")
        print(a.groupby("serie").size().to_string())
        print("\nmaiores |z|:")
        print(a.reindex(a["z_score"].abs().sort_values(ascending=False).index)
                .head(15).to_string(index=False))
    else:
        print("(nenhuma anomalia)")