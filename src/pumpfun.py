# src/pumpfun.py
import httpx
import json
import base64
import struct
from typing import Optional
import structlog

from .config import settings
from .turnkey_client import turnkey_client

log = structlog.get_logger()

# Pump.fun program constants
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_FUN_GLOBAL = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5zP9QkDnvsEXZrj"
PUMP_FUN_FEE_RECIPIENT = "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM"
PUMP_FUN_EVENT_AUTHORITY = "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"

class PumpFunClient:
    """
    Client for Pump.fun bonding curve trades.
    Uses pumpportal.fun API for transaction building,
    then signs via Turnkey.
    """
    
    def __init__(self):
        self.api_url = settings.pumpfun_api_url
        self.rpc_url = settings.solana_rpc_url
    
    async def buy(
        self,
        mint_address: str,
        sol_amount: float,
        slippage_bps: int = 100,
        paper_mode: bool = True
    ) -> dict:
        """
        Buy a Pump.fun token on the bonding curve.
        
        Args:
            mint_address: Token mint address
            sol_amount: Amount of SOL to spend
            slippage_bps: Slippage tolerance in basis points (100 = 1%)
            paper_mode: If True, simulate only
        """
        log.info("pumpfun_buy", mint=mint_address, sol=sol_amount, paper=paper_mode)
        
        if paper_mode:
            return self._paper_result("buy", mint_address, sol_amount)
        
        try:
            # Use pumpportal.fun lightning API
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get transaction from pumpportal
                response = await client.post(
                    f"{self.api_url}/trade-local",
                    headers={"Content-Type": "application/json"},
                    json={
                        "publicKey": turnkey_client.wallet_address,
                        "action": "buy",
                        "mint": mint_address,
                        "amount": int(sol_amount * 1e9),  # lamports
                        "slippage": slippage_bps / 100,   # percent
                        "priorityFee": 0.005,
                        "pool": "pump"
                    }
                )
                
                if response.status_code != 200:
                    return {"status": "error", "error": f"API error: {response.text[:200]}"}
                
                # Response is raw transaction bytes
                tx_bytes = response.content
                
                # Sign via Turnkey (policy-controlled)
                signed_tx = await turnkey_client.sign_solana_transaction(
                    tx_bytes,
                    note=f"buy {sol_amount} SOL of {mint_address[:8]}"
                )
                
                if not signed_tx:
                    return {"status": "error", "error": "Transaction rejected by Turnkey policy"}
                
                # Broadcast
                tx_sig = await self._broadcast(signed_tx)
                return {
                    "status": "success",
                    "action": "buy",
                    "mint": mint_address,
                    "sol_amount": sol_amount,
                    "tx_signature": tx_sig,
                    "explorer": f"https://solscan.io/tx/{tx_sig}"
                }
                
        except Exception as e:
            log.error("pumpfun_buy_error", error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def sell(
        self,
        mint_address: str,
        token_amount: float,
        slippage_bps: int = 100,
        paper_mode: bool = True
    ) -> dict:
        """Sell a Pump.fun token back to the bonding curve."""
        log.info("pumpfun_sell", mint=mint_address, amount=token_amount, paper=paper_mode)
        
        if paper_mode:
            return self._paper_result("sell", mint_address, token_amount)
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}/trade-local",
                    headers={"Content-Type": "application/json"},
                    json={
                        "publicKey": turnkey_client.wallet_address,
                        "action": "sell",
                        "mint": mint_address,
                        "amount": token_amount,
                        "slippage": slippage_bps / 100,
                        "priorityFee": 0.005,
                        "pool": "pump"
                    }
                )
                
                if response.status_code != 200:
                    return {"status": "error", "error": response.text[:200]}
                
                tx_bytes = response.content
                signed_tx = await turnkey_client.sign_solana_transaction(
                    tx_bytes,
                    note=f"sell {token_amount} of {mint_address[:8]}"
                )
                
                if not signed_tx:
                    return {"status": "error", "error": "Rejected by Turnkey policy"}
                
                tx_sig = await self._broadcast(signed_tx)
                return {
                    "status": "success",
                    "action": "sell",
                    "mint": mint_address,
                    "token_amount": token_amount,
                    "tx_signature": tx_sig,
                    "explorer": f"https://solscan.io/tx/{tx_sig}"
                }
                
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def create_token(
        self,
        name: str,
        symbol: str,
        description: str,
        image_url: str,
        initial_buy_sol: float = 0.0,
        paper_mode: bool = True
    ) -> dict:
        """Create a new Pump.fun token."""
        log.info("pumpfun_create", name=name, symbol=symbol, paper=paper_mode)
        
        if paper_mode:
            import secrets
            fake_mint = "PAPER_" + secrets.token_hex(16)
            return {
                "status": "paper_mode",
                "action": "create",
                "name": name, "symbol": symbol,
                "mint_address": fake_mint,
                "message": "Paper mode: token not actually created"
            }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: Get IPFS metadata uploaded (via pumpportal)
                form_data = {
                    "name": name,
                    "symbol": symbol,
                    "description": description,
                    "showName": "true"
                }
                # Download and reupload image
                img_resp = await client.get(image_url)
                
                meta_resp = await client.post(
                    "https://pump.fun/api/ipfs",
                    data=form_data,
                    files={"file": ("image.png", img_resp.content, "image/png")}
                )
                
                if meta_resp.status_code != 200:
                    return {"status": "error", "error": "IPFS upload failed"}
                
                metadata = meta_resp.json()
                meta_uri = metadata["metadataUri"]
                
                # Step 2: Build create transaction
                import solders.keypair as kp
                # New mint keypair (local, only used once for tx building)
                mint_keypair = kp.Keypair()
                
                tx_resp = await client.post(
                    f"{self.api_url}/trade-local",
                    json={
                        "publicKey": turnkey_client.wallet_address,
                        "action": "create",
                        "tokenMetadata": {
                            "name": name,
                            "symbol": symbol,
                            "uri": meta_uri
                        },
                        "mint": str(mint_keypair.pubkey()),
                        "denominatedInSol": "true",
                        "amount": initial_buy_sol,
                        "slippage": 10,
                        "priorityFee": 0.005,
                        "pool": "pump"
                    }
                )
                
                if tx_resp.status_code != 200:
                    return {"status": "error", "error": tx_resp.text[:200]}
                
                tx_bytes = tx_resp.content
                
                # Sign the transaction (Turnkey signs wallet portion,
                # mint keypair signs locally — this is safe as it's a new ephemeral key)
                signed_tx = await turnkey_client.sign_solana_transaction(
                    tx_bytes,
                    note=f"create token {symbol}"
                )
                
                if not signed_tx:
                    return {"status": "error", "error": "Rejected by Turnkey policy"}
                
                tx_sig = await self._broadcast(signed_tx)
                mint_address = str(mint_keypair.pubkey())
                
                return {
                    "status": "success",
                    "action": "create",
                    "name": name, "symbol": symbol,
                    "mint_address": mint_address,
                    "tx_signature": tx_sig,
                    "pump_url": f"https://pump.fun/{mint_address}",
                    "explorer": f"https://solscan.io/tx/{tx_sig}"
                }
                
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def _broadcast(self, signed_tx: str) -> str:
        """Broadcast signed transaction to Solana."""
        import httpx
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_tx,
                {"encoding": "base64", "skipPreflight": False,
                 "maxRetries": 3}
            ]
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(settings.solana_rpc_url, json=payload)
            result = resp.json()
            if "error" in result:
                raise Exception(f"RPC error: {result['error']}")
            return result["result"]
    
    def _paper_result(self, action: str, mint: str, amount: float) -> dict:
        import hashlib, time
        fake_sig = "PAPER_" + hashlib.sha256(
            f"{action}{mint}{amount}{time.time()}".encode()
        ).hexdigest()[:40]
        return {
            "status": "paper_mode",
            "action": action,
            "mint": mint,
            "amount": amount,
            "tx_signature": fake_sig,
            "message": "Paper mode: not broadcast to chain"
        }

pumpfun_client = PumpFunClient()
