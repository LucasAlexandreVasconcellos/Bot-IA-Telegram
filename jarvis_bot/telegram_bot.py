"""
Camada de interface conversacional no Telegram (`pyTelegramBotAPI`).
Implementa:
- Controle de acesso configurável (`TELEGRAM_ALLOWED_USER_IDS`) + aviso de segurança no log.
- Rate-limit por usuário (janela deslizante de 60 segundos).
- Comandos dedicados (`/start`, `/help`, `/reset`, `/meu_id`) e tratamento seguro de mídias não textuais (CT-028).
- Paginação automática de mensagens longas (> 4.000 caracteres) e limpeza automática do PNG enviado (CT-024 / DEF-016).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from jarvis_bot.agent import AgenteJarvis
from jarvis_bot.charts import remover_grafico_seguro
from jarvis_bot.config import ConfiguracaoJarvis, configurar_logging, obter_config

logger = logging.getLogger("jarvis.telegram")

LIMITE_CARACTERES_TELEGRAM = 4000
LIMITE_ENTRADA_USUARIO = 4000

MENSAGEM_BOAS_VINDAS = (
    "Olá! Sou o Jarvis, seu assistente executivo de indicadores corporativos.\n\n"
    "Posso consultar indicadores financeiros, marketing, operações e vendas por loja, "
    "além de gerar gráficos de barras, linhas e pizza.\n\n"
    "Comandos disponíveis:\n"
    "• /help — Exibe orientações de uso\n"
    "• /reset — Limpa o histórico recente desta conversa\n"
    "• /meu_id — Informa seu identificador numérico do Telegram\n\n"
    "Como posso auxiliá-lo hoje, senhor?"
)


class LimitadorTaxaUsuario:
    """Rate limiter thread-safe em janela deslizante de 60 segundos por `user_id`."""

    def __init__(self, max_requisicoes_por_minuto: int = 12) -> None:
        self.max_req = max(1, max_requisicoes_por_minuto)
        self._lock = threading.Lock()
        self._janelas: dict[int, deque[float]] = {}

    def permitir(self, user_id: int) -> bool:
        agora = time.monotonic()
        with self._lock:
            fila = self._janelas.setdefault(user_id, deque())
            while fila and (agora - fila[0] > 60.0):
                fila.popleft()
            if len(fila) >= self.max_req:
                return False
            fila.append(agora)
            return True


def dividir_mensagem_telegram(texto: str, limite: int = LIMITE_CARACTERES_TELEGRAM) -> list[str]:
    """Divide textos longos respeitando quebras de linha e o teto de 4.096 caracteres do Telegram."""
    conteudo = (texto or "").strip()
    if not conteudo:
        return ["Estou à disposição, senhor."]
    if len(conteudo) <= limite:
        return [conteudo]

    partes: list[str] = []
    restante = conteudo
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte <= 0:
            corte = restante.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(restante[:corte].strip())
        restante = restante[corte:].strip()
    if restante:
        partes.append(restante)
    return partes


def usuario_autorizado(user_id: int | None, allowed_ids: frozenset[int]) -> bool:
    if not allowed_ids:
        return True
    if user_id is None:
        return False
    return user_id in allowed_ids


def registrar_handlers(
    bot: Any,
    agente: AgenteJarvis,
    config: ConfiguracaoJarvis | None = None,
    limitador: LimitadorTaxaUsuario | None = None,
) -> None:
    """Registra todos os handlers de comandos, texto e mídias em uma instância `TeleBot`."""
    cfg = config or agente.cfg
    rate_limiter = limitador or LimitadorTaxaUsuario(cfg.rate_limit_per_minute)

    def _extrair_user_id(mensagem: Any) -> int:
        usuario = getattr(mensagem, "from_user", None)
        return int(getattr(usuario, "id", 0) or 0)

    def _checar_acesso_e_taxa(mensagem: Any) -> bool:
        uid = _extrair_user_id(mensagem)
        if not usuario_autorizado(uid, cfg.allowed_user_ids):
            logger.warning("Tentativa de acesso bloqueada para user_id=%s", uid)
            bot.reply_to(
                mensagem,
                "Acesso restrito aos executivos autorizados nesta instância, senhor.",
            )
            return False
        if not rate_limiter.permitir(uid):
            logger.warning("Rate limit atingido por user_id=%s", uid)
            bot.reply_to(
                mensagem,
                "Recebi muitas solicitações consecutivas; aguarde alguns segundos antes de prosseguir, senhor.",
            )
            return False
        return True

    @bot.message_handler(commands=["meu_id"])
    def handler_meu_id(mensagem: Any) -> None:
        uid = _extrair_user_id(mensagem)
        bot.reply_to(
            mensagem,
            f"Seu identificador numérico no Telegram é `{uid}`, senhor.",
        )

    @bot.message_handler(commands=["start", "help"])
    def handler_start_help(mensagem: Any) -> None:
        if not _checar_acesso_e_taxa(mensagem):
            return
        bot.reply_to(mensagem, MENSAGEM_BOAS_VINDAS)

    @bot.message_handler(commands=["reset", "limpar"])
    def handler_reset(mensagem: Any) -> None:
        if not _checar_acesso_e_taxa(mensagem):
            return
        chat_id = int(getattr(getattr(mensagem, "chat", None), "id", 0) or 0)
        agente.memoria.limpar(chat_id)
        bot.reply_to(
            mensagem,
            "O histórico recente da nossa conversa foi reiniciado com sucesso, senhor.",
        )

    @bot.message_handler(
        content_types=[
            "photo",
            "audio",
            "voice",
            "video",
            "document",
            "sticker",
            "location",
            "contact",
            "video_note",
        ]
    )
    def handler_midia_nao_suportada(mensagem: Any) -> None:
        if not _checar_acesso_e_taxa(mensagem):
            return
        bot.reply_to(
            mensagem,
            "No momento analiso apenas solicitações enviadas em formato de texto, senhor.",
        )

    @bot.message_handler(content_types=["text"], func=lambda m: True)
    def handler_texto(mensagem: Any) -> None:
        if not _checar_acesso_e_taxa(mensagem):
            return

        texto_usuario = (getattr(mensagem, "text", None) or "").strip()
        if not texto_usuario:
            bot.reply_to(
                mensagem,
                "Por favor, informe sua pergunta em texto para que eu possa analisá-la, senhor.",
            )
            return

        if len(texto_usuario) > LIMITE_ENTRADA_USUARIO:
            bot.reply_to(
                mensagem,
                f"Sua mensagem excede o limite de {LIMITE_ENTRADA_USUARIO} caracteres; "
                "por gentileza, sintetize a solicitação, senhor.",
            )
            return

        chat_id = int(getattr(getattr(mensagem, "chat", None), "id", 0) or 0)
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass

        resultado = agente.processar_pergunta(texto_usuario, chat_id=chat_id)
        try:
            partes = dividir_mensagem_telegram(resultado.texto_resposta)
            for idx, parte in enumerate(partes):
                if idx == 0:
                    bot.reply_to(mensagem, parte)
                else:
                    bot.send_message(chat_id, parte)

            if resultado.caminho_grafico:
                with open(resultado.caminho_grafico, "rb") as foto:
                    bot.send_photo(
                        chat_id=chat_id,
                        photo=foto,
                        caption=f"📊 {resultado.titulo_grafico or 'Visualização Executiva'}",
                    )
        except Exception as exc:
            logger.exception("Erro ao entregar resposta no Telegram (chat_id=%s): %s", chat_id, exc)
            try:
                bot.reply_to(
                    mensagem,
                    "Ocorreu uma falha de comunicação ao enviar a resposta; tente novamente em instantes, senhor.",
                )
            except Exception:
                pass
        finally:
            remover_grafico_seguro(resultado.caminho_grafico)


def criar_aplicacao_telegram(
    config: ConfiguracaoJarvis | None = None,
) -> tuple[Any, AgenteJarvis]:
    """Valida configuração, instancia `TeleBot` e `AgenteJarvis` e registra handlers."""
    configurar_logging()
    cfg = config or obter_config()
    cfg.validar_credenciais_bot()

    if not cfg.allowed_user_ids:
        logger.warning(
            "TELEGRAM_ALLOWED_USER_IDS está vazio! O bot aceitará mensagens de qualquer usuário "
            "(recomendado definir IDs autorizados em produção)."
        )

    import telebot

    bot = telebot.TeleBot(cfg.telegram_token)
    agente = AgenteJarvis(config=cfg)
    registrar_handlers(bot, agente, config=cfg)
    return bot, agente


def iniciar_bot() -> None:
    bot, cfg_agente = criar_aplicacao_telegram()
    logger.info(
        "Jarvis KPI Bot Online! (MCP=%s | Postgres=%s)",
        cfg_agente.cfg.use_mcp,
        cfg_agente.cfg.eh_postgres,
    )
    bot.infinity_polling(timeout=20, long_polling_timeout=20)


if __name__ == "__main__":
    iniciar_bot()
