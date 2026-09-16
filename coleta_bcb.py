"""
fin_tech_07 — Coleta de dados financeiros do Banco Central
==========================================================

O projeto entrega DUAS naturezas de dado, cada uma na sua saída:

  A) SÉRIES TEMPORAIS MENSAIS (mesma base de tempo, comparáveis)
     - Imobiliário PF ...... taxa média de mercado, % a.a. .. API SGS, cód. 20772
     - Veículos PF ......... taxa média de mercado, % a.a. .. API SGS, cód. 20749
     - Dólar (venda) ....... cotação diária -> média mensal .. API PTAX
     Saídas: serie_*.csv/.png e o gráfico combinado series_combinado.png.

  B) RANKING DE VEÍCULOS (OData de recursos livres) — em duas visões:
     - Foto da semana atual: 36 menores taxas por instituição.
       Saídas: ranking_veiculos.csv/.png.
     - Histórico acumulado: taxa por instituição ao longo do tempo, que
       NUNCA descarta o que já foi coletado (append incremental, sem duplicar).
       Saída: historico_ranking_veiculos.csv.

Robustez: todas as chamadas usam retry (a API do BC às vezes estoura o timeout,
sobretudo de madrugada). Sem isso, uma lentidão passageira derrubaria a coleta.

Três APIs, três formatos de data:
  - OData juros : recusa $filter (dá 400); filtramos no pandas.
  - SGS         : datas DD/MM/AAAA no retorno.
  - PTAX        : datas MM-DD-AAAA na chamada.

Antes do 1º uso, rode inspecionar.py para confirmar os campos da OData.
"""

import os
import time
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")             # backend sem tela — obrigatório no GitHub Actions
import matplotlib.pyplot as plt   # importado DEPOIS de definir o backend
from datetime import date

from alertas import verificar_alertas   # módulo de alertas por e-mail
from db import gravar_no_banco          # camada Postgres (além dos CSVs)


# ===========================================================================
#  CONFIGURAÇÃO  (ponto único de ajuste)
# ===========================================================================

PASTA = "dados"                   # onde CSVs e PNGs são gravados e versionados
os.makedirs(PASTA, exist_ok=True)

# --- Endpoints das três APIs ---
API_ODATA = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/"
API_SGS   = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
API_PTAX  = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
             "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)")

# --- Códigos das séries SGS ---
SGS_IMOBILIARIO = 20772           # PF, financiamento imobiliário taxas de mercado, % a.a.
SGS_VEICULOS    = 20749           # PF, aquisição de veículos (recursos livres), % a.a.

# --- Campos da OData de juros (confirme com inspecionar.py) ---
CAMPO_SEGMENTO    = "Segmento"
CAMPO_MODALIDADE  = "Modalidade"
CAMPO_INSTITUICAO = "InstituicaoFinanceira"
CAMPO_TAXA        = "TaxaJurosAoAno"
SEGMENTO_PF       = "PESSOA FÍSICA"   # valor EXATO do segmento pessoa física
MODALIDADE_VEIC   = "veículos"        # trecho buscado na Modalidade (case-insensitive)
TOP_RANKING       = 36                # nº de instituições no ranking

# --- Paginação da OData (recusa $filter; puxamos tudo e filtramos no pandas) ---
PAGINA_ODATA      = 1000          # linhas por página ($top máximo seguro; 5000 dá 400)
MAX_PAGINAS_ODATA = 10            # trava de segurança: até 10.000 linhas
MAX_PAGINAS_IMOVEL = 40           # ConsultaUnificada é maior (PF+PJ, 26 modalidades)

# --- Dólar (PTAX): início da série e formato de data MM-DD-AAAA ---
PTAX_ANO_INICIAL  = 1984
PTAX_DATA_INICIAL = "11-28-1984"

# --- Retry / timeout das chamadas HTTP ---
TIMEOUT_PADRAO    = 120           # s — o BC às vezes é lento
RETRY_TENTATIVAS  = 4             # nº de tentativas antes de desistir
RETRY_ESPERA      = 10            # s de espera entre tentativas


def caminho(nome, ext):
    """Monta o caminho dentro de dados/  (ex.: caminho('dolar', 'csv'))."""
    return os.path.join(PASTA, f"{nome}.{ext}")


# ===========================================================================
#  HTTP COM RETRY
# ===========================================================================

def _get(url, **kwargs):
    """
    GET com retry. A API do BC às vezes estoura o timeout (especialmente de
    madrugada, quando a coleta roda). Tenta RETRY_TENTATIVAS vezes, esperando
    RETRY_ESPERA segundos entre elas, antes de desistir — assim uma lentidão
    passageira não derruba o job do GitHub Actions.
    """
    kwargs.setdefault("timeout", TIMEOUT_PADRAO)
    ultimo_erro = None
    for tentativa in range(1, RETRY_TENTATIVAS + 1):
        try:
            r = requests.get(url, **kwargs)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            ultimo_erro = e
            if tentativa < RETRY_TENTATIVAS:
                time.sleep(RETRY_ESPERA)      # espera antes de tentar de novo
    raise ultimo_erro                          # esgotou as tentativas


# ===========================================================================
#  HELPERS DE API
# ===========================================================================

def bcb_odata(colecao, **params):
    """Chama uma coleção da OData de juros e devolve um DataFrame (JSON)."""
    params["$format"] = "json"
    r = _get(API_ODATA + colecao, params=params)
    return pd.DataFrame(r.json()["value"])


def sgs(codigo, nome_coluna):
    """
    Baixa uma série temporal mensal do SGS.
      - retorno: lista de {"data": "DD/MM/AAAA", "valor": "26.52"}
      - datas em DD/MM/AAAA (≠ PTAX, que é MM-DD-AAAA)
    Devolve DataFrame ['data' (datetime), nome_coluna (float)].
    """
    r = _get(API_SGS.format(codigo=codigo), params={"formato": "json"})
    df = pd.DataFrame(r.json())
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y")   # DD/MM/AAAA -> data
    df[nome_coluna] = pd.to_numeric(df["valor"])                 # texto -> float
    return df[["data", nome_coluna]]


def ptax_periodo(ini, fim):
    """Cotação do dólar entre duas datas (MM-DD-AAAA, sem aspas — adicionadas aqui)."""
    r = _get(API_PTAX, params={
        "@dataInicial": f"'{ini}'",
        "@dataFinalCotacao": f"'{fim}'",
        "$format": "json",
        "$select": "cotacaoCompra,cotacaoVenda,dataHoraCotacao",
    })
    return r.json()["value"]


# ===========================================================================
#  A) SÉRIES TEMPORAIS MENSAIS
# ===========================================================================

def carregar_dolar():
    """
    Série DIÁRIA do dólar, incremental. dados/dolar.csv é o "estado":
      - 1ª execução: baixa 1984 -> hoje (ano a ano) e salva.
      - Execuções seguintes: lê o CSV e busca só do último dia salvo até hoje.
    """
    csv = caminho("dolar", "csv")
    hoje = date.today()

    if os.path.exists(csv):
        base = pd.read_csv(csv, parse_dates=["dataHoraCotacao"])
        ultima = base["dataHoraCotacao"].max().date()
        if ultima >= hoje:
            return base
        novos = ptax_periodo(ultima.strftime("%m-%d-%Y"), hoje.strftime("%m-%d-%Y"))
        df = pd.concat([base, pd.DataFrame(novos)], ignore_index=True)
    else:
        linhas = []
        for ano in range(PTAX_ANO_INICIAL, hoje.year + 1):
            ini = PTAX_DATA_INICIAL if ano == PTAX_ANO_INICIAL else f"01-01-{ano}"
            fim = hoje.strftime("%m-%d-%Y") if ano == hoje.year else f"12-31-{ano}"
            linhas += ptax_periodo(ini, fim)
        df = pd.DataFrame(linhas)

    df["dataHoraCotacao"] = pd.to_datetime(df["dataHoraCotacao"])
    df = (df.drop_duplicates("dataHoraCotacao")
            .sort_values("dataHoraCotacao")
            .reset_index(drop=True))
    df.to_csv(csv, index=False)
    return df


def dolar_mensal(df_diario):
    """
    Média MENSAL da cotação de venda, para alinhar com as taxas do SGS (mensais).
    Default: média do mês. Para fechamento de fim de mês, troque .mean() por .last().
    """
    serie = (df_diario.set_index("dataHoraCotacao")["cotacaoVenda"]
                      .resample("MS").mean())     # MS = 1º dia do mês
    return serie.reset_index().rename(columns={"cotacaoVenda": "dolar_venda"})


# ===========================================================================
#  B) RANKING DE VEÍCULOS — foto atual + histórico acumulado
# ===========================================================================

def baixar_veiculos_pf():
    """
    Baixa TODAS as linhas de veículos (PF) da OData de recursos livres, uma vez.
    Base tanto do ranking atual quanto do histórico (evita pagar 2x a chamada,
    que é a mais custosa e a que dava timeout).

    A OData recusa $filter (400 — confirmado), então baixamos com $select+$skip
    (paginado) e filtramos PF + 'veículos' no pandas.
    """
    colunas = (f"InicioPeriodo,FimPeriodo,{CAMPO_SEGMENTO},{CAMPO_MODALIDADE},"
               f"{CAMPO_INSTITUICAO},{CAMPO_TAXA}")

    lotes = []
    for pagina in range(MAX_PAGINAS_ODATA):        # trava de segurança
        lote = bcb_odata("TaxasJurosDiariaPorInicioPeriodo", **{
            "$select": colunas,
            "$top": PAGINA_ODATA,
            "$skip": pagina * PAGINA_ODATA,
        })
        if lote.empty:
            break
        lotes.append(lote)
        if len(lote) < PAGINA_ODATA:               # última página
            break
    df = pd.concat(lotes, ignore_index=True)

    eh_pf   = df[CAMPO_SEGMENTO] == SEGMENTO_PF
    eh_veic = df[CAMPO_MODALIDADE].str.contains(MODALIDADE_VEIC, case=False, na=False)
    return df[eh_pf & eh_veic].copy()


def ranking_semana_atual(df_veic_pf):
    """
    Foto do momento: 36 menores taxas na semana mais recente, uma por instituição.
    Derivado do DataFrame já baixado (sem nova chamada de rede).
    """
    df = df_veic_pf[df_veic_pf["InicioPeriodo"] == df_veic_pf["InicioPeriodo"].max()]
    # uma linha por instituição = a menor taxa dela naquela semana
    df = df.sort_values(CAMPO_TAXA).drop_duplicates(subset=CAMPO_INSTITUICAO, keep="first")
    return df.sort_values(CAMPO_TAXA).head(TOP_RANKING).reset_index(drop=True)


def atualizar_historico_ranking(df_veic_pf):
    """
    Histórico acumulado da taxa por instituição ao longo do tempo (Opção 2),
    que NUNCA descarta o que já foi coletado.

    Reduz o dado a uma linha por (período, instituição) com a menor taxa, e faz
    APPEND ao histórico em disco, deduplicando por (período + instituição). Como
    o BC pode devolver um ou vários períodos por chamada, essa dedup cobre os
    dois casos: preenche de uma vez se vierem vários; acumula semana a semana se
    vier só o atual. Nada do passado é perdido.
    """
    csv = caminho("historico_ranking_veiculos", "csv")
    chave = ["InicioPeriodo", CAMPO_INSTITUICAO]

    # uma linha por (período, instituição): menor taxa
    novo = (df_veic_pf.sort_values(CAMPO_TAXA)
                      .drop_duplicates(subset=chave, keep="first")
                      [["InicioPeriodo", "FimPeriodo", CAMPO_INSTITUICAO, CAMPO_TAXA]]
                      .copy())

    if os.path.exists(csv):
        antigo = pd.read_csv(csv)
        combinado = pd.concat([antigo, novo], ignore_index=True)
    else:
        combinado = novo

    # dedup final: cada (período, instituição) aparece uma vez (mantém o mais recente)
    combinado = (combinado.drop_duplicates(subset=chave, keep="last")
                          .sort_values(["InicioPeriodo", CAMPO_TAXA])
                          .reset_index(drop=True))
    combinado.to_csv(csv, index=False)
    return combinado


# ===========================================================================
#  IMÓVEL — ranking por instituição, POR MODALIDADE (indexador)
#  Fonte: coleção ConsultaUnificada (a de recursos livres não tem imobiliário).
#  São 6 modalidades (mercado/regulado × Prefixado/IPCA/TR); mantemos todas
#  separadas para o usuário comparar cada indexador.
# ===========================================================================

def baixar_imovel_pf():
    """
    Baixa as linhas de financiamento imobiliário (PF) da coleção
    ConsultaUnificada, uma vez. Mesma técnica dos veículos: $select+$skip
    paginado (a coleção também recusa $filter) e filtro no pandas — aqui,
    Segmento PF e Modalidade contendo 'imobiliário' (pega as 6 modalidades).
    """
    colunas = (f"InicioPeriodo,FimPeriodo,{CAMPO_SEGMENTO},{CAMPO_MODALIDADE},"
               f"{CAMPO_INSTITUICAO},{CAMPO_TAXA}")

    lotes = []
    for pagina in range(MAX_PAGINAS_IMOVEL):       # coleção maior -> mais páginas
        lote = bcb_odata("ConsultaUnificada", **{
            "$select": colunas,
            "$top": PAGINA_ODATA,
            "$skip": pagina * PAGINA_ODATA,
        })
        if lote.empty:
            break
        lotes.append(lote)
        if len(lote) < PAGINA_ODATA:
            break
    df = pd.concat(lotes, ignore_index=True)

    # ConsultaUnificada usa "Pessoa Física" (capitalização normal), diferente
    # da coleção de veículos que usa "PESSOA FÍSICA". Comparo sem diferenciar
    # maiúsculas para casar nas duas grafias.
    eh_pf   = df[CAMPO_SEGMENTO].str.upper() == SEGMENTO_PF
    eh_imob = df[CAMPO_MODALIDADE].str.contains("imobiliário", case=False, na=False)
    return df[eh_pf & eh_imob].copy()


def ranking_imovel_atual(df_imovel_pf):
    """
    Foto do momento: por MODALIDADE (indexador), as menores taxas por
    instituição na semana mais recente. Mantém a coluna Modalidade para o
    seletor do dashboard. Uma linha por (modalidade, instituição).
    """
    df = df_imovel_pf[df_imovel_pf["InicioPeriodo"] == df_imovel_pf["InicioPeriodo"].max()]
    df = (df.sort_values(CAMPO_TAXA)
            .drop_duplicates(subset=[CAMPO_MODALIDADE, CAMPO_INSTITUICAO], keep="first"))
    return (df.sort_values([CAMPO_MODALIDADE, CAMPO_TAXA])
              [["InicioPeriodo", "FimPeriodo", CAMPO_MODALIDADE,
                CAMPO_INSTITUICAO, CAMPO_TAXA]]
              .reset_index(drop=True))


def atualizar_historico_imovel(df_imovel_pf):
    """
    Histórico acumulado do imóvel por (período, modalidade, instituição) — nunca
    descarta o passado. Mesma lógica do histórico de veículos, mas com a
    modalidade na chave (são 6 indexadores em paralelo).
    """
    csv = caminho("historico_ranking_imovel", "csv")
    chave = ["InicioPeriodo", CAMPO_MODALIDADE, CAMPO_INSTITUICAO]

    novo = (df_imovel_pf.sort_values(CAMPO_TAXA)
                        .drop_duplicates(subset=chave, keep="first")
                        [["InicioPeriodo", "FimPeriodo", CAMPO_MODALIDADE,
                          CAMPO_INSTITUICAO, CAMPO_TAXA]]
                        .copy())

    if os.path.exists(csv):
        antigo = pd.read_csv(csv)
        combinado = pd.concat([antigo, novo], ignore_index=True)
    else:
        combinado = novo

    combinado = (combinado.drop_duplicates(subset=chave, keep="last")
                          .sort_values(["InicioPeriodo", CAMPO_MODALIDADE, CAMPO_TAXA])
                          .reset_index(drop=True))
    combinado.to_csv(csv, index=False)
    return combinado


# ===========================================================================
#  GRÁFICOS
# ===========================================================================

def grafico_serie(df, coluna, titulo, nome):
    """Linha temporal mensal de uma taxa (% a.a.)."""
    ax = df.plot(x="data", y=coluna, figsize=(12, 4), legend=False, title=titulo)
    ax.set_xlabel(""); ax.set_ylabel("% a.a."); ax.grid(True, alpha=0.3)
    ax.figure.savefig(caminho(nome, "png"), dpi=120, bbox_inches="tight")
    plt.close(ax.figure)


def grafico_dolar(df, nome):
    """Linha temporal da cotação de venda — histórico diário completo."""
    ax = df.plot(x="dataHoraCotacao", y="cotacaoVenda", figsize=(12, 4),
                 legend=False, title="Dólar (venda) 1984–hoje")
    ax.set_xlabel(""); ax.set_ylabel("R$"); ax.grid(True, alpha=0.3)
    ax.figure.savefig(caminho(nome, "png"), dpi=120, bbox_inches="tight")
    plt.close(ax.figure)


def grafico_ranking(df, nome):
    """
    Barra horizontal — uma barra por instituição, menor taxa no topo.
    O período (semana de referência) fica destacado no título, deixando claro
    que é foto de uma data só.
    """
    ini = pd.to_datetime(df["InicioPeriodo"].iloc[0]).strftime("%d/%m/%Y")
    fim = pd.to_datetime(df["FimPeriodo"].iloc[0]).strftime("%d/%m/%Y")

    ax = df.plot.barh(x=CAMPO_INSTITUICAO, y=CAMPO_TAXA, figsize=(10, 11), legend=False)
    ax.invert_yaxis()                              # menor taxa em cima
    ax.set_ylabel(""); ax.set_xlabel("Taxa ao ano (%)")
    ax.grid(True, axis="x", alpha=0.3)
    ax.set_title(f"{TOP_RANKING} menores taxas — Veículos PF\n"
                 f"Período de referência: {ini} a {fim}",
                 fontsize=12, fontweight="bold")
    ax.figure.savefig(caminho(nome, "png"), dpi=120, bbox_inches="tight")
    plt.close(ax.figure)


def grafico_combinado(imob, veic, dolar_m, nome):
    """
    Um gráfico, mesma base mensal: juros (eixo esquerdo, % a.a.) e dólar (eixo
    direito, R$). Dois eixos porque as unidades diferem. Começa onde as três
    séries coexistem (~2011).
    """
    fig, ax_esq = plt.subplots(figsize=(12, 5))

    ax_esq.plot(imob["data"], imob["imobiliario"], label="Imobiliário (% a.a.)")
    ax_esq.plot(veic["data"], veic["veiculos"],    label="Veículos (% a.a.)")
    ax_esq.set_ylabel("Juros (% a.a.)"); ax_esq.grid(True, alpha=0.3)

    ax_dir = ax_esq.twinx()
    ax_dir.plot(dolar_m["dataHoraCotacao"], dolar_m["dolar_venda"],
                color="green", linestyle="--", label="Dólar (R$)")
    ax_dir.set_ylabel("Dólar (R$)")

    inicio_comum = max(imob["data"].min(), veic["data"].min(),
                       dolar_m["dataHoraCotacao"].min())
    ax_esq.set_xlim(left=inicio_comum)

    l_e, r_e = ax_esq.get_legend_handles_labels()
    l_d, r_d = ax_dir.get_legend_handles_labels()
    ax_esq.legend(l_e + l_d, r_e + r_d, loc="upper left")

    ax_esq.set_title("Juros PF e dólar — base mensal")
    fig.savefig(caminho(nome, "png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


# ===========================================================================
#  EXECUÇÃO
# ===========================================================================

def main():
    # --- A) séries temporais mensais ---
    imob         = sgs(SGS_IMOBILIARIO, "imobiliario")
    veic         = sgs(SGS_VEICULOS,    "veiculos")
    dolar_diario = carregar_dolar()
    dolar_m      = dolar_mensal(dolar_diario)

    imob.to_csv(caminho("serie_imobiliario", "csv"),    index=False)
    veic.to_csv(caminho("serie_veiculos", "csv"),       index=False)
    dolar_m.to_csv(caminho("serie_dolar_mensal", "csv"), index=False)

    grafico_serie(imob, "imobiliario", "Juros — Imobiliário PF (SGS 20772)", "serie_imobiliario")
    grafico_serie(veic, "veiculos",    "Juros — Veículos PF (SGS 20749)",    "serie_veiculos")
    grafico_dolar(dolar_diario, "dolar")
    grafico_combinado(imob, veic, dolar_m, "series_combinado")

    # --- B) ranking: uma busca, duas saídas (foto atual + histórico acumulado) ---
    veic_pf   = baixar_veiculos_pf()
    ranking   = ranking_semana_atual(veic_pf)
    historico = atualizar_historico_ranking(veic_pf)   # append incremental, nunca descarta

    ranking.to_csv(caminho("ranking_veiculos", "csv"), index=False)
    grafico_ranking(ranking, "ranking_veiculos")

    # --- C) imóvel: ranking por instituição, nas 6 modalidades (indexadores) ---
    imovel_pf      = baixar_imovel_pf()
    ranking_imovel = ranking_imovel_atual(imovel_pf)
    historico_imovel = atualizar_historico_imovel(imovel_pf)   # nunca descarta
    ranking_imovel.to_csv(caminho("ranking_imovel", "csv"), index=False)

    # --- grava no Postgres (além dos CSVs, que seguem versionados) ---
    gravar_no_banco(imob, veic, dolar_diario, dolar_m, ranking, historico,
                    ranking_imovel, historico_imovel)

    # --- alertas por e-mail (dispara só no cruzamento de limiar) ---
    verificar_alertas(ranking, imob, dolar_diario)

    # --- resumo ---
    for nome, df in [("imobiliario", imob), ("veiculos", veic),
                     ("dolar_diario", dolar_diario), ("dolar_mensal", dolar_m),
                     ("ranking_veic", ranking), ("historico_veic", historico),
                     ("ranking_imovel", ranking_imovel),
                     ("historico_imovel", historico_imovel)]:
        print(f"{nome:16} → {df.shape}")


if __name__ == "__main__":
    main()