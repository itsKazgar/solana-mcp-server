from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

async def run():
    client = MultiServerMCPClient({
        "solana_trader": {
            "url": "http://YOUR_IP:8000/mcp/",
            "transport": "streamable_http",
            "headers": {"Authorization": "Bearer change_this_to_a_strong_random_token_32chars"}
        }
    })
    tools = await client.get_tools()
    model = ChatOllama(model="hermes3")
    agent = create_react_agent(model, tools)
    return agent
