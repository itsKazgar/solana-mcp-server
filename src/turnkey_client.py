# src/turnkey_client.py
"""
Turnkey SDK integration for policy-controlled Solana signing.
Turnkey never exposes your private key — all signing happens in their secure enclave.
"""
import httpx
import json
import base64
import hashlib
import time
from typing import Optional
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
import structlog

from .config import settings

log = structlog.get_logger()

class TurnkeyClient:
    """
    Wraps Turnkey's API for Solana transaction signing.
    
    Turnkey Policy Examples you should configure in their dashboard:
    
    POLICY 1 - Max per-trade:
    {
      "policyName": "Max SOL per trade",
      "effect": "EFFECT_DENY",
      "consensus": "CONSENSUS_FULL",
      "condition": "solana.transferValue > 1000000000"  // 1 SOL in lamports
    }
    
    POLICY 2 - Allowed programs only:
    {
      "policyName": "Allowed programs",
      "effect": "EFFECT_DENY", 
      "condition": "!solana.instructions.all(i, i.programId in 
        ['6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',
         'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4',
         '11111111111111111111111111111111'])"
    }
    
    POLICY 3 - Require human approval above threshold:
    Configure webhook approval in Turnkey dashboard for txns > 0.5 SOL
    """
    
    BASE_URL = "https://api.turnkey.com"
    
    def __init__(self):
        self.org_id = settings.turnkey_organization_id
        self.wallet_address = settings.turnkey_wallet_address
        
        # Load API keypair for request signing
        # In production: store these in a secrets manager
        self._api_public_key = settings.turnkey_api_public_key
        self._api_private_key_bytes = self._load_private_key()
    
    def _load_private_key(self) -> Optional[bytes]:
        """Load Turnkey API signing key (NOT your wallet key)."""
        if not settings.turnkey_api_private_key:
            log.warning("turnkey_no_key", msg="No Turnkey API private key configured")
            return None
        try:
            return base64.b64decode(settings.turnkey_api_private_key)
        except Exception as e:
            log.error("turnkey_key_load_error", error=str(e))
            return None
    
    def _sign_request(self, payload: dict) -> dict:
        """Sign Turnkey API requests with your API keypair."""
        if not self._api_private_key_bytes:
            raise ValueError("Turnkey API private key not configured")
        
        body = json.dumps(payload, separators=(',', ':'))
        
        # Turnkey uses their stamp format
        stamp = {
            "publicKey": self._api_public_key,
            "scheme": "SIGNATURE_SCHEME_TK_API_P256",
            "signature": self._compute_signature(body)
        }
        return stamp
    
    def _compute_signature(self, body: str) -> str:
        """Compute P-256 signature for Turnkey API auth."""
        # In production use the official turnkey-sdk-python package
        # This is a simplified placeholder
        private_key = Ed25519PrivateKey.from_private_bytes(self._api_private_key_bytes[:32])
        sig = private_key.sign(body.encode())
        return base64.urlsafe_b64encode(sig).decode()
    
    async def sign_solana_transaction(
        self,
        transaction_bytes: bytes,
        note: str = ""
    ) -> Optional[str]:
        """
        Submit a Solana transaction to Turnkey for policy-controlled signing.
        Returns base64-encoded signed transaction, or None if policy denied.
        """
        if not self.org_id or not self.wallet_address:
            log.warning("turnkey_not_configured", msg="Using simulation mode")
            return self._simulate_sign(transaction_bytes)
        
        payload = {
            "type": "ACTIVITY_TYPE_SIGN_TRANSACTION_V2",
            "timestampMs": str(int(time.time() * 1000)),
            "organizationId": self.org_id,
            "parameters": {
                "signWith": self.wallet_address,
                "unsignedTransaction": base64.b64encode(transaction_bytes).decode(),
                "type": "TRANSACTION_TYPE_SOLANA",
            }
        }
        
        try:
            stamp = self._sign_request(payload)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/public/v1/submit/sign_transaction",
                    json=payload,
                    headers={
                        "X-Stamp": json.dumps(stamp),
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    activity = result.get("activity", {})
                    status = activity.get("status", "")
                    
                    if status == "ACTIVITY_STATUS_COMPLETED":
                        signed_tx = activity["result"]["signTransactionResult"]["signedTransaction"]
                        log.info("turnkey_signed", note=note, status="completed")
                        return signed_tx
                    elif status == "ACTIVITY_STATUS_REJECTED":
                        log.warning("turnkey_policy_denied", note=note, 
                                   reason=activity.get("failure", {}).get("message"))
                        return None
                    else:
                        log.warning("turnkey_unexpected_status", status=status)
                        return None
                else:
                    log.error("turnkey_api_error", 
                             status=response.status_code, 
                             body=response.text[:500])
                    return None
                    
        except Exception as e:
            log.error("turnkey_sign_error", error=str(e))
            return None
    
    def _simulate_sign(self, transaction_bytes: bytes) -> str:
        """Paper mode: return fake signature for testing."""
        fake_sig = "PAPER_" + base64.b64encode(
            hashlib.sha256(transaction_bytes).digest()
        ).decode()[:40]
        log.info("turnkey_paper_sign", sig=fake_sig)
        return fake_sig
    
    async def get_wallet_balance(self) -> float:
        """Get SOL balance of the Turnkey wallet."""
        from solana.rpc.async_api import AsyncClient
        async with AsyncClient(settings.solana_rpc_url) as client:
            from solders.pubkey import Pubkey
            pubkey = Pubkey.from_string(self.wallet_address)
            resp = await client.get_balance(pubkey)
            return resp.value / 1e9  # lamports to SOL

turnkey_client = TurnkeyClient()
