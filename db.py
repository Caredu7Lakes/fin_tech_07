"""
fin_tech_07 — Camada de banco de dados (Postgres)
=================================================

Grava as tabelas do pipeline num Postgres gerenciado, ALÉM dos CSVs — que
continuam sendo o registro versionado no git. Divisão de papéis:
  - CSV  = histórico versionado (auditável no git).
  - Postgres = camada de consulta que o dashboard lê.
Cada execução do pipeline atualiza os dois.

Conexão via variável de ambiente DATABASE_URL (secret no GitHub e no Streamlit
Cloud), nunca no código. Formato:
  postgresql+psycopg2://usuario:senha@host/banco?sslmode=require

Escrita idempotente: cada tabela tem uma chave natural e usamos UPSERT
(INSERT ... ON CONFLICT DO UPDATE). Rodar o pipeline duas vezes no mesmo dia
não duplica nada — é a versão SQL da deduplicação que já fazemos no pandas.
O ranking atual é um snapshot: a tabela é substituída inteira a cada execução.
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text


# ===========================================================================
#  CONEXÃO
# ===========================================================================

def get_engine():
    """Cria o engine a partir de DATABASE_URL. Retorna None se não definida."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True)   # pre_ping evita conexão morta


# ===========================================================================
#  SCHEMA (criado se não existir)
# ===========================================================================

DDL = [
    # Juros mensais em formato longo (tidy): imobiliário e veículos na mesma
    # tabela, distinguidos por 'modalidade'. Facilita filtrar no dashboard.
    """CREATE TABLE IF NOT EXISTS serie_juros (
        data       DATE NOT NULL,
        modalidade TEXT NOT NULL,
        taxa_aa    NUMERIC,
        PRIMARY KEY (data, modalidade)
    )""",
    """CREATE TABLE IF NOT EXISTS dolar_mensal (
        mes           DATE PRIMARY KEY,
        cotacao_venda NUMERIC
    )""",
    """CREATE TABLE IF NOT EXISTS dolar_diario (
        data           DATE PRIMARY KEY,
        cotacao_compra NUMERIC,
        cotacao_venda  NUMERIC
    )""",
    # Ranking da semana atual — snapshot (substituído a cada execução).
    """CREATE TABLE IF NOT EXISTS ranking_veiculos (
        instituicao    TEXT PRIMARY KEY,
        inicio_periodo DATE,
        fim_periodo    DATE,
        taxa_aa        NUMERIC
    )""",
    # Histórico acumulado da taxa por instituição — nunca descarta o passado.
    """CREATE TABLE IF NOT EXISTS historico_ranking (
        inicio_periodo DATE NOT NULL,
        instituicao    TEXT NOT NULL,
        fim_periodo    DATE,
        taxa_aa        NUMERIC,
        PRIMARY KEY (inicio_periodo, instituicao)
    )""",
    # IMÓVEL — ranking atual por instituição E por modalidade (6 indexadores).
    # Snapshot: substituído a cada execução. PK inclui a modalidade.
    """CREATE TABLE IF NOT EXISTS ranking_imovel (
        modalidade     TEXT NOT NULL,
        instituicao    TEXT NOT NULL,
        inicio_periodo DATE,
        fim_periodo    DATE,
        taxa_aa        NUMERIC,
        PRIMARY KEY (modalidade, instituicao)
    )""",
    # IMÓVEL — histórico acumulado por (período, modalidade, instituição).
    """CREATE TABLE IF NOT EXISTS historico_imovel (
        inicio_periodo DATE NOT NULL,
        modalidade     TEXT NOT NULL,
        instituicao    TEXT NOT NULL,
        fim_periodo    DATE,
        taxa_aa        NUMERIC,
        PRIMARY KEY (inicio_periodo, modalidade, instituicao)
    )""",
]


# ===========================================================================
#  ESCRITA
# ===========================================================================

def _upsert(engine, df, tabela, pk):
    """
    Grava um DataFrame com UPSERT (idempotente):
      1. joga o df numa tabela temporária de staging;
      2. INSERT ... SELECT dela para a tabela final, com ON CONFLICT (pk)
         DO UPDATE — atualiza se a chave já existe, insere se não.
    'pk' é a lista de colunas que formam a chave natural.
    """
    if df.empty:
        return
    # Remove duplicatas pela chave ANTES de gravar: o ON CONFLICT do Postgres
    # rejeita duas linhas com a mesma PK no mesmo INSERT (CardinalityViolation).
    # keep="last" mantém o valor mais recente de cada chave.
    df = df.drop_duplicates(subset=pk, keep="last")
    cols = list(df.columns)
    staging = f"_stg_{tabela}"
    with engine.begin() as con:
        df.to_sql(staging, con, if_exists="replace", index=False)
        col_list = ", ".join(f'"{c}"' for c in cols)
        pk_list  = ", ".join(f'"{c}"' for c in pk)
        set_cols = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in cols if c not in pk)
        con.execute(text(
            f'INSERT INTO "{tabela}" ({col_list}) '
            f'SELECT {col_list} FROM "{staging}" '
            f'ON CONFLICT ({pk_list}) DO UPDATE SET {set_cols}'
        ))
        con.execute(text(f'DROP TABLE IF EXISTS "{staging}"'))


def _substituir(engine, df, tabela):
    """Snapshot: apaga tudo e regrava (para o ranking da semana atual)."""
    if df.empty:
        return
    with engine.begin() as con:
        con.execute(text(f'TRUNCATE TABLE "{tabela}"'))
    df.to_sql(tabela, engine, if_exists="append", index=False)


def gravar_no_banco(imob, veic, dolar_diario, dolar_m, ranking, historico,
                    ranking_imovel=None, historico_imovel=None):
    """
    Cria o schema (se preciso) e grava as fontes no Postgres. Se DATABASE_URL
    não estiver definida, avisa e retorna — os CSVs seguem normais, então rodar
    sem banco não quebra o pipeline.
    ranking_imovel/historico_imovel são opcionais (imóvel por instituição).
    Renomeia as colunas do pipeline (camelCase/PT) para os nomes tidy das
    tabelas antes de gravar.
    """
    engine = get_engine()
    if engine is None:
        print("[db] DATABASE_URL ausente — banco não atualizado (CSVs seguem normais).")
        return

    with engine.begin() as con:
        for stmt in DDL:
            con.execute(text(stmt))

    # serie_juros: junta imobiliário + veículos em formato longo.
    ji = (imob.rename(columns={"imobiliario": "taxa_aa"})
              .assign(modalidade="imobiliario")[["data", "modalidade", "taxa_aa"]])
    jv = (veic.rename(columns={"veiculos": "taxa_aa"})
              .assign(modalidade="veiculos")[["data", "modalidade", "taxa_aa"]])
    juros = pd.concat([ji, jv], ignore_index=True)
    juros["data"] = pd.to_datetime(juros["data"]).dt.normalize()   # garante tipo date
    _upsert(engine, juros, "serie_juros", ["data", "modalidade"])

    # dólar mensal.
    dm = dolar_m.rename(columns={"dataHoraCotacao": "mes", "dolar_venda": "cotacao_venda"})
    dm["mes"] = pd.to_datetime(dm["mes"]).dt.normalize()
    _upsert(engine, dm[["mes", "cotacao_venda"]], "dolar_mensal", ["mes"])

    # dólar diário. Normaliza a data para o DIA (remove a hora): o CSV pode ter
    # timestamps diferentes no mesmo dia, que colidiriam ao virar coluna DATE.
    dd = dolar_diario.rename(columns={"dataHoraCotacao": "data",
                                      "cotacaoCompra": "cotacao_compra",
                                      "cotacaoVenda": "cotacao_venda"})
    dd["data"] = pd.to_datetime(dd["data"]).dt.normalize()
    _upsert(engine, dd[["data", "cotacao_compra", "cotacao_venda"]],
            "dolar_diario", ["data"])

    # ranking atual (snapshot — substitui tudo).
    rk = ranking.rename(columns={"InicioPeriodo": "inicio_periodo",
                                 "FimPeriodo": "fim_periodo",
                                 "InstituicaoFinanceira": "instituicao",
                                 "TaxaJurosAoAno": "taxa_aa"})
    # datas vêm como texto no CSV/DataFrame; converte para date (senão o
    # Postgres recusa texto numa coluna DATE).
    rk["inicio_periodo"] = pd.to_datetime(rk["inicio_periodo"]).dt.normalize()
    rk["fim_periodo"]    = pd.to_datetime(rk["fim_periodo"]).dt.normalize()
    _substituir(engine, rk[["instituicao", "inicio_periodo", "fim_periodo", "taxa_aa"]],
                "ranking_veiculos")

    # histórico acumulado (upsert por período+instituição).
    hist = historico.rename(columns={"InicioPeriodo": "inicio_periodo",
                                     "FimPeriodo": "fim_periodo",
                                     "InstituicaoFinanceira": "instituicao",
                                     "TaxaJurosAoAno": "taxa_aa"})
    hist["inicio_periodo"] = pd.to_datetime(hist["inicio_periodo"]).dt.normalize()
    hist["fim_periodo"]    = pd.to_datetime(hist["fim_periodo"]).dt.normalize()
    _upsert(engine, hist[["inicio_periodo", "instituicao", "fim_periodo", "taxa_aa"]],
            "historico_ranking", ["inicio_periodo", "instituicao"])

    # --- IMÓVEL (por modalidade) ---
    renomear_imovel = {"InicioPeriodo": "inicio_periodo", "FimPeriodo": "fim_periodo",
                       "Modalidade": "modalidade", "InstituicaoFinanceira": "instituicao",
                       "TaxaJurosAoAno": "taxa_aa"}
    if ranking_imovel is not None and not ranking_imovel.empty:
        ri = ranking_imovel.rename(columns=renomear_imovel)
        ri["inicio_periodo"] = pd.to_datetime(ri["inicio_periodo"]).dt.normalize()
        ri["fim_periodo"]    = pd.to_datetime(ri["fim_periodo"]).dt.normalize()
        _substituir(engine, ri[["modalidade", "instituicao", "inicio_periodo",
                                "fim_periodo", "taxa_aa"]], "ranking_imovel")
    if historico_imovel is not None and not historico_imovel.empty:
        hi = historico_imovel.rename(columns=renomear_imovel)
        hi["inicio_periodo"] = pd.to_datetime(hi["inicio_periodo"]).dt.normalize()
        hi["fim_periodo"]    = pd.to_datetime(hi["fim_periodo"]).dt.normalize()
        _upsert(engine, hi[["inicio_periodo", "modalidade", "instituicao",
                            "fim_periodo", "taxa_aa"]],
                "historico_imovel", ["inicio_periodo", "modalidade", "instituicao"])

    print("[db] Postgres atualizado.")