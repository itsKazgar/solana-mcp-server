from fastmcp import FastMCP, Context
from .tools_extra import (
    fetch_trending_pumpfun,
    fetch_token_price_jupiter,
    fetch_wallet_tokens,
    fetch_sol_balance,
    fetch_token_metadata,
    rug_check as _rug_check,
    get_transaction_history as _get_tx_history,
    search_tokens_by_name,
)
from .config import settings
from .turnkey_client import turnkey_client


def register_extra_tools(mcp: FastMCP):

    @mcp.tool(description="Get trending tokens on Pump.fun right now, sorted by recent activity. Always run rug_check before trading.")
    async def get_trending_pumpfun_tokens(ctx: Context, limit: int = 20) -> dict:
        tokens = await fetch_trending_pumpfun(min(limit, 50))
        return {"status": "ok", "count": len(tokens), "tokens": tokens}

    @mcp.tool(description="Get current USD price of any Solana token from Jupiter price API.")
    async def get_token_price(ctx: Context, mint_address: str) -> dict:
        price = await fetch_token_price_jupiter(mint_address)
        if not price:
            return {"status": "error", "error": "Price not found"}
        return {"status": "ok", **price}

    @mcp.tool(description="Get token metadata: name, symbol, market cap, bonding curve %, graduation status.")
    async def get_token_info(ctx: Context, mint_address: str) -> dict:
        info = await fetch_token_metadata(mint_address)
        return {"status": "ok", **info}

    @mcp.tool(description="Search Pump.fun tokens by name or symbol. Use when you know the name but not the mint address.")
    async def search_tokens(ctx: Context, query: str, limit: int = 10) -> dict:
        results = await search_tokens_by_name(query, limit)
        return {"status": "ok", "query": query, "count": len(results), "results": results}

    @mcp.tool(description="Rug pull risk check. Checks mint authority, freeze authority, top holder concentration. ALWAYS run before buying.")
    async def rug_check(ctx: Context, mint_address: str) -> dict:
        return await _rug_check(mint_address)

    @mcp.tool(description="Get all SPL token balances in the trading wallet.")
    async def get_wallet_tokens(ctx: Context) -> dict:
        wallet = turnkey_client.wallet_address
        if not wallet:
            return {"status": "error", "error": "Wallet not configured"}
        tokens = await fetch_wallet_tokens(wallet)
        return {"status": "ok", "wallet": wallet, "token_count": len(tokens), "tokens": tokens}

    @mcp.tool(description="Get SOL balance of the trading wallet.")
    async def get_sol_balance(ctx: Context) -> dict:
        wallet = turnkey_client.wallet_address
        if not wallet:
            return {"status": "error", "error": "Wallet not configured"}
        balance = await fetch_sol_balance(wallet)
        return {"status": "ok", "wallet": wallet, "sol_balance": balance, "network": settings.solana_network}

    @mcp.tool(description="Get recent transaction history for the trading wallet.")
    async def get_transaction_history(ctx: Context, limit: int = 20) -> dict:
        wallet = turnkey_client.wallet_address
        if not wallet:
            return {"status": "error", "error": "Wallet not configured"}
        txs = await _get_tx_history(wallet, min(limit, 50))
        return {"status": "ok", "wallet": wallet, "count": len(txs), "transactions": txs}
