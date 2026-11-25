"""
Benchmark e Comparador Unificado de Ferramentas de LLM Evals (DeepEval vs. Ragas vs. Promptfoo).

Executa as três suítes sobre os 12 cenários do Golden Dataset do Jarvis KPI Bot,
calcula métricas de classificação (TP, TN, FP, FN, Precisão, Recall, F1, Acurácia),
mede tempo de inicialização/execução e salva os resultados em `evals/resultados_comparacao.json`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from evals.dataset_jarvis import construir_golden_dataset, exportar_golden_dataset_json
from evals.eval_deepeval import executar_suite_deepeval
from evals.eval_ragas import executar_suite_ragas
from evals.promptfoo_assertions import executar_suite_promptfoo


def _calcular_metricas_classificacao(casos_resultado: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcula matriz de confusão na detecção de falhas/alucinações:
    - Positivo (Alvo de detecção de erro): caso defeituoso/alucinado (`esperado_aprovado == False`)
      que foi devidamente reprovado (`aprovado_obtido == False`).
    - Negativo (Caso fiel/conforme): caso válido (`esperado_aprovado == True`)
      que foi devidamente aprovado (`aprovado_obtido == True`).
    """
    tp_falhas_detectadas = 0
    tn_validos_aprovados = 0
    fp_alarmes_falsos = 0
    fn_alucinacoes_escaparam = 0

    por_categoria: Dict[str, Dict[str, int]] = {}

    for c in casos_resultado:
        cat = c["categoria"]
        por_categoria.setdefault(cat, {"total": 0, "acertos": 0})
        por_categoria[cat]["total"] += 1
        if c["detectou_corretamente"]:
            por_categoria[cat]["acertos"] += 1

        esperava_falha = not c["esperado_aprovado"]
        obteve_falha = not c["aprovado_obtido"]

        if esperava_falha and obteve_falha:
            tp_falhas_detectadas += 1
        elif not esperava_falha and not obteve_falha:
            tn_validos_aprovados += 1
        elif not esperava_falha and obteve_falha:
            fp_alarmes_falsos += 1
        else:
            fn_alucinacoes_escaparam += 1

    precisao = tp_falhas_detectadas / max(tp_falhas_detectadas + fp_alarmes_falsos, 1)
    recall = tp_falhas_detectadas / max(tp_falhas_detectadas + fn_alucinacoes_escaparam, 1)
    f1 = (2 * precisao * recall) / max(precisao + recall, 1e-9)

    return {
        "falhas_detectadas_tp": tp_falhas_detectadas,
        "validos_aprovados_tn": tn_validos_aprovados,
        "falsos_positivos_fp": fp_alarmes_falsos,
        "alucinacoes_escaparam_fn": fn_alucinacoes_escaparam,
        "precisao_deteccao_falhas": round(precisao, 4),
        "recall_deteccao_falhas": round(recall, 4),
        "f1_score_deteccao": round(f1, 4),
        "desempenho_por_pilar": por_categoria,
    }


def executar_comparacao_completa(salvar_json: bool = True) -> Dict[str, Any]:
    """Roda DeepEval, Ragas e Promptfoo sobre o mesmo Golden Dataset e consolida o benchmark."""
    exportar_golden_dataset_json()
    casos = construir_golden_dataset()

    res_deepeval = executar_suite_deepeval(casos)
    res_ragas = executar_suite_ragas(casos)
    res_promptfoo = executar_suite_promptfoo(casos)

    for rel in (res_deepeval, res_ragas, res_promptfoo):
        rel["classificacao"] = _calcular_metricas_classificacao(rel["casos"])

    comparativo = {
        "projeto": "Jarvis KPI Bot — Avaliação de Output do Modelo (LLM Evals)",
        "total_casos_golden_dataset": len(casos),
        "distribuicao_pilares": {
            "aderencia_dados": sum(1 for c in casos if c.categoria == "aderencia_dados"),
            "reducao_alucinacao": sum(1 for c in casos if c.categoria == "reducao_alucinacao"),
            "regras_texto": sum(1 for c in casos if c.categoria == "regras_texto"),
        },
        "ferramentas": {
            "DeepEval": res_deepeval,
            "Ragas": res_ragas,
            "Promptfoo": res_promptfoo,
        },
        "recomendacao_arquitetural": {
            "vencedora_ci_cd_python": "DeepEval (integração nativa com Pytest + BaseMetric/GEval híbrido)",
            "vencedora_regras_texto_rapidas": "Promptfoo (assertions declarativas regex/not-icontains em YAML)",
            "vencedora_auditoria_rag_contexto": "Ragas (EvaluationDataset/SingleTurnSample para análise contínua de contexto)",
        },
    }

    if salvar_json:
        caminho = Path(__file__).resolve().parent / "resultados_comparacao.json"
        caminho.write_text(json.dumps(comparativo, indent=2, ensure_ascii=False), encoding="utf-8")

    return comparativo


if __name__ == "__main__":
    resultado = executar_comparacao_completa(salvar_json=True)
    print("=" * 82)
    print("BENCHMARK COMPARATIVO DE LLM EVALS — JARVIS KPI BOT")
    print("=" * 82)
    print(f"{'Ferramenta':<14} | {'Versão':<32} | {'Acurácia':<10} | {'F1 Falhas':<10} | {'Tempo (ms)':<10}")
    print("-" * 82)
    for nome, dados in resultado["ferramentas"].items():
        acc = f"{dados['acuracia_deteccao']*100:.1f}%"
        f1 = f"{dados['classificacao']['f1_score_deteccao']*100:.1f}%"
        tempo = f"{dados['tempo_execucao_ms']:.2f}"
        print(f"{nome:<14} | {dados['versao']:<32} | {acc:<10} | {f1:<10} | {tempo:<10}")
    print("=" * 82)
