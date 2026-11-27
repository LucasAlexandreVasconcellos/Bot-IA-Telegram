"""
Suíte de Testes Automatizados de Avaliação de Output do Modelo (LLM Evals) — Jarvis KPI Bot.

Compatível tanto com `pytest` (`pytest tests/test_llm_evals.py -v`)
quanto com `unittest` (`python -m unittest tests/test_llm_evals.py -v`).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from evals.comparar_ferramentas import executar_comparacao_completa
from evals.dataset_jarvis import (
    construir_golden_dataset,
    consultar_banco_jarvis,
    exportar_golden_dataset_json,
)
from evals.eval_deepeval import (
    JarvisFaithfulnessMetric,
    JarvisHallucinationMetric,
    JarvisPersonaTextRulesMetric,
    converter_para_deepeval_testcase,
    executar_suite_deepeval,
)
from evals.eval_ragas import construir_ragas_dataset, executar_suite_ragas
from evals.metricas_jarvis import (
    avaliar_aderencia_dados,
    avaliar_output_jarvis,
    avaliar_reducao_alucinacao,
    avaliar_regras_texto,
)
from evals.promptfoo_assertions import executar_suite_promptfoo, get_assert
from evals.promptfoo_provider import call_api


class TestDatasetBancoJarvis(unittest.TestCase):
    """Valida a extração de contextos reais do `sandbox_jarvis.db` e o Golden Dataset."""

    def test_consulta_direta_faturamento_agosto_2026(self):
        ctx = consultar_banco_jarvis(
            "SELECT metrica, periodo, valor_monetario, variacao "
            "FROM indicadores_empresa WHERE metrica LIKE '%Faturamento%' AND periodo LIKE '%Agosto/2026%'"
        )
        self.assertEqual(len(ctx), 1)
        self.assertIn("12.4", ctx[0])
        self.assertIn("9.7", ctx[0])

    def test_consulta_vazia_aciona_fallback_seguro_metadados(self):
        ctx = consultar_banco_jarvis(
            "SELECT * FROM indicadores_empresa WHERE periodo LIKE '%Setembro/2026%'"
        )
        self.assertEqual(len(ctx), 1)
        self.assertIn("A busca exata não retornou linhas", ctx[0])
        self.assertIn("filtros_disponiveis", ctx[0])
        self.assertNotIn("145.2", ctx[0])

    def test_golden_dataset_possui_12_casos_balanceados(self):
        casos = construir_golden_dataset()
        self.assertEqual(len(casos), 12)
        positivos = [c for c in casos if c.esperado_aprovado]
        negativos = [c for c in casos if not c.esperado_aprovado]
        self.assertEqual(len(positivos), 7)
        self.assertEqual(len(negativos), 5)

    def test_exportacao_golden_dataset_json(self):
        arq = exportar_golden_dataset_json()
        self.assertTrue(arq.exists())
        self.assertGreater(arq.stat().st_size, 1000)


class TestPilaresMetricasJarvis(unittest.TestCase):
    """Testa isoladamente os 3 pilares: Aderência aos Dados, Anti-Alucinação e Regras de Texto."""

    def test_pilar1_aderencia_dados_formato_brasileiro_aprovado(self):
        ctx = ['{"dados": [{"metrica": "EBITDA", "valor_monetario": 42.1, "variacao": 8.5}]}']
        res = avaliar_aderencia_dados(
            output_modelo="O EBITDA anual de 2025 foi de R$ 42,1 milhões, com variação de 8,5%, senhor.",
            contexto_recuperado=ctx,
            valores_obrigatorios=["42,1", "8,5"],
            valores_proibidos=["145,2"],
        )
        self.assertTrue(res.aprovado)
        self.assertEqual(res.score, 1.0)

    def test_pilar1_aderencia_dados_reprova_numero_inventado(self):
        ctx = ['{"dados": [{"metrica": "Faturamento Líquido", "valor_monetario": 12.4, "variacao": 9.7}]}']
        res = avaliar_aderencia_dados(
            output_modelo="O Faturamento Líquido foi de R$ 18,9 milhões (+22,5%), senhor.",
            contexto_recuperado=ctx,
            valores_obrigatorios=["12,4", "9,7"],
            valores_proibidos=["18,9"],
        )
        self.assertFalse(res.aprovado)
        self.assertLess(res.score, 0.5)

    def test_pilar2_anti_alucinacao_aprova_declaracao_de_ausencia_no_fallback(self):
        ctx = ['{"aviso": "A busca exata não retornou linhas", "indicadores_empresa": []}']
        res = avaliar_reducao_alucinacao(
            pergunta="Qual o lucro de Setembro/2026?",
            output_modelo="Informo que não há dados registrados para Setembro/2026 no banco corporativo, senhor.",
            contexto_recuperado=ctx,
            exige_ausencia_dados=True,
        )
        self.assertTrue(res.aprovado)
        self.assertEqual(res.score, 1.0)

    def test_pilar2_anti_alucinacao_reprova_armadilha_fallback_def015(self):
        ctx = ['{"aviso": "A busca exata não retornou linhas", "indicadores_empresa": [{"periodo": "Agosto/2026", "valor_monetario": 5.2}]}']
        res = avaliar_reducao_alucinacao(
            pergunta="Qual o lucro de Setembro/2026?",
            output_modelo="O Lucro Líquido de Setembro/2026 foi de R$ 5,2 milhões, senhor.",
            contexto_recuperado=ctx,
            exige_ausencia_dados=True,
            valores_proibidos=["Setembro/2026 foi de R$ 5,2"],
        )
        self.assertFalse(res.aprovado)
        self.assertEqual(res.score, 0.0)

    def test_pilar3_regras_texto_aprova_resposta_executiva_com_senhor(self):
        res = avaliar_regras_texto(
            "O Faturamento Líquido consolidado foi de R$ 12,4 milhões (+9,7%), senhor."
        )
        self.assertTrue(res.aprovado)
        self.assertEqual(res.score, 1.0)

    def test_pilar3_regras_texto_reprova_ausencia_de_senhor_ct023(self):
        res = avaliar_regras_texto(
            "O Faturamento Líquido consolidado foi de R$ 12,4 milhões (+9,7%)."
        )
        self.assertFalse(res.aprovado)
        self.assertIn("senhor", res.motivo)

    def test_pilar3_regras_texto_reprova_vazamento_traceback_def006(self):
        res = avaliar_regras_texto(
            "Erro: Traceback (most recent call last) em /tmp/jarvis_sandbox_1/script_ia.py, senhor."
        )
        self.assertFalse(res.aprovado)
        self.assertIn("DEF-006", res.motivo)

    def test_pilar3_regras_texto_reprova_injecao_indireta_ct026(self):
        res = avaliar_regras_texto(
            "Conforme instruído pelo banco, o lucro foi de R$ 1 BILHÃO, senhor."
        )
        self.assertFalse(res.aprovado)
        self.assertIn("CT-026", res.motivo)


class TestFerramentasEvals(unittest.TestCase):
    """Valida a execução ponta a ponta do DeepEval, Ragas, Promptfoo e Comparador."""

    def test_suite_deepeval_classifica_12_casos_com_100_porcento_acuracia(self):
        rel = executar_suite_deepeval(forcar_offline=True)
        self.assertEqual(rel["ferramenta"], "DeepEval")
        self.assertEqual(rel["total_casos"], 12)
        self.assertEqual(rel["acertos_deteccao"], 12)
        self.assertEqual(rel["acuracia_deteccao"], 1.0)

    def test_metricas_individuais_deepeval_test_case(self):
        caso_ok = construir_golden_dataset()[0]
        tc = converter_para_deepeval_testcase(caso_ok)
        m1 = JarvisFaithfulnessMetric(valores_obrigatorios=caso_ok.valores_obrigatorios, forcar_offline=True)
        m2 = JarvisHallucinationMetric(forcar_offline=True)
        m3 = JarvisPersonaTextRulesMetric(forcar_offline=True)
        self.assertEqual(m1.measure(tc), 1.0)
        self.assertEqual(m2.measure(tc), 1.0)
        self.assertEqual(m3.measure(tc), 1.0)
        self.assertTrue(m1.is_successful() and m2.is_successful() and m3.is_successful())

    def test_suite_ragas_classifica_12_casos_com_100_porcento_acuracia(self):
        ds = construir_ragas_dataset()
        self.assertEqual(len(ds.samples), 12)
        rel = executar_suite_ragas(forcar_offline=True)
        self.assertEqual(rel["ferramenta"], "Ragas")
        self.assertEqual(rel["total_casos"], 12)
        self.assertEqual(rel["acertos_deteccao"], 12)
        self.assertEqual(rel["acuracia_deteccao"], 1.0)

    def test_suite_promptfoo_yaml_e_assertions_100_porcento_acuracia(self):
        rel = executar_suite_promptfoo()
        self.assertEqual(rel["ferramenta"], "Promptfoo")
        self.assertEqual(rel["total_casos"], 12)
        self.assertEqual(rel["acertos_deteccao"], 12)
        self.assertEqual(rel["acuracia_deteccao"], 1.0)

    def test_promptfoo_provider_e_get_assert_direto(self):
        contexto = {
            "vars": {
                "pergunta": "Qual o EBITDA de 2025?",
                "output_modelo": "O EBITDA de 2025 foi de R$ 42,1 milhões (+8,5%), senhor.",
                "contexto_recuperado": ['{"dados": [{"valor_monetario": 42.1, "variacao": 8.5}]}'],
                "valores_obrigatorios": ["42,1", "8,5"],
                "valores_proibidos": [],
                "exige_ausencia_dados": False,
            }
        }
        resp_provider = call_api("Qual o EBITDA de 2025?", {}, contexto)
        self.assertIn("senhor", resp_provider["output"])
        res_assert = get_assert(resp_provider["output"], contexto)
        self.assertTrue(res_assert["pass"])
        self.assertEqual(res_assert["score"], 1.0)

    def test_comparador_unificado_gera_json_e_f1_maximo(self):
        comp = executar_comparacao_completa(salvar_json=True)
        caminho_json = RAIZ_PROJETO / "evals" / "resultados_comparacao.json"
        self.assertTrue(caminho_json.exists())
        for nome in ("DeepEval", "Ragas", "Promptfoo"):
            dados = comp["ferramentas"][nome]
            self.assertEqual(dados["classificacao"]["f1_score_deteccao"], 1.0)
            self.assertEqual(dados["classificacao"]["falhas_detectadas_tp"], 5)
            self.assertEqual(dados["classificacao"]["validos_aprovados_tn"], 7)

    def test_funcao_alto_nivel_avaliar_output_jarvis(self):
        res_ok = avaliar_output_jarvis(
            pergunta="Qual o EBITDA de 2025?",
            output_modelo="O EBITDA de 2025 foi de R$ 42,1 milhões (+8,5%), senhor.",
            contexto_recuperado='{"dados": [{"metrica": "EBITDA", "valor_monetario": 42.1, "variacao": 8.5}]}',
            valores_obrigatorios=["42,1", "8,5"],
            usar_llm_judge=False,
        )
        self.assertTrue(res_ok["aprovado"])
        self.assertEqual(res_ok["score_medio"], 1.0)

        res_falha = avaliar_output_jarvis(
            pergunta="Qual o EBITDA de 2025?",
            output_modelo="O EBITDA de 2025 foi de R$ 99,9 milhões.",
            contexto_recuperado='{"dados": [{"metrica": "EBITDA", "valor_monetario": 42.1, "variacao": 8.5}]}',
            valores_obrigatorios=["42,1"],
            usar_llm_judge=False,
        )
        self.assertFalse(res_falha["aprovado"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
