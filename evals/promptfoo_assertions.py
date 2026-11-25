"""
Assertions em Python e Runner Declarativo do Promptfoo para o Jarvis KPI Bot.

Este módulo cumpre duplo papel:
1. É chamado diretamente pelo CLI `npx promptfoo eval` via `file://promptfoo_assertions.py:get_assert`.
2. Executa em Python puro a leitura e validação completa de `evals/promptfooconfig.yaml`
   (`executar_suite_promptfoo`), permitindo rodar os mesmos testes declarativos dentro do
   `pytest` e do comparador unificado sem exigir download externo em ambientes CI restritos.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml

from evals.dataset_jarvis import CasoAvaliacaoJarvis, construir_golden_dataset
from evals.metricas_jarvis import (
    avaliar_aderencia_dados,
    avaliar_reducao_alucinacao,
    avaliar_regras_texto,
    tem_openai_api_key,
)


def get_assert(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entrypoint padrão de custom Python assertion do Promptfoo (`type: python`).
    Valida os 3 pilares (Aderência aos Dados, Redução de Alucinação e Regras de Texto).
    """
    vars_caso = (context or {}).get("vars", {})
    pergunta = vars_caso.get("pergunta", "")
    ctx_raw = vars_caso.get("contexto_recuperado", [])
    if isinstance(ctx_raw, str):
        contexto_recuperado = [ctx_raw]
    else:
        contexto_recuperado = list(ctx_raw)

    obrigatorios = vars_caso.get("valores_obrigatorios", [])
    proibidos = vars_caso.get("valores_proibidos", [])
    exige_ausencia = bool(vars_caso.get("exige_ausencia_dados", False))
    categoria = vars_caso.get("categoria", "")

    res_aderencia = avaliar_aderencia_dados(
        output_modelo=output,
        contexto_recuperado=contexto_recuperado,
        valores_obrigatorios=obrigatorios if not exige_ausencia else [],
        valores_proibidos=proibidos,
    )
    res_alucinacao = avaliar_reducao_alucinacao(
        pergunta=pergunta,
        output_modelo=output,
        contexto_recuperado=contexto_recuperado,
        exige_ausencia_dados=exige_ausencia,
        valores_proibidos=proibidos,
    )
    res_regras = avaliar_regras_texto(
        output_modelo=output,
        valores_proibidos_texto=proibidos if categoria == "regras_texto" else [],
    )

    aprovado = res_aderencia.aprovado and res_alucinacao.aprovado and res_regras.aprovado
    score_medio = round((res_aderencia.score + res_alucinacao.score + res_regras.score) / 3, 2)
    motivos = (
        f"Aderência={res_aderencia.score} ({res_aderencia.motivo}) | "
        f"Anti-Alucinação={res_alucinacao.score} ({res_alucinacao.motivo}) | "
        f"RegrasTexto={res_regras.score} ({res_regras.motivo})"
    )

    return {
        "pass": aprovado,
        "score": score_medio,
        "reason": motivos,
        "componentResults": [
            {"pass": res_aderencia.aprovado, "score": res_aderencia.score, "reason": res_aderencia.motivo},
            {"pass": res_alucinacao.aprovado, "score": res_alucinacao.score, "reason": res_alucinacao.motivo},
            {"pass": res_regras.aprovado, "score": res_regras.score, "reason": res_regras.motivo},
        ],
    }


def _avaliar_assertion_declarativa(assertion: Dict[str, Any], output: str, context: Dict[str, Any]) -> tuple[bool, str]:
    """Avalia uma assertion individual declarada no `promptfooconfig.yaml`."""
    tipo = assertion.get("type", "")
    valor = str(assertion.get("value", ""))

    if tipo == "regex":
        ok = bool(re.search(valor, output))
        return ok, f"regex('{valor}') -> {'OK' if ok else 'FALHOU'}"
    if tipo == "icontains":
        ok = valor.lower() in output.lower()
        return ok, f"icontains('{valor}') -> {'OK' if ok else 'FALHOU'}"
    if tipo == "not-icontains":
        ok = valor.lower() not in output.lower()
        return ok, f"not-icontains('{valor}') -> {'OK' if ok else 'FALHOU'}"
    if tipo == "python":
        res = get_assert(output, context)
        return bool(res["pass"]), str(res["reason"])
    return True, f"assertion '{tipo}' ignorada"


def executar_suite_promptfoo(
    casos: List[CasoAvaliacaoJarvis] | None = None,
    caminho_yaml: Path | None = None,
) -> Dict[str, Any]:
    """
    Carrega a configuração declarativa `evals/promptfooconfig.yaml`, executa todas as
    `defaultTest.assert` (regras globais de persona/segurança) e as assertions específicas
    de cada caso do Golden Dataset, e retorna o relatório estruturado.
    """
    inicio = time.perf_counter()
    yaml_path = caminho_yaml or (Path(__file__).resolve().parent / "promptfooconfig.yaml")
    config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    default_asserts = config.get("defaultTest", {}).get("assert", [])
    testes_yaml = {t.get("vars", {}).get("id"): t for t in config.get("tests", [])}

    dataset = casos or construir_golden_dataset()
    resultados_casos: List[Dict[str, Any]] = []
    acertos_classificacao = 0

    for caso in dataset:
        teste_cfg = testes_yaml.get(caso.id, {})
        asserts_caso = list(default_asserts) + list(teste_cfg.get("assert", []))
        contexto_pf = {
            "vars": {
                "id": caso.id,
                "pergunta": caso.pergunta,
                "categoria": caso.categoria,
                "contexto_recuperado": caso.contexto_recuperado,
                "output_modelo": caso.output_modelo,
                "valores_obrigatorios": caso.valores_obrigatorios,
                "valores_proibidos": caso.valores_proibidos,
                "exige_ausencia_dados": caso.exige_ausencia_dados,
            }
        }

        detalhes_asserts = []
        todos_passaram = True
        for a in asserts_caso:
            ok, msg = _avaliar_assertion_declarativa(a, caso.output_modelo, contexto_pf)
            detalhes_asserts.append({"type": a.get("type"), "pass": ok, "reason": msg})
            if not ok:
                todos_passaram = False

        res_py = get_assert(caso.output_modelo, contexto_pf)
        comps = res_py["componentResults"]

        aprovado_geral = todos_passaram and bool(res_py["pass"])
        classificacao_correta = aprovado_geral == caso.esperado_aprovado
        if classificacao_correta:
            acertos_classificacao += 1

        resultados_casos.append(
            {
                "id": caso.id,
                "ct_referencia": caso.ct_referencia,
                "categoria": caso.categoria,
                "esperado_aprovado": caso.esperado_aprovado,
                "aprovado_obtido": aprovado_geral,
                "detectou_corretamente": classificacao_correta,
                "total_assertions_yaml": len(asserts_caso),
                "scores": {
                    "aderencia_dados": comps[0]["score"],
                    "reducao_alucinacao": comps[1]["score"],
                    "regras_texto": comps[2]["score"],
                },
                "motivos": {
                    "aderencia_dados": comps[0]["reason"],
                    "reducao_alucinacao": comps[1]["reason"],
                    "regras_texto": comps[2]["reason"],
                },
                "assertions_yaml": detalhes_asserts,
            }
        )

    duracao_ms = round((time.perf_counter() - inicio) * 1000, 2)
    return {
        "ferramenta": "Promptfoo",
        "versao": "YAML Declarativo + Python Assertions",
        "modo": "declarativo_hibrido",
        "arquivo_config": str(yaml_path.name),
        "total_casos": len(dataset),
        "acertos_deteccao": acertos_classificacao,
        "acuracia_deteccao": round(acertos_classificacao / max(len(dataset), 1), 4),
        "tempo_execucao_ms": duracao_ms,
        "casos": resultados_casos,
    }


if __name__ == "__main__":
    rel = executar_suite_promptfoo()
    print(f"=== Promptfoo ({rel['arquivo_config']}) ===")
    print(
        f"Casos avaliados: {rel['total_casos']} | "
        f"Acurácia de detecção (PASS/FAIL): {rel['acuracia_deteccao']*100:.1f}% | "
        f"Tempo: {rel['tempo_execucao_ms']} ms"
    )
    for c in rel["casos"]:
        status = "PASS" if c["aprovado_obtido"] else "FAIL"
        esperado = "PASS" if c["esperado_aprovado"] else "FAIL"
        check = "OK" if c["detectou_corretamente"] else "DIVERGENTE"
        print(
            f"  [{c['id']}] ({c['categoria']}) -> Obtido: {status} | Esperado: {esperado} [{check}] "
            f"| Assertions YAML: {c['total_assertions_yaml']} | Scores: {c['scores']}"
        )
