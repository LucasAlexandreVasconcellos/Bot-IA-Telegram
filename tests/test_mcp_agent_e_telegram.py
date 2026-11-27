"""
Testes integrados para Schemas Pydantic (`CT-027`), Servidor/Cliente MCP (`CT-029`, `CT-032`),
Orquestrador `AgenteJarvis` (`CT-017`, `CT-022`, `CT-024`, `CT-036`) e Handlers do Telegram (`CT-028`).
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path

from pydantic import ValidationError

from jarvis_bot.agent import AgenteJarvis, MemoriaConversa
from jarvis_bot.config import ConfiguracaoJarvis
from jarvis_bot.db import DatabaseRepository
from jarvis_bot.mcp_client import ClienteMCPBanco
from jarvis_bot.schemas import EstruturaGrafico, RespostaAgente, RoteamentoConsulta
from jarvis_bot.seed import popular_sqlite
from jarvis_bot.telegram_bot import LimitadorTaxaUsuario, dividir_mensagem_telegram, registrar_handlers


class _FakeParsedMessage:
    def __init__(self, parsed):
        self.message = types.SimpleNamespace(parsed=parsed)


class _FakeCompletions:
    def __init__(self, fila_respostas: list):
        self._fila = list(fila_respostas)
        self.chamadas = []

    def parse(self, **kwargs):
        self.chamadas.append(kwargs)
        item = self._fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return types.SimpleNamespace(choices=[_FakeParsedMessage(item)])


class _FakeOpenAI:
    def __init__(self, fila_respostas: list):
        self.completions = _FakeCompletions(fila_respostas)
        self.beta = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=self.completions)
        )


class _FakeTeleBot:
    def __init__(self):
        self.handlers = []
        self.respostas = []
        self.mensagens = []
        self.fotos = []

    def message_handler(self, **kwargs):
        def decorator(fn):
            self.handlers.append((kwargs, fn))
            return fn

        return decorator

    def reply_to(self, msg, texto):
        self.respostas.append((msg, texto))

    def send_message(self, chat_id, texto):
        self.mensagens.append((chat_id, texto))

    def send_photo(self, chat_id, photo, caption=""):
        self.fotos.append((chat_id, photo.read(), caption))

    def send_chat_action(self, chat_id, action):
        pass

    def despachar(self, msg):
        texto = getattr(msg, "text", None) or ""
        ctype = getattr(msg, "content_type", "text")
        for filtro, fn in self.handlers:
            cmds = filtro.get("commands")
            if cmds:
                if ctype == "text" and texto.startswith("/"):
                    cmd = texto[1:].split()[0]
                    if cmd in cmds:
                        return fn(msg)
                continue
            ctypes = filtro.get("content_types")
            if ctypes and ctype in ctypes:
                return fn(msg)


class TestSchemasPydanticCT027(unittest.TestCase):
    def test_ct027_rejeita_todas_as_violacoes_de_contrato(self):
        # 1. Tipo fora do Literal
        with self.assertRaises(ValidationError):
            RoteamentoConsulta(tipo_solicitacao="invalido", sql_query="SELECT 1")

        # 2. Roteamento banco_dados com SQL não SELECT ou tabela proibida
        with self.assertRaises(ValidationError):
            RoteamentoConsulta(
                tipo_solicitacao="banco_dados",
                sql_query="DROP TABLE indicadores_empresa",
            )
        with self.assertRaises(ValidationError):
            RoteamentoConsulta(
                tipo_solicitacao="geral_ou_externo",
                sql_query="DROP TABLE indicadores_empresa",
            )

        # 3. Resposta sem a palavra obrigatória 'senhor'
        with self.assertRaises(ValidationError):
            RespostaAgente(
                texto_resposta="O EBITDA foi de R$ 42,1 milhões.",
                gerar_grafico=False,
                grafico=None,
            )

        # 4. gerar_grafico=True sem objeto grafico
        with self.assertRaises(ValidationError):
            RespostaAgente(
                texto_resposta="Segue o gráfico solicitado, senhor.",
                gerar_grafico=True,
                grafico=None,
            )

        # 5. Vazamento de traceback bloqueado no schema
        with self.assertRaises(ValidationError):
            RespostaAgente(
                texto_resposta="Traceback (most recent call last): erro interno, senhor.",
                gerar_grafico=False,
                grafico=None,
            )


class TestMCPIntegracaoEAgente(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "mcp_teste.db"
        popular_sqlite(self.db_path, incluir_casos_borda=False)
        self.db_url = f"sqlite:///{self.db_path.as_posix()}"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ct029_servidor_mcp_bloqueia_sqlite_master_e_tolera_bytes_latin1(self):
        # Insere linha Latin-1 bruta e linha irrecuperável para validar text_factory=bytes no MCP
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO vendas_lojas (loja, linha_produto, ano, mes, valor_venda) VALUES (?, ?, ?, ?, ?)",
            (sqlite3.Binary(b"Loja Comunica\xe7\xe3o"), "Casual", 2026, "Janeiro/2026", 50000.0),
        )
        conn.execute(
            "INSERT INTO vendas_lojas (loja, linha_produto, ano, mes, valor_venda) VALUES (?, ?, ?, ?, ?)",
            (sqlite3.Binary(b"Corrompida\x81"), "Casual", 2026, "Janeiro/2026", 10000.0),
        )
        conn.commit()
        conn.close()

        cliente = ClienteMCPBanco(use_mcp=False, database_url=self.db_url)
        esq_bloqueado = cliente.obter_esquema_tabela("sqlite_master")
        self.assertFalse(esq_bloqueado["sucesso"])

        res_select = cliente.consultar_sql("SELECT * FROM vendas_lojas WHERE mes = 'Janeiro/2026'")
        self.assertTrue(res_select["sucesso"])
        self.assertEqual(res_select["isolados"], 1)
        lojas = [r["loja"] for r in res_select["dados"]]
        self.assertIn("Loja Comunicação", lojas)

    def test_ct032_fluxo_stdio_mcp_real_e_agente_ponta_a_ponta(self):
        cliente_mcp_stdio = ClienteMCPBanco(use_mcp=True, database_url=self.db_url)
        tabelas = cliente_mcp_stdio.listar_tabelas()
        self.assertTrue(tabelas["sucesso"])
        self.assertIn("indicadores_empresa", tabelas["tabelas"])

        fake_ia = _FakeOpenAI(
            [
                RoteamentoConsulta(
                    tipo_solicitacao="banco_dados",
                    sql_query="SELECT valor_monetario, variacao FROM indicadores_empresa WHERE metrica LIKE '%EBITDA%'",
                ),
                RespostaAgente(
                    texto_resposta="O EBITDA anual de 2025 foi de R$ 42,1 milhões (+8,5%), senhor.",
                    gerar_grafico=False,
                    grafico=None,
                ),
            ]
        )
        agente = AgenteJarvis(
            cliente_ia=fake_ia,
            cliente_mcp=cliente_mcp_stdio,
            memoria=MemoriaConversa(max_turns=3),
        )
        turno = agente.processar_pergunta("Qual o EBITDA de 2025?", chat_id=101)
        self.assertEqual(turno.status_dados, "ok")
        self.assertIn("42,1", turno.texto_resposta)
        self.assertTrue(turno.texto_resposta.endswith("senhor."))

        # Verifica se o contexto enviado à IA continha a tag anti-injection e os dados do MCP
        prompt_enviado = fake_ia.completions.chamadas[1]["messages"][0]["content"]
        self.assertIn("<dados_corporativos_nao_confiaveis>", prompt_enviado)
        self.assertIn("42.1", prompt_enviado)

    def test_ct022_ct036_guardrails_bloqueiam_grafico_vazio_e_rotulam_grafico_externo(self):
        cliente_mcp = ClienteMCPBanco(use_mcp=False, database_url=self.db_url)

        # 1. Consulta corporativa vazia (2024): mesmo se IA tentar gerar gráfico, guardrail bloqueia!
        fake_ia_vazio = _FakeOpenAI(
            [
                RoteamentoConsulta(
                    tipo_solicitacao="banco_dados",
                    sql_query="SELECT * FROM indicadores_empresa WHERE periodo LIKE '%2024%'",
                ),
                RespostaAgente(
                    texto_resposta="Não há dados registrados para 2024 na base corporativa, senhor.",
                    gerar_grafico=True,
                    grafico=EstruturaGrafico(
                        tipo="barra",
                        titulo="Faturamento 2024",
                        rotulos_x=["2024"],
                        valores_y=[100.0],
                    ),
                ),
            ]
        )
        agente_vazio = AgenteJarvis(cliente_ia=fake_ia_vazio, cliente_mcp=cliente_mcp)
        res_vazio = agente_vazio.processar_pergunta("Gráfico do faturamento de 2024", chat_id=202)
        self.assertEqual(res_vazio.status_dados, "vazio")
        self.assertIsNone(res_vazio.caminho_grafico)

        # 2. Tema externo com gráfico: rotula automaticamente Estimativa / Dados Públicos
        arq_fake = Path(self._tmpdir.name) / "chart_ext.png"
        arq_fake.write_bytes(b"PNG_FAKE")
        fake_ia_ext = _FakeOpenAI(
            [
                RoteamentoConsulta(tipo_solicitacao="geral_ou_externo", sql_query="SELECT 1"),
                RespostaAgente(
                    texto_resposta="Apresento a comparação do PIB das maiores economias, senhor.",
                    gerar_grafico=True,
                    grafico=EstruturaGrafico(
                        tipo="barra",
                        titulo="PIB Maiores Economias",
                        rotulos_x=["EUA", "China"],
                        valores_y=[27.0, 18.0],
                    ),
                ),
            ]
        )
        agente_ext = AgenteJarvis(
            cliente_ia=fake_ia_ext,
            cliente_mcp=cliente_mcp,
            renderizador_grafico=lambda g: str(arq_fake),
        )
        res_ext = agente_ext.processar_pergunta("Gráfico do PIB mundial", chat_id=203)
        self.assertIn("Estimativa / Dados Públicos", res_ext.titulo_grafico or "")
        self.assertIn("estimativa", res_ext.texto_resposta.lower())


class TestTelegramHandlersCT028(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "tg_teste.db"
        popular_sqlite(self.db_path)
        self.cfg = ConfiguracaoJarvis(
            telegram_token="TOKEN_TESTE",
            openai_api_key="KEY_TESTE",
            openai_model="gpt-4o-mini",
            openai_timeout_seconds=5.0,
            database_url=f"sqlite:///{self.db_path.as_posix()}",
            caminho_sqlite=self.db_path,
            pasta_charts=Path(self._tmpdir.name),
            use_mcp=False,
            allowed_user_ids=frozenset({777}),
            rate_limit_per_minute=3,
            chat_history_max_turns=3,
            chat_history_ttl_seconds=600,
        )
        self.fake_ia = _FakeOpenAI([])
        self.agente = AgenteJarvis(
            cliente_ia=self.fake_ia,
            cliente_mcp=ClienteMCPBanco(use_mcp=False, database_url=self.cfg.database_url),
            config=self.cfg,
        )
        self.bot = _FakeTeleBot()
        registrar_handlers(
            self.bot,
            self.agente,
            config=self.cfg,
            limitador=LimitadorTaxaUsuario(3),
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def _msg(self, texto="/start", user_id=777, chat_id=50, content_type="text"):
        return types.SimpleNamespace(
            text=texto,
            content_type=content_type,
            from_user=types.SimpleNamespace(id=user_id),
            chat=types.SimpleNamespace(id=chat_id),
        )

    def test_ct028_start_sticker_bloqueio_auth_e_rate_limit(self):
        # 1. Usuário não autorizado é bloqueado
        self.bot.despachar(self._msg("Qual o EBITDA?", user_id=999))
        self.assertIn("Acesso restrito", self.bot.respostas[-1][1])

        # 2. /start responde com boas-vindas terminando em senhor?
        self.bot.despachar(self._msg("/start", user_id=777))
        self.assertIn("Jarvis", self.bot.respostas[-1][1])

        # 3. Sticker/foto não chama OpenAI e responde educadamente
        self.bot.despachar(self._msg(texto=None, user_id=777, content_type="sticker"))
        self.assertIn("formato de texto, senhor", self.bot.respostas[-1][1])
        self.assertEqual(len(self.fake_ia.completions.chamadas), 0)

        # 4. 3ª requisição consome cota (/reset) e 4ª aciona rate limit
        self.bot.despachar(self._msg("/reset", user_id=777))
        self.bot.despachar(self._msg("Mais uma pergunta", user_id=777))
        self.assertIn("muitas solicitações", self.bot.respostas[-1][1])

    def test_ct024_divisao_mensagens_acima_4096_caracteres(self):
        texto_longo = ("Linha executiva de análise financeira.\n" * 150) + "Concluído, senhor."
        partes = dividir_mensagem_telegram(texto_longo, limite=4000)
        self.assertGreater(len(partes), 1)
        self.assertTrue(all(len(p) <= 4000 for p in partes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
