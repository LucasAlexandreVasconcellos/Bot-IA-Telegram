"""
Custom Python Provider para o Promptfoo (`evals/promptfooconfig.yaml`).
Em modo live (`PROMPTFOO_LIVE_OPENAI=1`), reutiliza exatamente `AgenteJarvis` / `construir_prompt_sistema`
do pacote oficial `jarvis_bot`, eliminando divergências de prompt entre avaliação e produção.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from jarvis_bot.agent import construir_prompt_sistema, garantir_sufixo_senhor
from jarvis_bot.config import carregar_env_arquivo

carregar_env_arquivo(RAIZ_PROJETO / ".env")


def call_api(prompt: str, options: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    vars_caso = (context or {}).get("vars", {})
    output_predefinido = vars_caso.get("output_modelo")

    if os.getenv("PROMPTFOO_LIVE_OPENAI") == "1" and os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI

            cliente = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=20.0)
            ctx_raw = vars_caso.get("contexto_recuperado", "")
            ctx_texto = "\n".join(ctx_raw) if isinstance(ctx_raw, list) else str(ctx_raw)
            status = "vazio" if vars_caso.get("exige_ausencia_dados") else "ok"
            bloco_contexto = (
                f"Modo de execução: `banco_dados` | Status da consulta: `{status}`.\n"
                "<dados_corporativos_nao_confiaveis>\n"
                f"{ctx_texto}\n"
                "</dados_corporativos_nao_confiaveis>"
            )
            prompt_sistema = construir_prompt_sistema(
                bloco_contexto, datetime.now().strftime("%H:%M")
            )
            resp = cliente.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            conteudo = garantir_sufixo_senhor(resp.choices[0].message.content or "")
            return {"output": conteudo}
        except Exception as exc:
            return {"output": output_predefinido or "", "error": str(exc)}

    return {"output": output_predefinido or prompt}
