# fin_tech_07

> **Pergunta de negócio:** onde está o crédito de veículos mais barato hoje, e
> como o custo de crédito (imóvel e veículos) se move em relação ao dólar?
>
> **Provocação (fase 2):** o próximo impacto é o endividamento das famílias —
> como esses custos de crédito se traduzem em comprometimento de renda?


Coleta automatizada de dados financeiros do Banco Central, com atualização
diária via GitHub Actions, arquivos versionados no repositório e alertas por
e-mail quando indicadores cruzam limiares definidos.

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

### B) Ranking de veículos (OData de recursos livres) — duas visões

| Visão | Saída | Natureza |
|---|---|---|
| Foto da semana atual — 36 menores taxas por instituição | `ranking_veiculos.csv/.png` | Reescrita a cada execução |
| Histórico — taxa por instituição ao longo do tempo | `historico_ranking_veiculos.csv` | **Acumula, nunca descarta** |

## Preservação de dados

- **Dólar** — incremental; `dolar.csv` cresce, nada é perdido.
- **Séries SGS** — o BC serve o histórico inteiro a cada chamada; regravar não perde nada.
- **Ranking (foto)** — `ranking_veiculos.csv` é a semana atual (foto).
- **Histórico do ranking** — `historico_ranking_veiculos.csv` acumula a taxa por
  instituição a cada semana, deduplicando por (período + instituição). Nunca
  descarta o passado.

## Alertas por e-mail

Dispara e-mail (Apple SMTP, 587/STARTTLS) **só quando um indicador cruza o
limiar** — ao entrar e ao sair da condição, não todo dia. Limiares em `alertas.py`:

| Indicador | Condição |
|---|---|
| Veículos (ranking) — menor taxa | < 4,00% a.a. |
| Veículos (ranking) — maior taxa | > 33,00% a.a. |
| Imóvel (SGS 20772) | < 12,00% a.a. |
| Dólar (PTAX venda) | < R$ 4,90 |

O estado do cruzamento fica em `dados/estado_alertas.json` (versionado), para o
código lembrar, entre execuções, se cada condição já estava ativa.

### Credenciais (secrets)

Configuradas em **Settings → Secrets and variables → Actions**:

- `EMAIL_USER` — e-mail Apple completo (remetente).
- `EMAIL_PASSWORD` — senha de app (appleid.apple.com → Segurança), não a senha normal.
- `EMAIL_TO` — opcional; se ausente, envia para o próprio `EMAIL_USER`.

Localmente, defina as mesmas variáveis de ambiente antes de rodar.

## Robustez

Todas as chamadas HTTP usam retry (4 tentativas, 10s de espera, timeout 120s),
porque a API do BC às vezes fica lenta de madrugada — sem isso, um timeout
passageiro derrubaria a coleta agendada.

## Três APIs, três formatos de data

- **OData de juros** — recusa `$filter` (400); o filtro PF+veículos é feito no
  pandas, sobre páginas obtidas via `$select` + `$skip`.
- **SGS** — datas `DD/MM/AAAA` no retorno.
- **PTAX** — datas `MM-DD-AAAA` na chamada.

## Banco de dados (Postgres)

Além dos CSVs versionados, o pipeline grava as tabelas num **Postgres
gerenciado** (camada de consulta que o dashboard lê). Papéis: CSV = histórico
versionado no git; Postgres = consulta.

Conexão via `DATABASE_URL` (secret no GitHub e, depois, no Streamlit Cloud).
Escrita **idempotente** por UPSERT (`ON CONFLICT DO UPDATE`); o ranking atual é
um snapshot (tabela substituída a cada execução). Tabelas: `serie_juros`
(imóvel+veículos, formato longo), `dolar_mensal`, `dolar_diario`,
`ranking_veiculos` (snapshot) e `historico_ranking` (acumulado).

Sem `DATABASE_URL` definida, o pipeline segue normal e só os CSVs são gerados.

## Estrutura

```
fin_tech_07/
├── coleta_bcb.py                     # script principal (coleta + gráficos + alertas)
├── alertas.py                        # e-mail por cruzamento de limiar (Apple SMTP)
├── db.py                             # camada Postgres (schema + upsert)
├── inspecionar.py                    # confere campos da OData (rodar 1x)
├── requirements.txt
├── .gitignore
├── dados/                            # CSVs, PNGs e estado — versionados (gerados)
└── .github/workflows/coleta-bcb.yml  # agendamento diário (02:00 BRT)
```

## Rodar manualmente

```bash
pip install -r requirements.txt
python inspecionar.py     # 1ª vez: confirma Segmento/Modalidade/campos da OData
python coleta_bcb.py
```

## Agendamento

Roda todo dia às **05:00 UTC (02:00 BRT)** e pode ser disparado à mão em
**Actions → Coleta BCB diária → Run workflow**.

- Cron do GitHub é em UTC e pode atrasar alguns minutos — normal.
- PTAX não publica cotação em fins de semana e feriados.
- Séries SGS saem até ~4 semanas após o mês de referência.

## Defaults assumidos (fáceis de trocar)

- **Dólar mensal:** média do mês (`resample("MS").mean()`). Para fechamento de
  fim de mês, troque `.mean()` por `.last()` em `dolar_mensal`.
- **"Janela" do ranking:** arquivo PNG separado. O projeto é um pipeline de
  dados; uma interface interativa seria outra etapa.