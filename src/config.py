# src/config.py
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import json
from pathlib import Path

class Settings(BaseSettings):
    # Solana
    solana_rpc_url: str = "https://api.devnet.solana.com"
    solana_network: str = "devnet"
    
    # Turnkey
    turnkey_api_public_key: str = ""
    turnkey_api_private_key: str = ""
    turnkey_organization_id: str = ""
    turnkey_wallet_address: str = ""
    
    # Server
    mcp_server_host: str = "0.0.0.0"
    mcp_server_port: int = 8000
    mcp_secret_token: str = "dev_token_change_in_production"
    
    # Risk defaults
    max_trade_sol: float = 1.0
    max_daily_sol: float = 10.0
    max_slippage_bps: int = 300
    require_approval: bool = True
    paper_mode: bool = True
    
    # External APIs
    jupiter_api_url: str = "https://quote-api.jup.ag/v6"
    pumpfun_api_url: str = "https://pumpportal.fun/api"
    x402_facilitator_url: str = "https://x402.org/facilitator"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Runtime risk limits (mutable from dashboard)
class RiskLimits:
    def __init__(self):
        self._path = Path("data/risk_limits.json")
        self._path.parent.mkdir(exist_ok=True)
        self._load()
    
    def _load(self):
        if self._path.exists():
            data = json.loads(self._path.read_text())
        else:
            data = {}
        self.max_trade_sol = data.get("max_trade_sol", settings.max_trade_sol)
        self.max_daily_sol = data.get("max_daily_sol", settings.max_daily_sol)
        self.max_slippage_bps = data.get("max_slippage_bps", settings.max_slippage_bps)
        self.require_approval = data.get("require_approval", settings.require_approval)
        self.paper_mode = data.get("paper_mode", settings.paper_mode)
        self.blocked_tokens: list[str] = data.get("blocked_tokens", [])
        self.allowed_programs: list[str] = data.get("allowed_programs", [
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # pump.fun
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter v6
        ])
    
    def save(self):
        self._path.write_text(json.dumps(self.__dict__, default=str))
    
    def reload(self):
        self._load()

risk_limits = RiskLimits()
