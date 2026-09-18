"""
fin_tech_07 — Dashboard (Streamlit)
===================================

Responde à pergunta de negócio do projeto, lendo do Postgres (Neon):

  "Onde está o crédito de veículos mais barato hoje, e como o custo de crédito
   (imóvel e veículos) se move em relação ao dólar?"

Três blocos:
  A) Ranking atual das instituições (menores taxas de veículos, PF).
  B) Séries de juros (imóvel e veículos) x dólar, na mesma base mensal.
  C) Provocação: o próximo impacto é o endividamento das famílias.

Conexão via DATABASE_URL. No Streamlit Cloud, defina-a em Settings → Secrets
(formato TOML: DATABASE_URL = "postgresql+psycopg2://...").
Rodar local:  streamlit run app.py
"""

import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine


# ===========================================================================
#  CONEXÃO E LEITURA
# ===========================================================================

@st.cache_resource
def get_engine():
    """
    Cria o engine uma vez (cache_resource) a partir de DATABASE_URL.
    No Streamlit Cloud, st.secrets expõe os secrets; localmente lê do ambiente.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        # st.secrets lança exceção se não houver secrets.toml (rodando local).
        # No Streamlit Cloud o secret existe; local usamos a variável de ambiente.
        try:
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    if not url:
        st.error("DATABASE_URL não definida. Configure nos Secrets do app.")
        st.stop()
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=3600)   # cacheia 1h: o dado muda 1x/dia, não a cada clique
def carregar(tabela):
    """Lê uma tabela inteira do Postgres como DataFrame."""
    return pd.read_sql(f"SELECT * FROM {tabela}", get_engine())


# ===========================================================================
#  PÁGINA
# ===========================================================================

st.set_page_config(page_title="fin_tech_07 — Crédito e câmbio",
                   page_icon="📊", layout="wide")

st.title("📊 fin_tech_07 — Crédito ao consumidor e câmbio")
st.markdown(
    "**Pergunta:** onde está o crédito de veículos mais barato hoje, e como o "
    "custo de crédito (imóvel e veículos) se move em relação ao dólar?"
)

# --- carrega os dados uma vez ---
ranking        = carregar("ranking_veiculos")
serie          = carregar("serie_juros")
dolar_m        = carregar("dolar_mensal")
ranking_imovel = carregar("ranking_imovel")

# ML: anomalias e subsídio (podem não existir se o pipeline ML ainda não rodou)
def carregar_opcional(tabela):
    try:
        return carregar(tabela)
    except Exception:
        return pd.DataFrame()

anomalias_df = carregar_opcional("anomalias")
subsidio_df  = carregar_opcional("subsidio_veiculos")


# ===========================================================================
#  BLOCO A — Ranking atual das instituições
# ===========================================================================

st.header("A) Onde está o crédito de veículos mais barato")

# período de referência (todas as linhas do snapshot têm o mesmo)
if not ranking.empty:
    ini = pd.to_datetime(ranking["inicio_periodo"].iloc[0]).strftime("%d/%m/%Y")
    fim = pd.to_datetime(ranking["fim_periodo"].iloc[0]).strftime("%d/%m/%Y")
    st.caption(f"Semana de referência: {ini} a {fim}")

    ranking = ranking.sort_values("taxa_aa").reset_index(drop=True)

    # destaque: SPREAD entre a maior e a menor taxa da série (dispersão do
    # mercado). Quanto maior o spread, mais vale comparar antes de contratar.
    menor_v = float(ranking["taxa_aa"].min())
    maior_v = float(ranking["taxa_aa"].max())
    spread  = maior_v - menor_v
    c1, c2, c3 = st.columns(3)
    c1.metric("Menor taxa", f"{menor_v:.2f}% a.a.")
    c2.metric("Maior taxa", f"{maior_v:.2f}% a.a.")
    c3.metric("Spread (maior − menor)", f"{spread:.2f} p.p.")

    # gráfico de barras ORDENADO POR TAXA (menor no topo). O st.bar_chart
    # reordena o eixo sozinho, então usamos Altair, que respeita a ordem
    # definida em 'sort' pelo próprio valor da taxa.
    import altair as alt
    grafico = (
        alt.Chart(ranking)
        .mark_bar(color="#4C78A8")
        .encode(
            x=alt.X("taxa_aa:Q", title="Taxa ao ano (%)"),
            y=alt.Y("instituicao:N", sort=alt.EncodingSortField(
                field="taxa_aa", order="ascending"), title=None),
            tooltip=["instituicao", "taxa_aa"],
        )
        .properties(height=760)
    )
    st.altair_chart(grafico, use_container_width=True)
else:
    st.info("Sem dados de ranking ainda.")


# ===========================================================================
#  BLOCO B — Imóvel por instituição, por indexador (seletor)
# ===========================================================================

st.header("B) Financiamento imobiliário por instituição")

if not ranking_imovel.empty:
    import altair as alt

    modalidades = sorted(ranking_imovel["modalidade"].unique())

    # Aviso explícito: o financiamento de imóvel tem VÁRIOS indexadores, que não
    # são comparáveis entre si. O usuário precisa escolher qual quer ver.
    st.info(
        f"O financiamento imobiliário tem **{len(modalidades)} modalidades** "
        "(taxas de mercado e reguladas, indexadas a Prefixado, IPCA ou TR). "
        "Elas **não são comparáveis entre si** — escolha uma no seletor abaixo "
        "para ver o ranking das instituições naquela modalidade. Todas as "
        "opções estão disponíveis no seletor."
    )

    escolha = st.selectbox("Escolha a modalidade (indexador):", modalidades)

    imv = ranking_imovel[ranking_imovel["modalidade"] == escolha].copy()
    imv = imv.sort_values("taxa_aa").reset_index(drop=True)

    if not imv.empty:
        ini = pd.to_datetime(imv["inicio_periodo"].iloc[0]).strftime("%d/%m/%Y")
        fim = pd.to_datetime(imv["fim_periodo"].iloc[0]).strftime("%d/%m/%Y")
        st.caption(f"Semana de referência: {ini} a {fim} · {len(imv)} instituições")

        menor_i = float(imv["taxa_aa"].min())
        maior_i = float(imv["taxa_aa"].max())
        d1, d2, d3 = st.columns(3)
        d1.metric("Menor taxa", f"{menor_i:.2f}% a.a.")
        d2.metric("Maior taxa", f"{maior_i:.2f}% a.a.")
        d3.metric("Spread (maior − menor)", f"{maior_i - menor_i:.2f} p.p.")

        g_imv = (
            alt.Chart(imv)
            .mark_bar(color="#54A24B")
            .encode(
                x=alt.X("taxa_aa:Q", title="Taxa ao ano (%)"),
                y=alt.Y("instituicao:N", sort=alt.EncodingSortField(
                    field="taxa_aa", order="ascending"), title=None),
                tooltip=["instituicao", "taxa_aa"],
            )
            .properties(height=max(300, 26 * len(imv)))
        )
        st.altair_chart(g_imv, use_container_width=True)
else:
    st.info("Sem dados de imóvel ainda.")


# ===========================================================================
#  BLOCO C — Juros (imóvel e veículos) x dólar, mesma base mensal
# ===========================================================================

st.header("C) Juros imóvel x juros veículos (base mensal)")

if not serie.empty and not dolar_m.empty:
    # juros: formato longo -> largo (uma coluna por modalidade)
    juros = serie.pivot(index="data", columns="modalidade", values="taxa_aa")
    juros.index = pd.to_datetime(juros.index)

    dm = dolar_m.copy()
    dm["mes"] = pd.to_datetime(dm["mes"])
    dm = dm.set_index("mes")["cotacao_venda"].rename("dolar")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Juros (% a.a.)")
        st.line_chart(juros)
    with col2:
        st.subheader("Dólar — venda (R$)")
        st.line_chart(dm)

    st.caption("Eixos separados porque as unidades diferem (% a.a. vs R$). "
               "Recorte comum começa onde as três séries coexistem.")
else:
    st.info("Sem séries suficientes ainda.")


# ===========================================================================
#  BLOCO C — Provocação (fase 2)
# ===========================================================================

st.header("D) Análise avançada — subsídio e anomalias")

st.caption(
    "Camada analítica sobre os dados. **Nota honesta:** testamos prever a "
    "direção das taxas com machine learning (Random Forest sobre fundamentos "
    "macro e fiscais); o modelo **não superou** um baseline de inércia — juros "
    "de curto prazo são dominados por inércia e não se mostraram previsíveis "
    "com esses dados. O que funciona e tem valor está abaixo: detecção de "
    "eventos atípicos e o indicador de subsídio."
)

# --- Subsídio de veículos (menor taxa − Selic) ---
st.subheader("Subsídio no crédito de veículos")
if not subsidio_df.empty:
    import altair as alt
    sub = subsidio_df.copy()
    sub["data"] = pd.to_datetime(sub["data"])
    sub = sub.sort_values("data")
    ultimo = float(sub["subsidio_veiculos"].iloc[-1])
    st.metric("Subsídio atual (menor taxa − Selic)", f"{ultimo:.2f} p.p.",
              help="Negativo = a menor taxa de veículos está abaixo da Selic, "
                   "sinal de subsídio (banco/montadora emprestando abaixo do "
                   "custo de captação).")
    linha = (alt.Chart(sub).mark_line(color="#E45756", point=True)
             .encode(x=alt.X("data:T", title=None),
                     y=alt.Y("subsidio_veiculos:Q", title="Menor taxa − Selic (p.p.)"),
                     tooltip=["data:T", "subsidio_veiculos:Q"]))
    st.altair_chart(linha, use_container_width=True)
    st.caption("Quanto mais negativo, maior o subsídio. Sua variação sinaliza "
               "mudança na política de subsídio das montadoras/bancos.")
else:
    st.info("Subsídio ainda não disponível (pipeline ML não rodou).")

# --- Anomalias detectadas ---
st.subheader("Eventos atípicos detectados")
if not anomalias_df.empty:
    an = anomalias_df.copy()
    an["data"] = pd.to_datetime(an["data"])
    st.caption(f"{len(an)} anomalias detectadas (saltos com |z| > 3 na variação "
               "diária). Os maiores coincidem com eventos econômicos reais.")
    maiores = (an.reindex(an["z_score"].abs().sort_values(ascending=False).index)
                 .head(10)[["data", "serie", "variacao", "z_score"]]
                 .reset_index(drop=True))
    maiores["data"] = maiores["data"].dt.strftime("%d/%m/%Y")
    st.dataframe(maiores, use_container_width=True, hide_index=True)
    st.caption("Ex.: jan/1999 (dólar, fim da âncora cambial), mar/2020 "
               "(pandemia), mai/2017 (Joesley Day), set/2008 (crise/soja).")
else:
    st.info("Anomalias ainda não disponíveis (pipeline ML não rodou).")


# ===========================================================================
#  BLOCO E — Provocação (fase 2)
# ===========================================================================

st.header("E) Próximo passo")
st.info(
    "**O próximo impacto é o endividamento das famílias.** Estes custos de "
    "crédito se traduzem em comprometimento de renda — a fase 2 do projeto "
    "cruza estas séries com o endividamento das famílias (série do BC) para "
    "medir esse efeito."
)

st.divider()
st.caption("Fonte: Banco Central do Brasil (APIs Olinda, SGS e PTAX). "
           "Dados atualizados diariamente via GitHub Actions.")