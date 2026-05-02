# src/guardrails.py
"""
Every tool call passes through this before touching the blockchain.
"""
import functools
import structlog
from typing import Callable, Any
from datetime import datetime

from .config import risk_limits
from .proposal_db import proposal_db, ProposalStatus

log = structlog.get_logger()

class GuardrailError(Exception):
    """Raised when a trade violates risk limits."""
    pass

def check_guardrails(tool_name: str, params: dict) -> list[str]:
    """
    Returns list of risk flags. Empty = clean.
    Raises GuardrailError for hard blocks.
    """
    flags = []
    
    # Hard block: paper mode
    if risk_limits.paper_mode:
        flags.append("PAPER_MODE: transaction will be simulated only")
    
    # Check blocked tokens
    token = params.get("mint_address") or params.get("output_mint") or params.get("token_address", "")
    if token and token in risk_limits.blocked_tokens:
        raise GuardrailError(f"Token {token} is on the blocked list")
    
    # Check SOL amount limits
    sol_amount = float(params.get("sol_amount", 0) or params.get("amount_sol", 0) or 0)
    
    if sol_amount > risk_limits.max_trade_sol:
        raise GuardrailError(
            f"Trade size {sol_amount} SOL exceeds max {risk_limits.max_trade_sol} SOL per trade"
        )
    
    if sol_amount > risk_limits.max_trade_sol * 0.5:
        flags.append(f"LARGE_TRADE: {sol_amount} SOL is >50% of per-trade limit")
    
    # Daily spend check
    daily_spent = proposal_db.get_daily_spend()
    if daily_spent + sol_amount > risk_limits.max_daily_sol:
        raise GuardrailError(
            f"Daily spend limit would be exceeded: "
            f"{daily_spent:.2f} spent + {sol_amount:.2f} = "
            f"{daily_spent+sol_amount:.2f} > {risk_limits.max_daily_sol} SOL"
        )
    
    if daily_spent > risk_limits.max_daily_sol * 0.7:
        flags.append(f"NEAR_DAILY_LIMIT: {daily_spent:.2f}/{risk_limits.max_daily_sol} SOL spent today")
    
    # Slippage check
    slippage = int(params.get("slippage_bps", 0))
    if slippage > risk_limits.max_slippage_bps:
        raise GuardrailError(
            f"Slippage {slippage}bps exceeds max {risk_limits.max_slippage_bps}bps"
        )
    
    return flags


def propose_or_execute(tool_name: str):
    """
    Decorator that wraps a tool with the propose/approve flow.
    
    If require_approval=True (default): creates a proposal and waits for human approval.
    If require_approval=False: executes immediately (still runs guardrails).
    
    Usage:
        @propose_or_execute("buy_pumpfun_token")
        async def buy_pumpfun_token(ctx, ...):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            # Extract context (first arg in MCP tools)
            ctx = args[0] if args else None
            
            # Get agent info from context
            agent_id = "unknown"
            reasoning = ""
            if ctx and hasattr(ctx, 'meta'):
                agent_id = getattr(ctx.meta, 'agent_id', 'unknown') or 'unknown'
                reasoning = kwargs.pop('reasoning', '') or ''
            
            # Run guardrails
            try:
                risk_flags = check_guardrails(tool_name, kwargs)
            except GuardrailError as e:
                return {
                    "status": "blocked",
                    "reason": str(e),
                    "tool": tool_name
                }
            
            # Create proposal
            proposal_id = proposal_db.create_proposal(
                tool_name=tool_name,
                params=kwargs,
                agent_id=agent_id,
                reasoning=reasoning,
                risk_flags=risk_flags,
                paper_mode=risk_limits.paper_mode
            )
            
            log.info("proposal_created", 
                     id=proposal_id, tool=tool_name, 
                     agent=agent_id, flags=risk_flags)
            
            if risk_limits.require_approval:
                return {
                    "status": "pending_approval",
                    "proposal_id": proposal_id,
                    "message": f"Trade proposal #{proposal_id} created. "
                               f"Review and approve at http://localhost:8501",
                    "risk_flags": risk_flags,
                    "params": kwargs
                }
            else:
                # Auto-execute
                return await _execute_proposal(proposal_id, fn, args, kwargs)
        
        return wrapper
    return decorator


async def _execute_proposal(proposal_id: str, fn: Callable, args, kwargs) -> dict:
    """Execute an approved proposal."""
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED)
    try:
        result = await fn(*args, **kwargs)
        proposal_db.update_status(
            proposal_id, ProposalStatus.EXECUTED,
            result=str(result),
            tx_sig=result.get("tx_signature") if isinstance(result, dict) else None
        )
        # Track spend
        sol_amount = float(kwargs.get("sol_amount", 0))
        if sol_amount > 0 and not risk_limits.paper_mode:
            proposal_db.add_daily_spend(sol_amount)
        return result
    except Exception as e:
        proposal_db.update_status(proposal_id, ProposalStatus.FAILED, result=str(e))
        return {"status": "error", "proposal_id": proposal_id, "error": str(e)}
