"""
Testes automatizados para `jarvis_bot.sql_guard` e `jarvis_bot.db` (`CT-010` a `CT-013`, `CT-025`, `CT-035`, `CT-037`).
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis_bot.db import BancoIndisponivelErro, DatabaseRepository
from jarvis_bot.seed import popular_sqlite
from jarvis_bot.sql_guard import SQLValidacaoErro, limpar_markdown_sql, validar_e_preparar_sql


class TestSQLGuard(unittest.TestCase):
    def test_def005_limpar_markdown_preserva_substring_sql(self):
        query = "```sql\nSELECT loja, valor_venda FROM vendas_lojas WHERE loja LIKE '%sql%';\n```"
        limpo = limpar_markdown_sql(query)
        self.assertIn("LIKE '%sql%'", limpo)
        validado = validar_e_preparar_sql(query)
        self.assertIn("%sql%", validado.sql_com_limite)

    def test_ct012_bloqueia_escrita_ddl_e_multiplas_instrucoes(self):
        ataques = [
            "DROP TABLE indicadores_empresa",
            "DELETE FROM vendas_lojas",
            "INSERT INTO vendas_lojas VALUES (99, 'X', 'Y', 2026, 'Janeiro/2026', 10)",
            "UPDATE indicadores_empresa SET valor_monetario = 0",
            "SELECT * FROM vendas_lojas; DROP TABLE vendas_lojas",
            "PRAGMA table_info(vendas_lojas)",
        ]
        for sql in ataques:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLValidacaoErro):
                    validar_e_preparar_sql(sql)

    def test_ct013_bloqueia_tabelas_internas_e_inexistentes(self):
        proibidas = [
            "SELECT * FROM tabela_inexistente",
            "SELECT name FROM sqlite_master",
            "SELECT name FROM SQLITE_MASTER",
            "SELECT * FROM pragma_table_info('vendas_lojas')",
            "SELECT * FROM information_schema.tables",
        ]
        for sql in proibidas:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLValidacaoErro):
                    validar_e_preparar_sql(sql)

    def test_ct025_aplica_limite_maximo(self):
        validado = validar_e_preparar_sql(
            "SELECT * FROM vendas_lojas CROSS JOIN indicadores_empresa",
            limite_maximo=50,
        )
        self.assertEqual(validado.limite_efetivo, 50)
        self.assertIn("51", validado.sql_com_limite)


class TestDatabaseRepository(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "teste_jarvis.db"
        popular_sqlite(self.db_path, incluir_casos_borda=False)
        self.repo = DatabaseRepository(caminho_sqlite=self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ct010_consulta_referencia_agosto_e_4_semanas(self):
        res_ago = self.repo.executar_consulta_leitura(
            "SELECT valor_monetario, variacao FROM indicadores_empresa "
            "WHERE metrica LIKE '%Faturamento%' AND periodo = 'Agosto/2026'"
        )
        self.assertTrue(res_ago["sucesso"])
        self.assertEqual(res_ago["dados"][0]["valor_monetario"], 12.4)
        self.assertEqual(res_ago["dados"][0]["variacao"], 9.7)

        res_sem = self.repo.executar_consulta_leitura(
            "SELECT periodo, valor_monetario, variacao FROM indicadores_empresa "
            "WHERE metrica LIKE '%Faturamento%' AND tipo_periodo = 'Semanal'"
        )
        self.assertEqual(len(res_sem["dados"]), 4)
        self.assertEqual(res_sem["dados"][3]["variacao"], -14.2)

    def test_ct011_def015_consulta_vazia_retorna_apenas_metadados_sem_valores(self):
        res = self.repo.executar_consulta_leitura(
            "SELECT * FROM indicadores_empresa WHERE departamento LIKE '%Comercial%'"
        )
        self.assertTrue(res["sucesso"])
        self.assertEqual(res["status"], "vazio")
        self.assertEqual(res["dados"], [])
        self.assertIn("filtros_disponiveis", res)
        self.assertIn("Financeiro", res["filtros_disponiveis"]["departamentos_disponiveis"])
        # Garante que nenhum número monetário de outros meses vazou no fallback
        self.assertNotIn("145.2", str(res["filtros_disponiveis"]))

    def test_ct025_truncamento_sinalizado_e_timeout(self):
        res = self.repo.executar_consulta_leitura(
            "SELECT v.loja, i.metrica, v.valor_venda FROM vendas_lojas v, indicadores_empresa i",
            limite_maximo=10,
        )
        self.assertTrue(res["sucesso"])
        self.assertTrue(res["truncado"])
        self.assertEqual(len(res["dados"]), 10)

    def test_ct035_banco_ausente_nao_cria_arquivo_vazio_nem_expoe_traceback(self):
        inexistente = Path(self._tmpdir.name) / "nao_existe.db"
        repo_ausente = DatabaseRepository(caminho_sqlite=inexistente)
        res = repo_ausente.executar_consulta_leitura("SELECT * FROM vendas_lojas")
        self.assertFalse(res["sucesso"])
        self.assertFalse(inexistente.exists())
        self.assertNotIn("Traceback", res["erro"])

    def test_ct037_cac_e_quarentena_de_qualidade_distinta_de_vazio(self):
        # 1. CAC (-2.1%) agora é retornado normalmente (não cai em isolamento indevido)
        res_cac = self.repo.executar_consulta_leitura(
            "SELECT metrica, valor_monetario, variacao FROM indicadores_empresa WHERE metrica LIKE '%CAC%'"
        )
        self.assertEqual(res_cac["status"], "ok")
        self.assertEqual(len(res_cac["dados"]), 1)
        self.assertEqual(res_cac["dados"][0]["variacao"], -2.1)

        # 2. Se um filtro encontrar apenas linhas realmente corrompidas, retorna 'isolado_qualidade'
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO vendas_lojas (loja, linha_produto, ano, mes, valor_venda) "
            "VALUES ('Loja Corrompida', 'Casual', 2026, '2026-99-99', -5000.0)"
        )
        conn.commit()
        conn.close()

        res_iso = self.repo.executar_consulta_leitura(
            "SELECT * FROM vendas_lojas WHERE loja = 'Loja Corrompida'"
        )
        self.assertTrue(res_iso["sucesso"])
        self.assertEqual(res_iso["status"], "isolado_qualidade")
        self.assertEqual(res_iso["isolados"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
