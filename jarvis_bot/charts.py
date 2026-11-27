"""
Renderização isolada e validada de gráficos na Sandbox Python.
- Valida `EstruturaGrafico` antes de executar (sem truncar tamanhos divergentes em silêncio — DEF-009).
- Gera nomes únicos com `uuid4` evitando colisão concorrente.
- Não copia arquivos `.db` desnecessários durante a plotagem.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from jarvis_bot.config import obter_config
from jarvis_bot.schemas import EstruturaGrafico
from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox

logger = logging.getLogger("jarvis.charts")


class ErroRenderizacaoGrafico(RuntimeError):
    """Exceção controlada para falhas na geração de gráficos."""


def criar_grafico_sandbox(
    dados: EstruturaGrafico,
    pasta_saida: Path | str | None = None,
    timeout_segundos: int = 15,
) -> str:
    """
    Valida `dados` via `EstruturaGrafico` e renderiza o PNG em subprocesso isolado na Sandbox.
    Retorna o caminho absoluto do arquivo `.png` gerado.
    """
    dados_validados = (
        dados
        if isinstance(dados, EstruturaGrafico)
        else EstruturaGrafico.model_validate(dados)
    )

    destino_dir = Path(pasta_saida) if pasta_saida else obter_config().pasta_charts
    nome_arquivo = f"grafico_jarvis_{uuid.uuid4().hex[:12]}.png"

    codigo_grafico = f"""
import numpy as np

tipo = {repr(dados_validados.tipo)}
titulo = {repr(dados_validados.titulo)}
rotulos_x = {repr(dados_validados.rotulos_x)}
valores_y = {repr(dados_validados.valores_y)}
label_x = {repr(dados_validados.label_eixo_x)}
label_y = {repr(dados_validados.label_eixo_y)}

plt.figure(figsize=(8.5, 5.2))
plt.style.use('ggplot')

if tipo == "barra":
    plt.bar(rotulos_x, valores_y, color='#1f77b4', edgecolor='black', alpha=0.88)
    plt.xlabel(label_x or "Categorias")
    plt.ylabel(label_y or "Valores")
    plt.xticks(rotation=20, ha='right')

elif tipo == "linha":
    plt.plot(rotulos_x, valores_y, marker='o', color='#2ca02c', linewidth=2.5, markersize=6)
    plt.xlabel(label_x or "Período")
    plt.ylabel(label_y or "Valores")
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.xticks(rotation=20, ha='right')

elif tipo == "pizza":
    num_fatias = len(valores_y)
    cores = plt.cm.tab10(np.linspace(0, 1, max(num_fatias, 1)))
    explode = [0.03] * num_fatias
    plt.pie(
        valores_y,
        labels=rotulos_x,
        autopct='%1.1f%%',
        startangle=140,
        colors=cores,
        explode=explode,
        wedgeprops={{"edgecolor": "white", "linewidth": 1.5}},
    )

plt.title(titulo, fontsize=12, fontweight='bold', pad=15)
plt.tight_layout()
plt.savefig({repr(nome_arquivo)}, dpi=160)
plt.close()
"""
    logger.info("Renderizando gráfico '%s' (%s) na Sandbox...", dados_validados.titulo, dados_validados.tipo)
    res_sandbox = executar_codigo_sandbox(
        codigo_python=codigo_grafico,
        caminho_banco=None,
        pasta_saida_graficos=str(destino_dir),
        timeout_segundos=timeout_segundos,
    )

    if not res_sandbox["sucesso"] or not res_sandbox["grafico_gerado"]:
        logger.error(
            "Falha ao renderizar gráfico na Sandbox: erro=%s | detalhe=%s",
            res_sandbox.get("erro"),
            res_sandbox.get("erro_interno", ""),
        )
        raise ErroRenderizacaoGrafico(
            "Não foi possível gerar a visualização gráfica solicitada no momento."
        )

    return str(res_sandbox["grafico_gerado"])


def remover_grafico_seguro(caminho_imagem: str | Path | None) -> None:
    """Remove o arquivo `.png` temporário após o envio ao Telegram (DEF-016)."""
    if not caminho_imagem:
        return
    try:
        p = Path(caminho_imagem)
        if p.exists() and p.is_file():
            p.unlink()
    except OSError as exc:
        logger.warning("Não foi possível remover gráfico temporário %s: %s", caminho_imagem, exc)
