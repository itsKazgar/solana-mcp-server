# src/x402_client.py
"""
x402 micropayment standard implementation.
x402 is an HTTP 402 Payment Required protocol for autonomous AI agent payments.
Spec: https://x402.org
"""
import httpx
import json
import base64
import structlog
from typing import Optional

from .config import settings
from .turnkey_client import turnkey_client

log = structlog.get_logger()

class X402Client:
    """
    Handles x402 payment flow:
    1. Agent hits a paywall → gets 402 with payment requirements
    2. We build a payment payload on Solana
    3. Sign with Turnkey
    4. Retry the request with payment header
    5. Facilitator verifies and grants access
    """
    
    def __init__(self):
        self.facilitator_url = settings.x402_facilitator_url
    
    async def make_payment(
        self,
        url: str,
        max_amount_usdc: float = 1.0,
        purpose: str = "",
        paper_mode: bool = True
    ) -> dict:
        """
        Make an x402 micropayment to access a paid resource.
        
        Args:
            url: The URL requiring payment (will be fetched)
            max_amount_usdc: Maximum acceptable payment in USDC
            purpose: Why the agent needs this resource
            paper_mode: Simulate payment
        """
        log.info("x402_payment_attempt", url=url, max_usdc=max_amount_usdc, paper=paper_mode)
        
        if paper_mode:
            return {
                "status": "paper_mode",
                "url": url,
                "message": "Paper mode: payment simulated",
                "simulated_cost": max_amount_usdc * 0.1
            }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: Hit the URL to get 402 payment details
                initial_resp = await client.get(url)
                
                if initial_resp.status_code != 402:
                    # No payment required, return content directly
                    return {
                        "status": "no_payment_required",
                        "url": url,
                        "content": initial_resp.text[:1000]
                    }
                
                # Parse x402 payment requirements
                payment_required = initial_resp.json()
                accepts = payment_required.get("accepts", [])
                
                if not accepts:
                    return {"status": "error", "error": "No payment options in 402 response"}
                
                # Find a Solana/USDC option
                solana_option = None
                for option in accepts:
                    if option.get("network") in ("solana-mainnet", "solana-devnet", "base-sepolia"):
                        amount = float(option.get("maxAmountRequired", 0)) / 1e6  # USDC decimals
                        if amount <= max_amount_usdc:
                            solana_option = option
                            break
                
                if not solana_option:
                    return {
                        "status": "error",
                        "error": f"No acceptable payment option found (max {max_amount_usdc} USDC)",
                        "available": accepts
                    }
                
                # Step 2: Build payment payload
                payment_payload = await self._build_payment(solana_option)
                if not payment_payload:
                    return {"status": "error", "error": "Failed to build payment payload"}
                
                # Step 3: Retry with payment header
                paid_resp = await client.get(
                    url,
                    headers={"X-PAYMENT": json.dumps(payment_payload)}
                )
                
                if paid_resp.status_code == 200:
                    log.info("x402_payment_success", url=url, 
                             amount=solana_option.get("maxAmountRequired"))
                    return {
                        "status": "success",
                        "url": url,
                        "amount_paid_usdc": float(solana_option.get("maxAmountRequired", 0)) / 1e6,
                        "content": paid_resp.text[:5000],
                        "content_type": paid_resp.headers.get("content-type")
                    }
                else:
                    return {
                        "status": "error",
                        "error": f"Payment rejected: {paid_resp.status_code}",
                        "body": paid_resp.text[:500]
                    }
                    
        except Exception as e:
            log.error("x402_error", error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def _build_payment(self, payment_option: dict) -> Optional[dict]:
        """Build and sign an x402 payment payload."""
        try:
            network = payment_option.get("network", "solana-mainnet")
            amount = payment_option.get("maxAmountRequired", "0")
            pay_to = payment_option.get("payTo", "")
            
            if "solana" in network:
                return await self._build_solana_payment(payment_option)
            else:
                log.warning("x402_unsupported_network", network=network)
                return None
                
        except Exception as e:
            log.error("x402_build_error", error=str(e))
            return None
    
    async def _build_solana_payment(self, option: dict) -> Optional[dict]:
        """Build Solana USDC transfer for x402."""
        from solders.pubkey import Pubkey
        from solana.rpc.async_api import AsyncClient
        
        amount_usdc = int(option.get("maxAmountRequired", 0))
        pay_to = option.get("payTo", "")
        extra = option.get("extra", {})
        
        # Build minimal USDC transfer transaction
        # In production, use proper SPL token transfer instruction
        # This is simplified for illustration
        payment_payload = {
            "x402Version": 1,
            "scheme": "exact",
            "network": option.get("network"),
            "payload": {
                "signature": "TURNKEY_SIGNED",  # Would be actual signed tx
                "authorization": {
                    "from": turnkey_client.wallet_address,
                    "to": pay_to,
                    "value": str(amount_usdc),
                    "validAfter": "0",
                    "validBefore": str(int(__import__('time').time()) + 300),
                    "nonce": __import__('secrets').token_hex(16)
                }
            }
        }
        
        # Sign authorization via Turnkey
        auth_bytes = json.dumps(payment_payload["payload"]["authorization"]).encode()
        signed = await turnkey_client.sign_solana_transaction(
            auth_bytes,
            note=f"x402 payment {amount_usdc} USDC to {pay_to[:8]}"
        )
        
        if signed:
            payment_payload["payload"]["signature"] = signed
            return payment_payload
        return None

x402_client = X402Client()
