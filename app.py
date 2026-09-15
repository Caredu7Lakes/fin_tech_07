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
    url = os.getenv("DATABASE_URL") or st.secrets.get("DATABASE_URL")
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
ranking   = carregar("ranking_veiculos")
serie     = carregar("serie_juros")
dolar_m   = carregar("dolar_mensal")


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

    # destaque: a instituição mais barata
    menor = ranking.iloc[0]
    st.metric("Instituição mais barata",
              menor["instituicao"], f'{menor["taxa_aa"]:.2f}% a.a.')

    # gráfico de barras (menor no topo) — Streamlit desenha horizontal ao usar
    # o índice como categoria.
    graf = ranking.set_index("instituicao")["taxa_aa"]
    st.bar_chart(graf, horizontal=True, height=700)
else:
    st.info("Sem dados de ranking ainda.")


# ===========================================================================
#  BLOCO B — Juros (imóvel e veículos) x dólar, mesma base mensal
# ===========================================================================

st.header("B) Custo de crédito x dólar (base mensal)")

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

st.header("C) Próximo passo")
st.info(
    "**O próximo impacto é o endividamento das famílias.** Estes custos de "
    "crédito se traduzem em comprometimento de renda — a fase 2 do projeto "
    "cruza estas séries com o endividamento das famílias (série do BC) para "
    "medir esse efeito."
)

st.divider()
st.caption("Fonte: Banco Central do Brasil (APIs Olinda, SGS e PTAX). "
           "Dados atualizados diariamente via GitHub Actions.")