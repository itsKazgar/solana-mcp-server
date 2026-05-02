import httpx
import asyncio
from typing import Optional
import structlog

from .config import settings

log = structlog.get_logger()

async def fetch_trending_pumpfun(limit: int = 20) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://frontend-api.pump.fun/coins",
                params={
                    "offset": 0, "limit": limit,
                    "sort": "last_trade_timestamp", "order": "DESC",
                    "includeNsfw": False
                },
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                coins = resp.json()
                return [{
                    "mint": c.get("mint"),
                    "name": c.get("name"),
                    "symbol": c.get("symbol"),
                    "market_cap_usd": c.get("usd_market_cap", 0),
                    "volume_24h": c.get("volume", 0),
                    "price_usd": c.get("price", 0),
                    "bonding_curve_pct": c.get("bonding_curve_percentage", 0),
                    "created_at": c.get("created_timestamp"),
                    "description": c.get("description", "")[:100],
                    "pump_url": f"https://pump.fun/{c.get('mint')}",
                    "graduated": c.get("complete", False)
                } for c in coins]
    except Exception as e:
        log.error("trending_fetch_error", error=str(e))
    return []

async def fetch_token_price_jupiter(mint: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.jup.ag/price/v2",
                params={"ids": mint, "showExtraInfo": True}
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get(mint, {})
                return {
                    "mint": mint,
                    "price_usd": float(data.get("price", 0)),
                    "buy_price": float(data.get("extraInfo", {}).get("quotedPrice", {}).get("buyPrice", 0)),
                    "sell_price": float(data.get("extraInfo", {}).get("quotedPrice", {}).get("sellPrice", 0)),
                }
    except Exception as e:
        log.error("jupiter_price_error", error=str(e))
    return None

async def fetch_wallet_tokens(wallet_address: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                settings.solana_rpc_url,
                json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        wallet_address,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"}
                    ]
                }
            )
            accounts = resp.json().get("result", {}).get("value", [])
            tokens = []
            for acc in accounts:
                info = acc["account"]["data"]["parsed"]["info"]
                amount = float(info["tokenAmount"]["uiAmount"] or 0)
                if amount > 0:
                    tokens.append({
                        "mint": info["mint"],
                        "balance": amount,
                        "decimals": info["tokenAmount"]["decimals"],
                        "account": acc["pubkey"]
                    })
            return tokens
    except Exception as e:
        log.error("wallet_tokens_error", error=str(e))
    return []

async def fetch_sol_balance(wallet_address: str) -> float:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                settings.solana_rpc_url,
                json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getBalance",
                    "params": [wallet_address]
                }
            )
            lamports = resp.json().get("result", {}).get("value", 0)
            return lamports / 1e9
    except Exception as e:
        log.error("sol_balance_error", error=str(e))
    return 0.0

async def fetch_token_metadata(mint: str) -> dict:
    result = {"mint": mint, "name": "Unknown", "symbol": "???", "source": "none"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"https://frontend-api.pump.fun/coins/{mint}",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                d = resp.json()
                result.update({
                    "name": d.get("name", "Unknown"),
                    "symbol": d.get("symbol", "???"),
                    "description": d.get("description", "")[:200],
                    "market_cap_usd": d.get("usd_market_cap", 0),
                    "bonding_curve_pct": d.get("bonding_curve_percentage", 0),
                    "graduated": d.get("complete", False),
                    "created_at": d.get("created_timestamp"),
                    "pump_url": f"https://pump.fun/{mint}",
                    "source": "pumpfun"
                })
                return result
    except Exception as e:
        log.error("token_metadata_error", error=str(e))
    return result

async def rug_check(mint: str) -> dict:
    risks = []
    score = 0
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.solana_rpc_url,
                json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getAccountInfo",
                    "params": [mint, {"encoding": "jsonParsed"}]
                }
            )
            data = resp.json().get("result", {}).get("value", {})
            if data:
                parsed = data.get("data", {}).get("parsed", {}).get("info", {})
                mint_auth = parsed.get("mintAuthority")
                freeze_auth = parsed.get("freezeAuthority")
                if mint_auth:
                    risks.append("MINT AUTHORITY ACTIVE - devs can print more tokens")
                    score += 30
                if freeze_auth:
                    risks.append("FREEZE AUTHORITY ACTIVE - devs can freeze wallets")
                    score += 25
            holders_resp = await client.post(
                settings.solana_rpc_url,
                json={
                    "jsonrpc": "2.0", "id": 2,
                    "method": "getTokenLargestAccounts",
                    "params": [mint]
                }
            )
            holders = holders_resp.json().get("result", {}).get("value", [])
            if holders:
                total = sum(int(h.get("amount", 0)) for h in holders)
                if total > 0:
                    top1_pct = int(holders[0].get("amount", 0)) / total * 100
                    top5_pct = sum(int(h.get("amount", 0)) for h in holders[:5]) / total * 100
                    if top1_pct > 20:
                        risks.append(f"TOP HOLDER OWNS {top1_pct:.1f}% OF SUPPLY")
                        score += 35
                    elif top1_pct > 10:
                        risks.append(f"TOP HOLDER OWNS {top1_pct:.1f}% - elevated risk")
                        score += 15
                    if top5_pct > 60:
                        risks.append(f"TOP 5 HOLDERS OWN {top5_pct:.1f}% OF SUPPLY")
                        score += 10
    except Exception as e:
        risks.append(f"Could not complete rug check: {str(e)}")
        score = 50
    if score == 0:
        risks.append("No major red flags detected")
    return {
        "mint": mint,
        "risk_score": min(score, 100),
        "risk_level": "HIGH" if score > 60 else "MEDIUM" if score > 30 else "LOW",
        "risks": risks,
        "recommendation": "AVOID" if score > 60 else "CAUTION" if score > 30 else "OK"
    }

async def get_transaction_history(wallet_address: str, limit: int = 20) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.solana_rpc_url,
                json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [wallet_address, {"limit": limit}]
                }
            )
            sigs = resp.json().get("result", [])
            return [{
                "signature": s.get("signature"),
                "slot": s.get("slot"),
                "block_time": s.get("blockTime"),
                "err": s.get("err"),
                "explorer": f"https://solscan.io/tx/{s.get('signature')}"
            } for s in sigs]
    except Exception as e:
        log.error("tx_history_error", error=str(e))
    return []

async def search_tokens_by_name(query: str, limit: int = 10) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://frontend-api.pump.fun/coins",
                params={
                    "offset": 0, "limit": limit,
                    "sort": "market_cap", "order": "DESC",
                    "searchTerm": query, "includeNsfw": False
                },
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if resp.status_code == 200:
                coins = resp.json()
                return [{
                    "mint": c.get("mint"),
                    "name": c.get("name"),
                    "symbol": c.get("symbol"),
                    "market_cap_usd": c.get("usd_market_cap", 0),
                    "pump_url": f"https://pump.fun/{c.get('mint')}",
                    "graduated": c.get("complete", False)
                } for c in coins]
    except Exception as e:
        log.error("token_search_error", error=str(e))
    return []
