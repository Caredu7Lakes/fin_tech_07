# fin_tech_07

Coleta automatizada de dados financeiros do Banco Central, com atualização
diária via GitHub Actions e arquivos versionados no repositório.

## O que coleta

O projeto tem **duas naturezas de dado**, em saídas separadas:

### A) Séries temporais mensais (mesma base de tempo, comparáveis)

| Item | Fonte | Código | Unidade | Saída |
|---|---|---|---|---|
| Imobiliário PF | SGS | 20772 | % a.a. | `serie_imobiliario.csv/.png` |
| Veículos PF (média de mercado) | SGS | 20749 | % a.a. | `serie_veiculos.csv/.png` |
| Dólar (venda) | PTAX | — | R$ | `dolar.csv` (diário) + `serie_dolar_mensal.csv` |

Mais um gráfico combinado das três na mesma base mensal: `series_combinado.png`
(juros no eixo esquerdo em % a.a., dólar no eixo direito em R$).

### B) Ranking — foto do momento (janela separada)

| Item | Fonte | Saída |
|---|---|---|
| Veículos PF — 36 menores taxas por instituição | OData (recursos livres) | `ranking_veiculos.csv/.png` |

O dólar é diário e **incremental** (o CSV cresce). As séries SGS e o ranking são
**refeitos** a cada execução.

## Por que fontes diferentes

- A coleção OData `TaxasJurosDiariaPorInicioPeriodo` cobre só crédito com
  **recursos livres** — por isso serve ao **ranking** de veículos (tem lista de
  instituições). O **imobiliário** é crédito **direcionado** (regulado pelo CMN)
  e não está nela; sua taxa vem da série **SGS 20772**.
- Para o gráfico combinado "na mesma base", veículos também entra como série
  mensal (**SGS 20749**). O ranking por instituição continua existindo à parte.

## Três APIs, três formatos de data

- **OData de juros** — recusa `$filter` (retorna 400); o filtro PF+veículos é
  feito no pandas, sobre páginas obtidas via `$select` + `$skip`.
- **SGS** — datas `DD/MM/AAAA` no retorno.
- **PTAX** — datas `MM-DD-AAAA` na chamada.

## Estrutura

```
fin_tech_07/
├── coleta_bcb.py                     # script principal
├── inspecionar.py                    # confere nomes de campo da OData (rodar 1x)
├── requirements.txt
├── dados/                            # CSVs e PNGs versionados (gerados)
└── .github/workflows/coleta-bcb.yml  # agendamento diário (02:00 BRT)
```

## Antes do primeiro uso

```bash
pip install -r requirements.txt
python inspecionar.py     # confirma Segmento / Modalidade / campos da OData
```

Se algum nome divergir, ajuste as constantes `CAMPO_*`, `SEGMENTO_PF` e
`MODALIDADE_VEIC` no topo de `coleta_bcb.py`. É o único ponto de ajuste de schema.

## Rodar manualmente

```bash
python coleta_bcb.py
```

## Agendamento

Roda todo dia às **05:00 UTC (02:00 BRT)** e pode ser disparado à mão em
**Actions → Coleta BCB diária → Run workflow**.

- O cron do GitHub é em UTC e pode atrasar alguns minutos — normal.
- A PTAX não publica cotação em fins de semana e feriados.
- As séries SGS saem até ~4 semanas após o mês de referência (dado mensal).

## Defaults assumidos (fáceis de trocar)

- **Dólar mensal:** média do mês (`resample("MS").mean()`). Para fechamento de
  fim de mês, troque `.mean()` por `.last()` em `dolar_mensal`.
- **"Janela" do ranking:** arquivo PNG separado (`ranking_veiculos.png`). O
  projeto é um pipeline de dados; uma interface interativa seria outra etapa.