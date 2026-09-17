"""
fin_tech_07 — Estágio 2 do ML: previsão de tendência das taxas (Prophet)
========================================================================

Prevê a DIREÇÃO das taxas de crédito (imóvel e veículos) num horizonte de 3
meses e traduz em recomendação para dois públicos. NÃO promete número exato:
entrega tendência + banda de incerteza, e admite "indefinido" quando o sinal
não é claro.

Método:
  - Prophet por série (imóvel SGS 20772, veículos SGS 20749), série mensal.
  - Horizonte: 3 meses à frente.
  - Saída em TRÊS estados por "zona morta":
      * "alta"      -> previsão sobe E a banda inteira aponta pra cima E o
                       movimento é material (>= LIMIAR_PP)
      * "queda"     -> simétrico, pra baixo
      * "indefinido"-> a banda de confiança cruza zero, OU o movimento é
                       menor que o limiar (irrelevante para decisão)
  - Banda de incerteza (80%) sempre reportada — nunca um número seco.

Recomendação por público (mesmo sinal, invertido):
  - CONTRATANTE:      alta -> "financiar agora"     | queda -> "esperar"
  - QUEM TEM DÍVIDA:   queda -> "antecipar/portar"   | alta  -> "manter"
  (indefinido -> "sem sinal claro" para ambos)

Parâmetros:
  HORIZONTE_MESES = 3
  LIMIAR_PP = 0.3   # movimento mínimo (pontos percentuais) para virar recomendação
  INTERVALO = 0.80  # largura da banda de confiança do Prophet
"""

import os
import pandas as pd

PASTA = "dados"
HORIZONTE_MESES = 3
LIMIAR_PP = 0.3
INTERVALO = 0.80

# (arquivo CSV, coluna da taxa, rótulo)
SERIES = [
    ("serie_imobiliario", "imobiliario", "imóvel"),
    ("serie_veiculos",    "veiculos",    "veículos"),
]


def _prever_serie(csv, coluna, rotulo):
    """Roda Prophet numa série mensal e classifica a tendência em 3 estados."""
    from prophet import Prophet

    caminho = os.path.join(PASTA, f"{csv}.csv")
    if not os.path.exists(caminho):
        return {"serie": rotulo, "estado": "sem_dados"}

    df = pd.read_csv(caminho, parse_dates=["data"]).dropna()
    df = df.rename(columns={"data": "ds", coluna: "y"})[["ds", "y"]].sort_values("ds")
    if len(df) < 24:                          # menos de 2 anos: previsão não confiável
        return {"serie": rotulo, "estado": "historico_curto", "n": len(df)}

    m = Prophet(interval_width=INTERVALO, weekly_seasonality=False,
                daily_seasonality=False)
    m.fit(df)
    futuro = m.make_future_dataframe(periods=HORIZONTE_MESES, freq="MS")
    fc = m.predict(futuro).iloc[-1]           # ponto no fim do horizonte

    atual = float(df["y"].iloc[-1])
    prev  = float(fc["yhat"])
    lo, hi = float(fc["yhat_lower"]), float(fc["yhat_upper"])
    delta = prev - atual                      # variação prevista (p.p.)

    # zona morta: banda cruza zero OU movimento imaterial -> indefinido
    banda_sobe   = (lo - atual) > 0           # limite inferior já acima do atual
    banda_desce  = (hi - atual) < 0           # limite superior já abaixo do atual
    material     = abs(delta) >= LIMIAR_PP

    if material and banda_sobe:
        estado = "alta"
    elif material and banda_desce:
        estado = "queda"
    else:
        estado = "indefinido"

    return {
        "serie": rotulo,
        "estado": estado,
        "taxa_atual": round(atual, 2),
        "prev_3m": round(prev, 2),
        "delta_pp": round(delta, 2),
        "banda_pp": (round(lo - atual, 2), round(hi - atual, 2)),
        "contratante": {"alta": "financiar agora", "queda": "esperar"}.get(estado, "sem sinal claro"),
        "quem_tem_divida": {"queda": "antecipar/portar", "alta": "manter"}.get(estado, "sem sinal claro"),
    }


def prever():
    resultados = [_prever_serie(csv, col, rot) for csv, col, rot in SERIES]
    return resultados


if __name__ == "__main__":
    for r in prever():
        print("─" * 60)
        for k, v in r.items():
            print(f"{k:16}: {v}")