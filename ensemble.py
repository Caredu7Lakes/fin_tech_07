"""
fin_tech_07 — Estágio 3 do ML: ensemble de direção das taxas (Random Forest)
============================================================================

Prevê a DIREÇÃO da taxa de crédito 3 meses à frente (sobe / cai / indefinido)
a partir do estado macro do mês. Aprende com o passado para prever o futuro.

Desenho (decidido):
  - Modelo ÚNICO e UNIFICADO: imóvel e veículos empilhados no mesmo treino, com
    a coluna 'tipo_credito' distinguindo. Aproveita a proporcionalidade entre as
    duas taxas e dobra o número de amostras.
  - Frequência MENSAL (o alvo é mensal; frequência maior inflaria o dado).
  - Features: dólar, NTN-B 2035, soja (fim do mês), flag de anomalia no mês,
    nível da própria taxa, variação recente da taxa (3 meses), tipo de crédito.
  - Rótulo: direção da PRÓPRIA taxa nos 3 meses seguintes — sobe/cai se o
    movimento for material (|Δ| >= LIMIAR_PP), senão "indefinido".
  - Validação TEMPORAL: treina no passado, testa no futuro (sem embaralhar).
  - Comparado com um BASELINE trivial ("repetir a direção atual"): se o RF não
    superar o baseline, o resultado honesto é dizer isso.

Parâmetros: HORIZONTE=1 mês, LIMIAR_PP=0.3, corte treino/teste=80% no tempo.
"""

import os
import numpy as np
import pandas as pd

PASTA = "dados"
HORIZONTE = 1
LIMIAR_PP = 0.3


def _mensal(csv, col):
    """Lê uma série e reamostra para o último valor de cada mês (fim do mês)."""
    caminho = os.path.join(PASTA, f"{csv}.csv")
    if not os.path.exists(caminho):
        return None
    df = pd.read_csv(caminho)
    dcol = "dataHoraCotacao" if "dataHoraCotacao" in df.columns else "data"
    if col not in df.columns:                 # coluna ausente -> deixa o chamador tentar outra
        return None
    df[dcol] = pd.to_datetime(df[dcol])
    s = df.set_index(dcol)[col].resample("ME").last()
    return s


def _direcao(delta):
    if delta >= LIMIAR_PP:
        return "sobe"
    if delta <= -LIMIAR_PP:
        return "cai"
    return "indefinido"


def montar_tabela():
    """Monta a tabela mensal empilhada (imóvel+veículos) com features e rótulo."""
    dolar = _mensal("dolar", "cotacaoVenda").rename("dolar")
    ntnb  = _mensal("ntnb_2035", "ntnb_2035").rename("ntnb")
    soja_col = "soja_usc_bushel"
    soja = _mensal("soja_usd", soja_col)
    if soja is None:
        soja = _mensal("soja_usd", "soja_usd")
    soja = soja.rename("soja")
    # demanda por crédito (lag natural: publicadas ~2 meses após o mês de ref.)
    comp = _mensal("comprometimento_renda", "comprometimento_renda")
    endv = _mensal("endividamento", "endividamento")
    partes = [dolar, ntnb, soja]
    if comp is not None:
        partes.append(comp.rename("comprometimento_renda"))
    if endv is not None:
        partes.append(endv.rename("endividamento"))
    macro = pd.concat(partes, axis=1)

    # anomalia: houve alguma anomalia no mês? (do estágio 1)
    anom_path = os.path.join(PASTA, "anomalias.csv")
    an_mes = pd.Series(dtype=float, name="anomalias_mes")
    if os.path.exists(anom_path) and os.path.getsize(anom_path) > 0:
        an = pd.read_csv(anom_path)
        if not an.empty and "data" in an.columns:
            an["data"] = pd.to_datetime(an["data"])
            an_mes = an.set_index("data").resample("ME").size().rename("anomalias_mes")

    linhas = []
    for csv, col, tipo in [("serie_imobiliario", "imobiliario", "imovel"),
                           ("serie_veiculos", "veiculos", "veiculos")]:
        taxa = _mensal(csv, col).rename("taxa")
        d = pd.concat([taxa, macro], axis=1, sort=True)
        d["anomalias_mes"] = an_mes.reindex(d.index).fillna(0)
        # demanda tem lag de publicação -> forward-fill para não furar o treino
        for c in ["comprometimento_renda", "endividamento"]:
            if c in d.columns:
                d[c] = d[c].ffill()
        d = d.dropna(subset=["taxa"]).copy()

        # features derivadas da própria taxa
        d["var_taxa_3m"] = d["taxa"].diff(3)                 # tendência recente
        # rótulo: direção da taxa daqui a HORIZONTE meses
        d["taxa_futura"] = d["taxa"].shift(-HORIZONTE)
        d["rotulo"] = (d["taxa_futura"] - d["taxa"]).apply(
            lambda x: _direcao(x) if pd.notna(x) else np.nan)
        d["tipo_credito"] = 1 if tipo == "imovel" else 0
        d["mes"] = d.index
        linhas.append(d)

    tab = pd.concat(linhas, ignore_index=True)
    # forward-fill do macro (dias sem pregão no fim do mês) e limpa treino
    tab = tab.dropna(subset=["rotulo", "dolar", "ntnb", "soja", "var_taxa_3m"])
    return tab.sort_values("mes").reset_index(drop=True)


def treinar():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report

    tab = montar_tabela()
    feats = ["dolar", "ntnb", "soja", "anomalias_mes", "taxa", "var_taxa_3m", "tipo_credito"]
    # inclui demanda por crédito se as colunas existirem na tabela
    for c in ["comprometimento_renda", "endividamento"]:
        if c in tab.columns:
            feats.append(c)
    # RF não aceita NaN: preenche buracos residuais das features de demanda
    tab[feats] = tab[feats].ffill().bfill()
    X, y = tab[feats], tab["rotulo"]

    # validação TEMPORAL: 80% mais antigos treinam, 20% mais recentes testam
    corte = int(len(tab) * 0.8)
    Xtr, Xte = X.iloc[:corte], X.iloc[corte:]
    ytr, yte = y.iloc[:corte], y.iloc[corte:]

    rf = RandomForestClassifier(n_estimators=300, max_depth=6,
                                min_samples_leaf=5, random_state=42, class_weight="balanced")
    rf.fit(Xtr, ytr)
    pred = rf.predict(Xte)

    # baseline trivial: repetir a direção ATUAL (var_taxa_3m) como previsão
    base_pred = Xte["var_taxa_3m"].apply(_direcao).values

    acc_rf   = accuracy_score(yte, pred)
    acc_base = accuracy_score(yte, base_pred)

    print(f"amostras: {len(tab)} (treino {len(Xtr)} / teste {len(Xte)})")
    print(f"acurácia Random Forest : {acc_rf:.3f}")
    print(f"acurácia baseline      : {acc_base:.3f}  (repetir direção atual)")
    print(f"veredito: {'RF SUPERA o baseline' if acc_rf > acc_base else 'RF NÃO supera o baseline — modelo não agrega'}")
    print("\nrelatório (teste):")
    print(classification_report(yte, pred, zero_division=0))
    print("importância das features:")
    for f, imp in sorted(zip(feats, rf.feature_importances_), key=lambda t: -t[1]):
        print(f"  {f:16}: {imp:.3f}")
    return rf


if __name__ == "__main__":
    treinar()