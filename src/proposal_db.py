# src/proposal_db.py
import sqlite3
import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
import threading

class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    EXPIRED = "expired"

class ProposalDB:
    def __init__(self, db_path: str = "data/proposals.db"):
        Path(db_path).parent.mkdir(exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    agent_id TEXT,
                    agent_reasoning TEXT,
                    params TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result TEXT,
                    tx_signature TEXT,
                    paper_mode INTEGER DEFAULT 1,
                    risk_flags TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT,
                    connected_at TEXT,
                    last_seen TEXT,
                    total_proposals INTEGER DEFAULT 0,
                    approved INTEGER DEFAULT 0,
                    rejected INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS daily_spend (
                    date TEXT PRIMARY KEY,
                    total_sol REAL DEFAULT 0.0
                );
            """)
    
    def create_proposal(self, tool_name: str, params: dict,
                        agent_id: str = "unknown", reasoning: str = "",
                        risk_flags: list = None, paper_mode: bool = True) -> str:
        proposal_id = str(uuid.uuid4())[:8].upper()
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO proposals 
                (id, tool_name, agent_id, agent_reasoning, params, status,
                 created_at, updated_at, paper_mode, risk_flags)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (proposal_id, tool_name, agent_id, reasoning,
                  json.dumps(params), ProposalStatus.PENDING,
                  now, now, int(paper_mode),
                  json.dumps(risk_flags or [])))
            # Update agent session
            conn.execute("""
                INSERT INTO agent_sessions (agent_id, name, connected_at, last_seen, total_proposals)
                VALUES (?,?,?,?,1)
                ON CONFLICT(agent_id) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    total_proposals=total_proposals+1
            """, (agent_id, agent_id, now, now))
        return proposal_id
    
    def get_proposal(self, proposal_id: str) -> Optional[dict]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE id=?", (proposal_id,)
            ).fetchone()
            return dict(row) if row else None
    
    def list_proposals(self, status: str = None, limit: int = 100) -> list[dict]:
        with self._lock, self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM proposals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
    
    def update_status(self, proposal_id: str, status: str,
                      result: str = None, tx_sig: str = None):
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("""
                UPDATE proposals SET status=?, updated_at=?, result=?, tx_signature=?
                WHERE id=?
            """, (status, now, result, tx_sig, proposal_id))
    
    def get_daily_spend(self) -> float:
        today = datetime.utcnow().date().isoformat()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT total_sol FROM daily_spend WHERE date=?", (today,)
            ).fetchone()
            return row["total_sol"] if row else 0.0
    
    def add_daily_spend(self, sol_amount: float):
        today = datetime.utcnow().date().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT INTO daily_spend (date, total_sol) VALUES (?,?)
                ON CONFLICT(date) DO UPDATE SET total_sol=total_sol+?
            """, (today, sol_amount, sol_amount))
    
    def get_agents(self) -> list[dict]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT * FROM agent_sessions ORDER BY last_seen DESC").fetchall()
            return [dict(r) for r in rows]

proposal_db = ProposalDB()
