# src/jupiter.py
import httpx
import base64
import structlog
from typing import Optional

from .config import settings
from .turnkey_client import turnkey_client

log = structlog.get_logger()

# Common token mints
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

class JupiterClient:
    """Jupiter V6 aggregator for best-price Solana swaps."""
    
    def __init__(self):
        self.api_url = settings.jupiter_api_url
    
    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount_lamports: int,
        slippage_bps: int = 50
    ) -> Optional[dict]:
        """Get best swap route from Jupiter."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.api_url}/quote",
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount_lamports,
                    "slippageBps": slippage_bps,
                    "onlyDirectRoutes": False,
                    "asLegacyTransaction": False
                }
            )
            if resp.status_code != 200:
                log.error("jupiter_quote_error", status=resp.status_code, body=resp.text[:200])
                return None
            return resp.json()
    
    async def swap(
        self,
        input_mint: str,
        output_mint: str,
        amount: float,
        slippage_bps: int = 50,
        paper_mode: bool = True,
        amount_in_sol: bool = True
    ) -> dict:
        """
        Execute a swap via Jupiter.
        
        Args:
            input_mint: Input token mint (use SOL_MINT for SOL)
            output_mint: Output token mint  
            amount: Amount to swap (in SOL if amount_in_sol=True, else lamports)
            slippage_bps: Slippage tolerance (50 = 0.5%)
            paper_mode: Simulate only
            amount_in_sol: If True, amount is in SOL; else raw lamports
        """
        amount_lamports = int(amount * 1e9) if amount_in_sol else int(amount)
        
        log.info("jupiter_swap", 
                 input=input_mint[:8], output=output_mint[:8],
                 amount=amount, paper=paper_mode)
        
        if paper_mode:
            return {
                "status": "paper_mode",
                "input_mint": input_mint,
                "output_mint": output_mint,
                "amount_in": amount,
                "message": "Paper mode: swap simulated, not executed"
            }
        
        # Get quote
        quote = await self.get_quote(input_mint, output_mint, amount_lamports, slippage_bps)
        if not quote:
            return {"status": "error", "error": "Could not get Jupiter quote"}
        
        out_amount = int(quote["outAmount"]) / 1e9
        price_impact = float(quote.get("priceImpactPct", 0))
        
        if price_impact > 5.0:
            return {
                "status": "blocked",
                "reason": f"Price impact too high: {price_impact:.2f}%",
                "quote": quote
            }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Build swap transaction
                swap_resp = await client.post(
                    f"{self.api_url}/swap",
                    json={
                        "quoteResponse": quote,
                        "userPublicKey": turnkey_client.wallet_address,
                        "wrapAndUnwrapSol": True,
                        "dynamicComputeUnitLimit": True,
                        "prioritizationFeeLamports": "auto"
                    }
                )
                
                if swap_resp.status_code != 200:
                    return {"status": "error", "error": swap_resp.text[:200]}
                
                swap_data = swap_resp.json()
                tx_bytes = base64.b64decode(swap_data["swapTransaction"])
                
                # Sign via Turnkey
                signed_tx = await turnkey_client.sign_solana_transaction(
                    tx_bytes,
                    note=f"Jupiter swap {amount} {input_mint[:8]}→{output_mint[:8]}"
                )
                
                if not signed_tx:
                    return {"status": "error", "error": "Rejected by Turnkey policy"}
                
                # Broadcast
                tx_sig = await self._broadcast(signed_tx)
                
                return {
                    "status": "success",
                    "input_mint": input_mint,
                    "output_mint": output_mint,
                    "amount_in": amount,
                    "amount_out": out_amount,
                    "price_impact_pct": price_impact,
                    "tx_signature": tx_sig,
                    "explorer": f"https://solscan.io/tx/{tx_sig}"
                }
                
        except Exception as e:
            log.error("jupiter_swap_error", error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def _broadcast(self, signed_tx: str) -> str:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [signed_tx, {
                "encoding": "base64",
                "skipPreflight": False,
                "maxRetries": 3,
                "preflightCommitment": "processed"
            }]
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(settings.solana_rpc_url, json=payload)
            result = resp.json()
            if "error" in result:
                raise Exception(f"RPC broadcast error: {result['error']}")
            return result["result"]

jupiter_client = JupiterClient()
