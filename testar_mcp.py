import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def testar():
    # Define a inicialização do servidor local como subprocesso via stdio
    parametros_servidor = StdioServerParameters(
        command="python",
        args=["servidor_mcp_banco.py"],
        env=None
    )

    print("Conectando ao servidor MCP...")
    async with stdio_client(parametros_servidor) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            # 1. Inicializa a comunicação MCP
            await sessao.initialize()
            print("Sessão MCP estabelecida com sucesso!\n")

            # 2. Lista as ferramentas registadas no servidor
            resposta_ferramentas = await sessao.list_tools()
            nomes_ferramentas = [ferramenta.name for ferramenta in resposta_ferramentas.tools]
            print(f"Ferramentas detetadas pelo MCP: {nomes_ferramentas}\n")

            # 3. Testa a ferramenta de listar tabelas
            print("Executando a ferramenta 'listar_tabelas':")
            res_tabelas = await sessao.call_tool("listar_tabelas", arguments={})
            print(res_tabelas.content[0].text, "\n")

            # 4. Testa a ferramenta de descrever o esquema de uma tabela
            print("Executando a ferramenta 'obter_esquema_tabela' para 'vendas_lojas':")
            res_esquema = await sessao.call_tool("obter_esquema_tabela", arguments={"nome_tabela": "vendas_lojas"})
            print(res_esquema.content[0].text, "\n")

            # 5. Testa a execução de uma consulta SQL real de teste
            print("Executando consulta SQL via MCP:")
            res_sql = await sessao.call_tool(
                "executar_consulta_sql",
                arguments={"query": "SELECT loja, AVG(valor_venda) as media FROM vendas_lojas WHERE linha_produto = 'Casual' GROUP BY loja;"}
            )
            print("Resultado da base de dados:")
            print(res_sql.content[0].text)

if __name__ == "__main__":
    asyncio.run(testar())
