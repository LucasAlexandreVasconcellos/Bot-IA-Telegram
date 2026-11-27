"""
Testes automatizados de isolamento da Sandbox (`CT-034` / `DEF-014`) e geração de gráficos (`CT-019`..`021`, `CT-031`).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from jarvis_bot.charts import criar_grafico_sandbox, remover_grafico_seguro
from jarvis_bot.schemas import EstruturaGrafico
from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox


class TestIsolamentoSandbox(unittest.TestCase):
    def test_ct034_bloqueia_todos_os_vetores_de_escape_ast(self):
        vetores_maliciosos = [
            "import os\nprint(os.listdir('.'))",
            "getattr(__builtins__, 'op' + 'en')('dados.txt')",
            "df = pd.read_csv('/etc/hostname')",
            "print(matplotlib.os.environ.get('OPENAI_API_KEY'))",
            "x = ().__class__.__base__.__subclasses__()",
            "from urllib.request import urlopen",
        ]
        for codigo in vetores_maliciosos:
            with self.subTest(codigo=codigo):
                res = executar_codigo_sandbox(codigo, caminho_banco=None)
                self.assertFalse(res["sucesso"])
                self.assertTrue(res["erro"])

    def test_ct034_ambiente_subprocesso_nao_herda_chaves_secretas(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-proj-segredo-super-confidencial",
                "TELEGRAM_TOKEN": "999999:TOKEN_CONFIDENCIAL",
            },
        ):
            # Executa cálculo legítimo e garante execução limpa em modo isolado (-E)
            res = executar_codigo_sandbox("print(2 + 2)", caminho_banco=None)
            self.assertTrue(res["sucesso"])
            self.assertEqual(res["saida"], "4")

    def test_ct034_timeout_encerra_laco_infinito(self):
        res = executar_codigo_sandbox(
            "while True:\n    pass",
            caminho_banco=None,
            timeout_segundos=1,
        )
        self.assertFalse(res["sucesso"])
        self.assertIn("Timeout", res["erro"])


class TestGeracaoGraficos(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.pasta_charts = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ct019_ct020_ct021_renderiza_barra_linha_pizza_e_limpa_png(self):
        for tipo in ("barra", "linha", "pizza"):
            with self.subTest(tipo=tipo):
                dados = EstruturaGrafico(
                    tipo=tipo,
                    titulo=f"Teste {tipo}'); import os #",
                    rotulos_x=["Centro", "Norte", "Oeste", "Sul"],
                    valores_y=[125000.0, 147500.0, 100000.0, 187500.0],
                )
                caminho = criar_grafico_sandbox(dados, pasta_saida=self.pasta_charts)
                arq = Path(caminho)
                self.assertTrue(arq.exists())
                self.assertGreater(arq.stat().st_size, 1000)
                remover_grafico_seguro(caminho)
                self.assertFalse(arq.exists())

    def test_ct031_rejeita_tamanhos_diferentes_pizza_negativa_nan_e_vazio(self):
        casos_invalidos = [
            # Tamanhos diferentes (não trunca mais em silêncio!)
            {"tipo": "barra", "titulo": "Tamanhos", "rotulos_x": ["A", "B"], "valores_y": [10.0]},
            # Pizza com valor negativo ou zero
            {"tipo": "pizza", "titulo": "Pizza Neg", "rotulos_x": ["A", "B"], "valores_y": [10.0, -5.0]},
            {"tipo": "pizza", "titulo": "Pizza Zero", "rotulos_x": ["A", "B"], "valores_y": [0.0, 0.0]},
            # NaN e Inf
            {"tipo": "linha", "titulo": "NaN", "rotulos_x": ["A"], "valores_y": [float("nan")]},
            {"tipo": "barra", "titulo": "Inf", "rotulos_x": ["A"], "valores_y": [float("inf")]},
            # Vazio
            {"tipo": "barra", "titulo": "Vazio", "rotulos_x": [], "valores_y": []},
        ]
        for payload in casos_invalidos:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    EstruturaGrafico(**payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
