"""
Configuração centralizada, resolução segura de caminhos e logging estruturado do Jarvis KPI Bot.
Compatível tanto com `python-dotenv` quanto com ambientes Python stdlib puros.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

RAIZ_PROJETO: Path = Path(__file__).resolve().parent.parent


def carregar_env_arquivo(caminho_env: Path | None = None) -> None:
    """Carrega variáveis do `.env` usando `python-dotenv` ou parser stdlib de fallback."""
    alvo = caminho_env or (RAIZ_PROJETO / ".env")
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=alvo)
        return
    except ImportError:
        pass

    if not alvo.exists():
        return
    for linha in alvo.read_text(encoding="utf-8", errors="replace").splitlines():
        texto = linha.strip()
        if not texto or texto.startswith("#") or "=" not in texto:
            continue
        chave, valor = texto.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


carregar_env_arquivo()

_LOGGING_CONFIGURADO = False


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Configura logging estruturado uma única vez sem sobrescrever handlers existentes."""
    global _LOGGING_CONFIGURADO
    if _LOGGING_CONFIGURADO:
        return
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=nivel,
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    _LOGGING_CONFIGURADO = True


def _parse_bool(valor: str | None, padrao: bool = True) -> bool:
    if valor is None or valor.strip() == "":
        return padrao
    return valor.strip().lower() in ("1", "true", "yes", "sim", "on")


def _parse_allowed_users(valor: str | None) -> frozenset[int]:
    if not valor or not valor.strip():
        return frozenset()
    ids: set[int] = set()
    for parte in valor.split(","):
        limpo = parte.strip()
        if not limpo:
            continue
        try:
            ids.add(int(limpo))
        except ValueError:
            logging.getLogger("jarvis.config").warning(
                "ID de usuário Telegram inválido ignorado em TELEGRAM_ALLOWED_USER_IDS: %r",
                limpo,
            )
    return frozenset(ids)


@dataclass(frozen=True)
class ConfiguracaoJarvis:
    """Parâmetros imutáveis carregados do ambiente em tempo de execução."""

    telegram_token: str
    openai_api_key: str
    openai_model: str
    openai_timeout_seconds: float
    database_url: str
    caminho_sqlite: Path
    pasta_charts: Path
    use_mcp: bool
    allowed_user_ids: frozenset[int]
    rate_limit_per_minute: int
    chat_history_max_turns: int
    chat_history_ttl_seconds: int

    @property
    def eh_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    def validar_credenciais_bot(self) -> None:
        """Garante fail-fast na inicialização do bot caso credenciais críticas faltem."""
        faltantes = []
        if not self.telegram_token:
            faltantes.append("TELEGRAM_TOKEN")
        if not self.openai_api_key:
            faltantes.append("OPENAI_API_KEY")
        if faltantes:
            raise RuntimeError(
                f"Variáveis obrigatórias ausentes no ambiente/.env: {', '.join(faltantes)}. "
                "Copie `.env.example` para `.env` e configure suas chaves."
            )


def resolver_caminho_sqlite(database_url: str, padrao: Path | None = None) -> Path:
    """Converte URL `sqlite:///...` ou caminho simples em `Path` absoluto ancorado na raiz."""
    base_padrao = padrao or (RAIZ_PROJETO / "sandbox_jarvis.db")
    if not database_url or database_url.startswith(("postgres://", "postgresql://")):
        return base_padrao
    if database_url.startswith("sqlite:///"):
        raw = database_url[len("sqlite:///") :]
        caminho = Path(raw)
    else:
        caminho = Path(database_url)
    if not caminho.is_absolute():
        caminho = (RAIZ_PROJETO / caminho).resolve()
    return caminho


def obter_config() -> ConfiguracaoJarvis:
    """Lê as variáveis de ambiente atuais e retorna uma instância validada de configuração."""
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    caminho_sqlite = resolver_caminho_sqlite(db_url)
    if not db_url:
        db_url = f"sqlite:///{caminho_sqlite.as_posix()}"

    pasta_charts_env = (os.getenv("JARVIS_CHARTS_DIR") or "").strip()
    pasta_charts = (
        Path(pasta_charts_env).resolve()
        if pasta_charts_env
        else (RAIZ_PROJETO / "charts")
    )

    return ConfiguracaoJarvis(
        telegram_token=(os.getenv("TELEGRAM_TOKEN") or "").strip(),
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
        openai_model=(os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip(),
        openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS") or "20"),
        database_url=db_url,
        caminho_sqlite=caminho_sqlite,
        pasta_charts=pasta_charts,
        use_mcp=_parse_bool(os.getenv("USE_MCP"), padrao=True),
        allowed_user_ids=_parse_allowed_users(os.getenv("TELEGRAM_ALLOWED_USER_IDS")),
        rate_limit_per_minute=max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE") or "12")),
        chat_history_max_turns=max(1, int(os.getenv("CHAT_HISTORY_MAX_TURNS") or "5")),
        chat_history_ttl_seconds=max(60, int(os.getenv("CHAT_HISTORY_TTL_SECONDS") or "1800")),
    )
