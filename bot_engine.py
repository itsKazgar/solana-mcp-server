# src/bot_engine.py
"""
Bot Engine — create wallets, define strategies, run autonomous trading bots.
Each bot has its own Solana wallet, its own prompt/strategy, and its own runtime.
"""
import asyncio
import json
import uuid
import sqlite3
import threading
import time
import httpx
import structlog
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum
from cryptography.fernet import Fernet
import base64
import os

log = structlog.get_logger()

# ── Encryption for stored private keys ───────────────────────────
def _get_or_create_encryption_key() -> bytes:
    key_path = Path("data/bot_key.key")
    key_path.parent.mkdir(exist_ok=True)
    if key_path.exists():
        return key_path.read_bytes()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key

_fernet = Fernet(_get_or_create_encryption_key())

def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode()

def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


class BotStatus(str, Enum):
    STOPPED  = "stopped"
    RUNNING  = "running"
    PAUSED   = "paused"
    ERROR    = "error"


# ── Database ──────────────────────────────────────────────────────
class BotDB:
    def __init__(self, db_path: str = "data/bots.db"):
        Path(db_path).parent.mkdir(exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS bots (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    status      TEXT DEFAULT 'stopped',
                    strategy    TEXT,
                    prompt      TEXT,
                    wallet_pub  TEXT,
                    wallet_priv TEXT,
                    config      TEXT,
                    created_at  TEXT,
                    updated_at  TEXT,
                    last_run    TEXT,
                    total_trades INTEGER DEFAULT 0,
                    total_pnl   REAL DEFAULT 0.0,
                    error_msg   TEXT
                );
                CREATE TABLE IF NOT EXISTS bot_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id     TEXT,
                    timestamp  TEXT,
                    level      TEXT,
                    message    TEXT,
                    data       TEXT
                );
                CREATE TABLE IF NOT EXISTS bot_trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id      TEXT,
                    timestamp   TEXT,
                    action      TEXT,
                    mint        TEXT,
                    amount_sol  REAL,
                    result      TEXT,
                    tx_sig      TEXT,
                    pnl         REAL DEFAULT 0.0
                );
            """)

    def create_bot(self, name: str, strategy: str, prompt: str,
                   wallet_pub: str, wallet_priv_enc: str, config: dict) -> str:
        bot_id = str(uuid.uuid4())[:8].upper()
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO bots
                (id,name,status,strategy,prompt,wallet_pub,wallet_priv,config,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (bot_id, name, BotStatus.STOPPED, strategy, prompt,
                  wallet_pub, wallet_priv_enc, json.dumps(config), now, now))
        return bot_id

    def get_bot(self, bot_id: str) -> Optional[dict]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
            return dict(row) if row else None

    def list_bots(self) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT * FROM bots ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def update_bot(self, bot_id: str, **kwargs):
        kwargs["updated_at"] = datetime.utcnow().isoformat()
        fields = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [bot_id]
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE bots SET {fields} WHERE id=?", values)

    def delete_bot(self, bot_id: str):
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM bots WHERE id=?", (bot_id,))
            conn.execute("DELETE FROM bot_logs WHERE bot_id=?", (bot_id,))
            conn.execute("DELETE FROM bot_trades WHERE bot_id=?", (bot_id,))

    def add_log(self, bot_id: str, level: str, message: str, data: dict = None):
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO bot_logs (bot_id,timestamp,level,message,data) VALUES (?,?,?,?,?)",
                (bot_id, now, level, message, json.dumps(data or {}))
            )

    def get_logs(self, bot_id: str, limit: int = 50) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bot_logs WHERE bot_id=? ORDER BY id DESC LIMIT ?",
                (bot_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def add_trade(self, bot_id: str, action: str, mint: str,
                  amount_sol: float, result: str, tx_sig: str = None, pnl: float = 0.0):
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO bot_trades (bot_id,timestamp,action,mint,amount_sol,result,tx_sig,pnl)
                VALUES (?,?,?,?,?,?,?,?)
            """, (bot_id, now, action, mint, amount_sol, result, tx_sig, pnl))
            conn.execute(
                "UPDATE bots SET total_trades=total_trades+1, last_run=? WHERE id=?",
                (now, bot_id)
            )

    def get_trades(self, bot_id: str, limit: int = 50) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM bot_trades WHERE bot_id=? ORDER BY id DESC LIMIT ?",
                (bot_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

bot_db = BotDB()


# ── Wallet Generation ─────────────────────────────────────────────
def generate_solana_wallet() -> tuple[str, str]:
    """
    Generate a new Solana keypair.
    Returns (public_key_base58, private_key_base58)
    Private key is stored encrypted — never exposed in UI.
    """
    try:
        from solders.keypair import Keypair
        kp = Keypair()
        pub  = str(kp.pubkey())
        priv = base64.b64encode(bytes(kp)).decode()
        return pub, priv
    except ImportError:
        # Fallback using os.urandom if solders not available
        import hashlib
        seed = os.urandom(32)
        # Simple deterministic pubkey from seed (not real Ed25519, just for UI demo)
        pub  = base64.b58encode(hashlib.sha256(seed).digest()).decode()[:44]
        priv = base64.b64encode(seed).decode()
        return pub, priv


# ── Bot Runner ────────────────────────────────────────────────────
class BotRunner:
    """
    Runs a bot's strategy in a background thread.
    Uses Claude API to reason about trades based on the bot's prompt + market data.
    """

    def __init__(self):
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}

    def start(self, bot_id: str):
        if bot_id in self._threads and self._threads[bot_id].is_alive():
            return
        stop_event = threading.Event()
        self._stop_events[bot_id] = stop_event
        t = threading.Thread(
            target=self._run_loop,
            args=(bot_id, stop_event),
            daemon=True
        )
        self._threads[bot_id] = t
        bot_db.update_bot(bot_id, status=BotStatus.RUNNING, error_msg=None)
        t.start()
        log.info("bot_started", bot_id=bot_id)

    def stop(self, bot_id: str):
        if bot_id in self._stop_events:
            self._stop_events[bot_id].set()
        bot_db.update_bot(bot_id, status=BotStatus.STOPPED)
        log.info("bot_stopped", bot_id=bot_id)

    def pause(self, bot_id: str):
        bot_db.update_bot(bot_id, status=BotStatus.PAUSED)

    def resume(self, bot_id: str):
        bot_db.update_bot(bot_id, status=BotStatus.RUNNING)

    def is_running(self, bot_id: str) -> bool:
        return (bot_id in self._threads and
                self._threads[bot_id].is_alive() and
                not self._stop_events.get(bot_id, threading.Event()).is_set())

    def _run_loop(self, bot_id: str, stop_event: threading.Event):
        """Main bot loop — runs every interval, calls AI to decide what to do."""
        bot = bot_db.get_bot(bot_id)
        if not bot:
            return

        config = json.loads(bot["config"]) if isinstance(bot["config"], str) else bot["config"]
        interval_seconds = config.get("interval_seconds", 60)

        bot_db.add_log(bot_id, "INFO", f"Bot started. Strategy: {bot['strategy']}. Interval: {interval_seconds}s")

        while not stop_event.is_set():
            try:
                # Check if paused
                current = bot_db.get_bot(bot_id)
                if current and current["status"] == BotStatus.PAUSED:
                    time.sleep(5)
                    continue

                # Run one cycle
                asyncio.run(self._run_cycle(bot_id, stop_event))

            except Exception as e:
                bot_db.add_log(bot_id, "ERROR", f"Cycle error: {str(e)}")
                bot_db.update_bot(bot_id, error_msg=str(e)[:200])
                time.sleep(30)

            # Wait for next interval
            stop_event.wait(interval_seconds)

        bot_db.update_bot(bot_id, status=BotStatus.STOPPED)

    async def _run_cycle(self, bot_id: str, stop_event: threading.Event):
        """One trading cycle — gather market data, ask AI, execute decision."""
        from .tools_extra import fetch_trending_pumpfun, fetch_sol_balance

        bot = bot_db.get_bot(bot_id)
        if not bot:
            return

        config = json.loads(bot["config"]) if isinstance(bot["config"], str) else bot["config"]
        paper_mode = config.get("paper_mode", True)
        max_sol_per_trade = float(config.get("max_sol_per_trade", 0.1))
        wallet_pub = bot["wallet_pub"]

        bot_db.add_log(bot_id, "INFO", "Starting cycle — gathering market data...")

        # Gather context
        trending = await fetch_trending_pumpfun(limit=10)
        sol_balance = await fetch_sol_balance(wallet_pub)
        recent_trades = bot_db.get_trades(bot_id, limit=5)

        # Build AI prompt
        market_summary = json.dumps([{
            "name": t["name"], "symbol": t["symbol"],
            "mint": t["mint"], "mcap": t["market_cap_usd"],
            "bonding_pct": t["bonding_curve_pct"],
            "graduated": t["graduated"]
        } for t in trending[:5]], indent=2)

        recent_summary = json.dumps([{
            "action": t["action"], "mint": t["mint"][:8],
            "amount": t["amount_sol"], "result": t["result"][:50]
        } for t in recent_trades], indent=2) if recent_trades else "No trades yet"

        system_prompt = f"""You are an autonomous Solana trading bot.
Your wallet: {wallet_pub}
Your SOL balance: {sol_balance:.4f} SOL
Paper mode: {paper_mode}
Max SOL per trade: {max_sol_per_trade}

YOUR STRATEGY:
{bot['prompt']}

RULES:
- Never spend more than {max_sol_per_trade} SOL in one trade
- Always respond with valid JSON only
- If you want to trade, specify the exact action
- If conditions aren't right, say WAIT
- Be concise and decisive

Respond ONLY with this JSON format:
{{
  "decision": "BUY" | "SELL" | "WAIT",
  "mint_address": "...",
  "amount_sol": 0.0,
  "reasoning": "brief reason",
  "confidence": 0-100
}}"""

        user_prompt = f"""Current market data (top trending pump.fun tokens):
{market_summary}

Your recent trades:
{recent_summary}

Current time: {datetime.utcnow().isoformat()}

What do you do?"""

        bot_db.add_log(bot_id, "INFO", "Asking AI for trading decision...")

        # Call Claude API
        decision = await self._ask_ai(bot_id, system_prompt, user_prompt)

        if not decision:
            bot_db.add_log(bot_id, "WARN", "No decision from AI, skipping cycle")
            return

        action = decision.get("decision", "WAIT")
        reasoning = decision.get("reasoning", "")
        confidence = decision.get("confidence", 0)

        bot_db.add_log(bot_id, "INFO",
            f"Decision: {action} | Confidence: {confidence}% | {reasoning}")

        if action == "WAIT":
            return

        mint = decision.get("mint_address", "")
        amount = min(float(decision.get("amount_sol", 0)), max_sol_per_trade)

        if not mint or amount <= 0:
            bot_db.add_log(bot_id, "WARN", "Invalid trade params from AI")
            return

        if sol_balance < amount and not paper_mode:
            bot_db.add_log(bot_id, "WARN", f"Insufficient balance: {sol_balance:.4f} SOL < {amount} SOL")
            return

        # Execute trade
        await self._execute_trade(bot_id, action, mint, amount, paper_mode, reasoning)

    async def _ask_ai(self, bot_id: str, system: str, user: str) -> Optional[dict]:
        """Call Claude API for trading decision."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 500,
                        "system": system,
                        "messages": [{"role": "user", "content": user}]
                    }
                )
                if resp.status_code == 200:
                    text = resp.json()["content"][0]["text"].strip()
                    # Strip markdown if present
                    text = text.replace("```json", "").replace("```", "").strip()
                    return json.loads(text)
                else:
                    bot_db.add_log(bot_id, "ERROR", f"AI API error: {resp.status_code}")
                    return None
        except json.JSONDecodeError as e:
            bot_db.add_log(bot_id, "ERROR", f"AI returned invalid JSON: {str(e)}")
            return None
        except Exception as e:
            bot_db.add_log(bot_id, "ERROR", f"AI call failed: {str(e)}")
            return None

    async def _execute_trade(self, bot_id: str, action: str, mint: str,
                              amount_sol: float, paper_mode: bool, reasoning: str):
        """Execute the trade decision."""
        from .pumpfun import pumpfun_client
        from .proposal_db import proposal_db

        bot_db.add_log(bot_id, "INFO",
            f"Executing {action} — {amount_sol} SOL on {mint[:8]}... | Paper: {paper_mode}")

        try:
            if paper_mode:
                import hashlib, time as t
                fake_sig = "BOT_PAPER_" + hashlib.sha256(
                    f"{bot_id}{action}{mint}{t.time()}".encode()
                ).hexdigest()[:20]
                result = {
                    "status": "paper_mode",
                    "action": action,
                    "mint": mint,
                    "amount_sol": amount_sol,
                    "tx_signature": fake_sig
                }
                bot_db.add_log(bot_id, "INFO", f"Paper trade executed: {fake_sig}")
            else:
                if action == "BUY":
                    result = await pumpfun_client.buy(mint, amount_sol, paper_mode=False)
                else:
                    result = await pumpfun_client.sell(mint, amount_sol, paper_mode=False)

            tx_sig = result.get("tx_signature", "")
            bot_db.add_trade(bot_id, action.lower(), mint, amount_sol,
                            result.get("status", "unknown"), tx_sig)

            # Also create a proposal record for dashboard visibility
            proposal_db.create_proposal(
                tool_name=f"bot_{action.lower()}_pumpfun_token",
                params={"mint_address": mint, "sol_amount": amount_sol},
                agent_id=f"bot_{bot_id}",
                reasoning=f"[BOT {bot_id}] {reasoning}",
                paper_mode=paper_mode
            )

        except Exception as e:
            bot_db.add_log(bot_id, "ERROR", f"Trade execution failed: {str(e)}")
            bot_db.add_trade(bot_id, action.lower(), mint, amount_sol, f"error: {str(e)}")


bot_runner = BotRunner()
