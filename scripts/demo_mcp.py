"""
Script de demonstração da integração cliente-servidor via protocolo MCP (`stdio`).
Execute: `python scripts/demo_mcp.py`
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))


async def demonstrar_mcp() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parametros_servidor = StdioServerParameters(
        command=sys.executable,
        args=[str(RAIZ_PROJETO / "servidor_mcp_banco.py")],
        env=None,
    )

    print("Conectando ao servidor MCP...")
    async with stdio_client(parametros_servidor) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()
            print("Sessão MCP estabelecida com sucesso!\n")

            resposta_ferramentas = await sessao.list_tools()
            nomes_ferramentas = [f.name for f in resposta_ferramentas.tools]
            print(f"Ferramentas detectadas pelo MCP: {nomes_ferramentas}\n")

            res_tabelas = await sessao.call_tool("listar_tabelas", arguments={})
            print("Tabelas:", res_tabelas.content[0].text, "\n")

            res_esquema = await sessao.call_tool(
                "obter_esquema_tabela", arguments={"nome_tabela": "vendas_lojas"}
            )
            print("Esquema vendas_lojas:", res_esquema.content[0].text, "\n")

            res_sql = await sessao.call_tool(
                "executar_consulta_sql",
                arguments={
                    "query": (
                        "SELECT loja, AVG(valor_venda) AS media_venda "
                        "FROM vendas_lojas WHERE linha_produto = 'Casual' GROUP BY loja;"
                    )
                },
            )
            print("Resultado SQL sanitizado:")
            print(res_sql.content[0].text)


if __name__ == "__main__":
    asyncio.run(demonstrar_mcp())
