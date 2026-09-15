"""
fin_tech_07 — Alertas por e-mail (Apple SMTP)
=============================================

Dispara e-mail quando um indicador CRUZA um limiar — ou seja, só quando MUDA
de estado (de "dentro" para "fora", ou vice-versa). Não manda e-mail todo dia
enquanto continua fora; manda uma vez quando entra na condição e outra quando
sai. Isso evita spam e mantém o alerta legível.

Limiares monitorados:
  - Veículos (ranking): MENOR taxa < 4,00% a.a.  (surgiu oferta excepcional)
  - Veículos (ranking): MAIOR taxa > 33,00% a.a. (apareceu banco muito caro)
  - Imóvel (SGS 20772): taxa < 12,00% a.a.
  - Dólar (PTAX venda): < R$ 4,90

Estado do cruzamento fica em dados/estado_alertas.json (versionado no repo),
para o código lembrar, entre execuções, se cada condição já estava ativa.

Credenciais vêm de variáveis de ambiente (secrets no GitHub Actions), nunca no
código: EMAIL_USER, EMAIL_PASSWORD e, opcional, EMAIL_TO (destino; se ausente,
envia para o próprio EMAIL_USER).

Apple SMTP tem duas pegadinhas já tratadas aqui:
  - porta 587 é STARTTLS (SMTP + starttls), não SSL direto;
  - o usuário no SMTP é o e-mail COMPLETO.
"""

import os
import json
import smtplib
from email.message import EmailMessage


# ===========================================================================
#  CONFIGURAÇÃO
# ===========================================================================

# --- Limiares (ajuste aqui) ---
LIMITE_VEIC_MIN = 4.0     # veículos: alerta se MENOR taxa do ranking < 4,00% a.a.
LIMITE_VEIC_MAX = 33.0    # veículos: alerta se MAIOR taxa do ranking > 33,00% a.a.
LIMITE_IMOVEL   = 12.0    # imóvel:   alerta se taxa < 12,00% a.a.
LIMITE_DOLAR    = 4.90    # dólar:    alerta se venda < R$ 4,90

# --- Apple SMTP ---
SMTP_SERVIDOR = "smtp.mail.me.com"
SMTP_PORTA    = 587       # STARTTLS (não SSL direto)

# --- Arquivo de estado (permite disparar só no cruzamento) ---
ARQ_ESTADO = os.path.join("dados", "estado_alertas.json")


# ===========================================================================
#  ENVIO DE E-MAIL
# ===========================================================================

def _enviar_email(assunto, corpo):
    """
    Envia um e-mail pelo Apple SMTP (587/STARTTLS). Lê credenciais do ambiente.
    Se EMAIL_USER/EMAIL_PASSWORD não estiverem definidos, apenas avisa e sai —
    assim rodar localmente sem secrets não quebra o pipeline.
    """
    usuario = os.getenv("EMAIL_USER")
    senha   = os.getenv("EMAIL_PASSWORD")
    destino = os.getenv("EMAIL_TO", usuario)      # default: manda para si mesmo

    if not usuario or not senha:
        print("[alertas] EMAIL_USER/EMAIL_PASSWORD ausentes — e-mail não enviado.")
        return

    msg = EmailMessage()
    msg["From"] = usuario                          # Apple: usuário = e-mail completo
    msg["To"] = destino
    msg["Subject"] = assunto
    msg.set_content(corpo)

    with smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA, timeout=30) as smtp:
        smtp.starttls()                            # 587 exige STARTTLS
        smtp.login(usuario, senha)
        smtp.send_message(msg)
    print(f"[alertas] e-mail enviado para {destino}: {assunto}")


# ===========================================================================
#  ESTADO (cruzamento)
# ===========================================================================

def _ler_estado():
    """Lê o estado anterior (quais condições já estavam ativas). {} na 1ª vez."""
    if os.path.exists(ARQ_ESTADO):
        with open(ARQ_ESTADO, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _salvar_estado(estado):
    """Persiste o estado atual para a próxima execução comparar."""
    os.makedirs(os.path.dirname(ARQ_ESTADO), exist_ok=True)
    with open(ARQ_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ===========================================================================
#  VERIFICAÇÃO DE ALERTAS
# ===========================================================================

def verificar_alertas(ranking, imob, dolar_diario):
    """
    Compara os indicadores atuais com os limiares e dispara e-mail SÓ quando uma
    condição muda de estado (cruza o limiar). Recebe:
      - ranking: DataFrame do ranking de veículos (coluna TaxaJurosAoAno);
      - imob: série SGS do imobiliário (coluna 'imobiliario', última linha = atual);
      - dolar_diario: série diária do dólar (coluna 'cotacaoVenda', última = atual).
    """
    # Valores atuais de cada indicador.
    veic_min = float(ranking["TaxaJurosAoAno"].min())
    veic_max = float(ranking["TaxaJurosAoAno"].max())
    imob_atual = float(imob["imobiliario"].iloc[-1])
    dolar_atual = float(dolar_diario["cotacaoVenda"].iloc[-1])

    # Cada condição: nome -> (está ativa agora?, texto para o e-mail).
    condicoes = {
        "veic_min": (veic_min < LIMITE_VEIC_MIN,
                     f"Veículos: menor taxa {veic_min:.2f}% a.a. < {LIMITE_VEIC_MIN:.2f}%"),
        "veic_max": (veic_max > LIMITE_VEIC_MAX,
                     f"Veículos: maior taxa {veic_max:.2f}% a.a. > {LIMITE_VEIC_MAX:.2f}%"),
        "imovel":   (imob_atual < LIMITE_IMOVEL,
                     f"Imóvel: taxa {imob_atual:.2f}% a.a. < {LIMITE_IMOVEL:.2f}%"),
        "dolar":    (dolar_atual < LIMITE_DOLAR,
                     f"Dólar: venda R$ {dolar_atual:.2f} < R$ {LIMITE_DOLAR:.2f}"),
    }

    estado_anterior = _ler_estado()
    estado_atual = {}
    entrou = []    # condições que ACABARAM de entrar (dispara e-mail)
    saiu = []      # condições que ACABARAM de sair  (dispara e-mail)

    for chave, (ativa_agora, texto) in condicoes.items():
        estado_atual[chave] = ativa_agora
        estava_ativa = estado_anterior.get(chave, False)
        if ativa_agora and not estava_ativa:
            entrou.append(texto)                   # cruzou para dentro
        elif not ativa_agora and estava_ativa:
            saiu.append(texto)                     # cruzou para fora

    # Monta e envia um único e-mail com o que mudou (se algo mudou).
    if entrou or saiu:
        linhas = []
        if entrou:
            linhas.append("⚠️ ENTROU na condição de alerta:")
            linhas += [f"  • {t}" for t in entrou]
        if saiu:
            linhas.append("✅ SAIU da condição de alerta:")
            linhas += [f"  • {t}" for t in saiu]
        _enviar_email("fin_tech_07 — alerta de indicadores", "\n".join(linhas))
    else:
        print("[alertas] nenhum cruzamento — nada a enviar.")

    _salvar_estado(estado_atual)                   # grava para a próxima execução