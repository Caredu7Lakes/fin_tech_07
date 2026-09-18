"""
fin_tech_07 — Base DIÁRIA unificada (entrada do pipeline de ML)
===============================================================

Junta todas as séries numa tabela DIÁRIA, ancorada nos dias do ranking de
veículos. O ranking do BC é uma janela móvel de ~5 dias úteis atualizada
diariamente, então cada InicioPeriodo é um dia útil — a granularidade real é
diária, não semanal.

Regras:
  - Grade temporal: cada InicioPeriodo distinto do ranking de veículos (1 por dia útil).
  - subsidio_veiculos: menor taxa de veiculos − Selic meta (forward-fill). Negativo = subsidio.
  - dolar, ntnb_2035, soja: valor do próprio dia; se não houver (feriado/fim de
    semana), o último valor anterior disponível (forward-fill).
  - juros mensais (imóvel/veículos): forward-fill do mês vigente.

Saída: dados/base_diaria.csv — uma linha por dia, colunas: data, subsidio_veiculos,
dolar, ntnb_2035, soja, juro_imovel, juro_veiculos.
"""

import os
import pandas as pd

PASTA = "dados"


def _ler(nome, **kw):
    return pd.read_csv(os.path.join(PASTA, f"{nome}.csv"), **kw)


def _valor_no_dia(serie, col, dias):
    """
    Para cada dia da grade, o valor de 'serie[col]' naquele dia; se ausente,
    o último valor anterior (forward-fill). 'serie' tem ['data', col].
    """
    s = serie.dropna(subset=[col]).sort_values("data").set_index("data")[col]
    vals = []
    for dia in dias:
        ate = s[s.index <= dia]
        vals.append(ate.iloc[-1] if not ate.empty else pd.NA)
    return vals


def montar_base_diaria():
    # --- grade diária = dias distintos do ranking de veículos ---
    hist = _ler("historico_ranking_veiculos", parse_dates=["InicioPeriodo"])
    menor = (hist.groupby("InicioPeriodo")["TaxaJurosAoAno"].min()
                 .reset_index()
                 .rename(columns={"InicioPeriodo": "data", "TaxaJurosAoAno": "menor_taxa"})
                 .sort_values("data"))
    # subsídio = menor taxa de veículos − Selic meta vigente (forward-fill)
    selic = _ler("selic_meta", parse_dates=["data"]).sort_values("data")
    m = pd.merge_asof(menor, selic, on="data", direction="backward")
    m["subsidio_veiculos"] = m["menor_taxa"] - m["selic_meta"]
    base = m[["data", "subsidio_veiculos"]].copy()
    dias = base["data"].tolist()

    # --- séries diárias (valor do dia, com forward-fill) ---
    dolar = _ler("dolar", parse_dates=["dataHoraCotacao"]).rename(
        columns={"dataHoraCotacao": "data", "cotacaoVenda": "dolar"})
    base["dolar"] = _valor_no_dia(dolar[["data", "dolar"]], "dolar", dias)

    ntnb = _ler("ntnb_2035", parse_dates=["data"])
    base["ntnb_2035"] = _valor_no_dia(ntnb, "ntnb_2035", dias)

    soja = _ler("soja_usd", parse_dates=["data"])
    col_soja = "soja_usc_bushel" if "soja_usc_bushel" in soja.columns else "soja_usd"
    base["soja"] = _valor_no_dia(soja, col_soja, dias)

    # --- juros mensais (forward-fill do mês vigente) ---
    imo = _ler("serie_imobiliario", parse_dates=["data"])
    base["juro_imovel"] = _valor_no_dia(imo, "imobiliario", dias)
    vei = _ler("serie_veiculos", parse_dates=["data"])
    base["juro_veiculos"] = _valor_no_dia(vei, "veiculos", dias)

    base.to_csv(os.path.join(PASTA, "base_diaria.csv"), index=False)
    return base


if __name__ == "__main__":
    b = montar_base_diaria()
    print(f"base_diaria → {b.shape}")
    print(b.to_string(index=False))