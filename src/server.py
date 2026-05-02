# src/server.py
"""
Universal Solana AI Trading MCP Server
Connect any agent: claude, langchain, crewai, custom scripts
URL: http://your-server:8000/mcp/
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Any
import structlog
from fastmcp import FastMCP, Context
from fastmcp.server.auth import BearerAuthProvider

from .config import settings, risk_limits
from .proposal_db import proposal_db, ProposalStatus
from .guardrails import propose_or_execute, check_guardrails, GuardrailError, _execute_proposal
from .pumpfun import pumpfun_client
from .jupiter import jupiter_client, SOL_MINT, USDC_MINT
from .x402_client import x402_client
from .turnkey_client import turnkey_client

log = structlog.get_logger()

# ── Auth ─────────────────────────────────────────────────────────
auth = BearerAuthProvider(
    public_key=settings.mcp_secret_token
) if settings.mcp_secret_token else None

# ── Server Init ──────────────────────────────────────────────────
mcp = FastMCP(
    name="Solana Trading MCP Server",
    instructions="""
    Universal Solana AI trading server. You can:
    - Buy/sell Pump.fun meme coins on the bonding curve
    - Create new Pump.fun tokens
    - Swap any Solana tokens via Jupiter aggregator
    - Make x402 micropayments for API/data access
    - Propose trades for human review (default mode)
    
    IMPORTANT: All trades default to 'propose mode' — they are queued for 
    human approval at the dashboard (http://localhost:8501). 
    The human operator will approve/reject/edit proposals.
    
    Always include 'reasoning' parameter explaining WHY you want to make the trade.
    This reasoning is shown to the human reviewer.
    
    Current mode: """ + ("PAPER (simulated)" if settings.paper_mode else "LIVE"),
    auth=auth
)

# ═══════════════════════════════════════════════════════════════════
# PUMP.FUN TOOLS
# ═══════════════════════════════════════════════════════════════════

@mcp.tool(
    description="""Buy a Pump.fun meme coin on the bonding curve.
    
    Use this when you want to purchase tokens that are still on Pump.fun's 
    bonding curve (market cap < ~$69k). After graduation, use jupiter_swap instead.
    
    Returns: proposal_id for human approval, or execution result if auto-approve is on.
    """
)
async def buy_pumpfun_token(
    ctx: Context,
    mint_address: str,
    sol_amount: float,
    reasoning: str,
    slippage_bps: int = 100,
) -> dict:
    """
    Buy a Pump.fun token.
    
    Args:
        mint_address: The token's mint address (from pump.fun URL)
        sol_amount: How much SOL to spend (e.g., 0.1 for 0.1 SOL)
        reasoning: Why you want to buy this token (shown to human reviewer)
        slippage_bps: Max slippage in basis points (100 = 1%)
    """
    agent_id = _get_agent_id(ctx)
    
    # Guardrails check
    try:
        risk_flags = check_guardrails("buy_pumpfun_token", {
            "mint_address": mint_address,
            "sol_amount": sol_amount,
            "slippage_bps": slippage_bps
        })
    except GuardrailError as e:
        return {"status": "blocked", "reason": str(e)}
    
    # Create proposal
    proposal_id = proposal_db.create_proposal(
        tool_name="buy_pumpfun_token",
        params={"mint_address": mint_address, "sol_amount": sol_amount, 
                "slippage_bps": slippage_bps},
        agent_id=agent_id,
        reasoning=reasoning,
        risk_flags=risk_flags,
        paper_mode=risk_limits.paper_mode
    )
    
    if risk_limits.require_approval:
        return {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "message": f"Buy proposal #{proposal_id} queued for review at http://localhost:8501",
            "details": {
                "action": "buy", "mint": mint_address,
                "sol_amount": sol_amount, "slippage_bps": slippage_bps
            },
            "risk_flags": risk_flags
        }
    
    # Auto-execute
    result = await pumpfun_client.buy(
        mint_address, sol_amount, slippage_bps,
        paper_mode=risk_limits.paper_mode
    )
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED,
                              result=str(result),
                              tx_sig=result.get("tx_signature"))
    return result


@mcp.tool(
    description="""Sell a Pump.fun meme coin back to the bonding curve.
    
    Use this to exit a Pump.fun position. Specify the token amount to sell.
    To sell all tokens, first check your balance with get_portfolio.
    """
)
async def sell_pumpfun_token(
    ctx: Context,
    mint_address: str,
    token_amount: float,
    reasoning: str,
    slippage_bps: int = 100,
) -> dict:
    """
    Sell a Pump.fun token.
    
    Args:
        mint_address: Token mint address
        token_amount: Number of tokens to sell (check get_portfolio for balance)
        reasoning: Why you want to sell (shown to human reviewer)
        slippage_bps: Max slippage in basis points
    """
    agent_id = _get_agent_id(ctx)
    
    try:
        risk_flags = check_guardrails("sell_pumpfun_token", {
            "mint_address": mint_address, "slippage_bps": slippage_bps
        })
    except GuardrailError as e:
        return {"status": "blocked", "reason": str(e)}
    
    proposal_id = proposal_db.create_proposal(
        tool_name="sell_pumpfun_token",
        params={"mint_address": mint_address, "token_amount": token_amount,
                "slippage_bps": slippage_bps},
        agent_id=agent_id, reasoning=reasoning,
        risk_flags=risk_flags, paper_mode=risk_limits.paper_mode
    )
    
    if risk_limits.require_approval:
        return {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "message": f"Sell proposal #{proposal_id} queued for review",
            "risk_flags": risk_flags
        }
    
    result = await pumpfun_client.sell(
        mint_address, token_amount, slippage_bps,
        paper_mode=risk_limits.paper_mode
    )
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED,
                              result=str(result), tx_sig=result.get("tx_signature"))
    return result


@mcp.tool(
    description="""Create a new Pump.fun meme coin token.
    
    Launches a new token on Pump.fun with bonding curve mechanics.
    Optionally make an initial buy to seed the bonding curve.
    Requires IPFS-accessible image URL.
    """
)
async def create_pumpfun_token(
    ctx: Context,
    name: str,
    symbol: str,
    description: str,
    image_url: str,
    reasoning: str,
    initial_buy_sol: float = 0.0,
) -> dict:
    """
    Create a new Pump.fun token.
    
    Args:
        name: Token full name (e.g., "Degen Pepe")
        symbol: Ticker symbol (e.g., "DPEPE")
        description: Token description for metadata
        image_url: URL to token image (must be publicly accessible)
        reasoning: Why you're creating this token
        initial_buy_sol: Optional initial buy amount in SOL (seeds bonding curve)
    """
    agent_id = _get_agent_id(ctx)
    
    if initial_buy_sol > 0:
        try:
            check_guardrails("create_pumpfun_token", {"sol_amount": initial_buy_sol})
        except GuardrailError as e:
            return {"status": "blocked", "reason": str(e)}
    
    proposal_id = proposal_db.create_proposal(
        tool_name="create_pumpfun_token",
        params={"name": name, "symbol": symbol, "description": description,
                "image_url": image_url, "initial_buy_sol": initial_buy_sol},
        agent_id=agent_id, reasoning=reasoning,
        risk_flags=["TOKEN_CREATION"] if not risk_limits.paper_mode else ["PAPER_MODE"],
        paper_mode=risk_limits.paper_mode
    )
    
    if risk_limits.require_approval:
        return {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "message": f"Token creation proposal #{proposal_id} queued for review",
        }
    
    result = await pumpfun_client.create_token(
        name, symbol, description, image_url, initial_buy_sol,
        paper_mode=risk_limits.paper_mode
    )
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED,
                              result=str(result), tx_sig=result.get("tx_signature"))
    return result


# ═══════════════════════════════════════════════════════════════════
# JUPITER SWAP TOOL
# ═══════════════════════════════════════════════════════════════════

@mcp.tool(
    description="""Swap any Solana token using Jupiter aggregator (best price routing).
    
    Use this for:
    - Tokens that have graduated from Pump.fun
    - Any SPL token swap (SOL→USDC, SOL→any token, token→token)
    - When you need best execution price across Raydium, Orca, Meteora, etc.
    
    Common mint addresses:
    - SOL: So11111111111111111111111111111111111111112  
    - USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
    - USDT: Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB
    """
)
async def jupiter_swap(
    ctx: Context,
    input_mint: str,
    output_mint: str,
    amount_sol: float,
    reasoning: str,
    slippage_bps: int = 50,
    amount_in_sol: bool = True,
) -> dict:
    """
    Swap tokens via Jupiter.
    
    Args:
        input_mint: Mint address of token to sell
        output_mint: Mint address of token to buy
        amount_sol: Amount to swap (in SOL if amount_in_sol=True)
        reasoning: Why you're making this swap
        slippage_bps: Slippage tolerance (50 = 0.5%)
        amount_in_sol: True if amount is in SOL, False for raw lamports
    """
    agent_id = _get_agent_id(ctx)
    
    try:
        risk_flags = check_guardrails("jupiter_swap", {
            "sol_amount": amount_sol, "slippage_bps": slippage_bps
        })
    except GuardrailError as e:
        return {"status": "blocked", "reason": str(e)}
    
    # Get a preview quote for the proposal
    quote_preview = None
    if not risk_limits.paper_mode:
        amount_lamports = int(amount_sol * 1e9) if amount_in_sol else int(amount_sol)
        quote_preview = await jupiter_client.get_quote(
            input_mint, output_mint, amount_lamports, slippage_bps
        )
    
    proposal_id = proposal_db.create_proposal(
        tool_name="jupiter_swap",
        params={"input_mint": input_mint, "output_mint": output_mint,
                "amount_sol": amount_sol, "slippage_bps": slippage_bps,
                "amount_in_sol": amount_in_sol,
                "quote_preview": quote_preview},
        agent_id=agent_id, reasoning=reasoning,
        risk_flags=risk_flags, paper_mode=risk_limits.paper_mode
    )
    
    if risk_limits.require_approval:
        response = {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "message": f"Swap proposal #{proposal_id} queued for review",
            "risk_flags": risk_flags
        }
        if quote_preview:
            response["quote"] = {
                "out_amount": int(quote_preview.get("outAmount", 0)) / 1e9,
                "price_impact_pct": quote_preview.get("priceImpactPct"),
                "route_plan": [r.get("swapInfo", {}).get("label") 
                               for r in quote_preview.get("routePlan", [])]
            }
        return response
    
    result = await jupiter_client.swap(
        input_mint, output_mint, amount_sol,
        slippage_bps, paper_mode=risk_limits.paper_mode, amount_in_sol=amount_in_sol
    )
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED,
                              result=str(result), tx_sig=result.get("tx_signature"))
    return result


# ═══════════════════════════════════════════════════════════════════
# x402 PAYMENT TOOL
# ═══════════════════════════════════════════════════════════════════

@mcp.tool(
    description="""Make an x402 micropayment to access a paid API or data resource.
    
    x402 is the HTTP 402 Payment Required standard for autonomous AI payments.
    Use this when you need to access a resource that requires a small USDC payment.
    The payment is made on Solana (or Base) and the resource is returned.
    
    Max payment is enforced — if the resource costs more, the payment is declined.
    """
)
async def make_x402_payment(
    ctx: Context,
    url: str,
    max_amount_usdc: float,
    reasoning: str,
    purpose: str = "",
) -> dict:
    """
    Make an x402 micropayment.
    
    Args:
        url: URL of the paid resource
        max_amount_usdc: Maximum you're willing to pay in USDC
        reasoning: Why this data/resource is needed
        purpose: Brief description of what the resource is for
    """
    agent_id = _get_agent_id(ctx)
    
    # Hard limit on micropayments
    if max_amount_usdc > 5.0:
        return {
            "status": "blocked",
            "reason": "x402 payments capped at $5 USDC per request"
        }
    
    proposal_id = proposal_db.create_proposal(
        tool_name="make_x402_payment",
        params={"url": url, "max_amount_usdc": max_amount_usdc, "purpose": purpose},
        agent_id=agent_id, reasoning=reasoning,
        risk_flags=[], paper_mode=risk_limits.paper_mode
    )
    
    if risk_limits.require_approval:
        return {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "message": f"Payment proposal #{proposal_id} queued for review",
        }
    
    result = await x402_client.make_payment(
        url, max_amount_usdc, purpose,
        paper_mode=risk_limits.paper_mode
    )
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED, result=str(result))
    return result


# ═══════════════════════════════════════════════════════════════════
# GENERAL PROPOSE TRADE TOOL
# ═══════════════════════════════════════════════════════════════════

@mcp.tool(
    description="""General trade proposal tool. Use this for complex multi-step strategies 
    or when you want to describe a trade in natural language for human review.
    
    Unlike specific trade tools, this doesn't execute anything — it just creates a 
    well-structured proposal for the human to review and optionally convert to 
    specific trades.
    """
)
async def propose_trade(
    ctx: Context,
    trade_description: str,
    reasoning: str,
    estimated_sol_amount: float,
    trade_type: str,
    tokens_involved: list[str],
    risk_assessment: str,
    time_sensitivity: str = "low",
) -> dict:
    """
    Propose a general trade for human review.
    
    Args:
        trade_description: Natural language description of the trade
        reasoning: Detailed reasoning for why this trade makes sense
        estimated_sol_amount: Estimated SOL involved
        trade_type: One of: "buy", "sell", "swap", "create_token", "multi_step"
        tokens_involved: List of token addresses or names
        risk_assessment: Your assessment of the trade risks
        time_sensitivity: "low", "medium", "high" - urgency of the trade
    """
    agent_id = _get_agent_id(ctx)
    
    try:
        check_guardrails("propose_trade", {"sol_amount": estimated_sol_amount})
    except GuardrailError as e:
        return {"status": "blocked", "reason": str(e)}
    
    risk_flags = []
    if time_sensitivity == "high":
        risk_flags.append("TIME_SENSITIVE: Agent marked as urgent")
    if estimated_sol_amount > risk_limits.max_trade_sol * 0.5:
        risk_flags.append(f"LARGE_TRADE: {estimated_sol_amount} SOL")
    
    proposal_id = proposal_db.create_proposal(
        tool_name="propose_trade",
        params={
            "description": trade_description,
            "trade_type": trade_type,
            "tokens": tokens_involved,
            "estimated_sol": estimated_sol_amount,
            "risk_assessment": risk_assessment,
            "time_sensitivity": time_sensitivity
        },
        agent_id=agent_id, reasoning=reasoning,
        risk_flags=risk_flags, paper_mode=True  # always paper for general proposals
    )
    
    return {
        "status": "pending_approval",
        "proposal_id": proposal_id,
        "message": f"Trade proposal #{proposal_id} submitted for human review",
        "review_url": "http://localhost:8501",
        "risk_flags": risk_flags
    }


# ═══════════════════════════════════════════════════════════════════
# UTILITY / READ TOOLS
# ═══════════════════════════════════════════════════════════════════

@mcp.tool(description="Get current portfolio balances and open proposals summary.")
async def get_portfolio(ctx: Context) -> dict:
    """Returns SOL balance, pending proposals count, and daily spend."""
    balance = 0.0
    try:
        balance = await turnkey_client.get_wallet_balance()
    except Exception:
        balance = -1  # unavailable
    
    pending = proposal_db.list_proposals(status="pending")
    daily_spend = proposal_db.get_daily_spend()
    
    return {
        "wallet_address": turnkey_client.wallet_address or "not_configured",
        "sol_balance": balance,
        "network": settings.solana_network,
        "paper_mode": risk_limits.paper_mode,
        "pending_proposals": len(pending),
        "daily_spend_sol": daily_spend,
        "daily_limit_sol": risk_limits.max_daily_sol,
        "require_approval": risk_limits.require_approval
    }


@mcp.tool(description="Check the status of a previously submitted trade proposal.")
async def check_proposal(ctx: Context, proposal_id: str) -> dict:
    """Check status of a proposal by its ID."""
    proposal = proposal_db.get_proposal(proposal_id)
    if not proposal:
        return {"status": "not_found", "proposal_id": proposal_id}
    return proposal


@mcp.tool(description="Get current risk limits and server configuration.")
async def get_risk_limits(ctx: Context) -> dict:
    """Returns current risk limits in effect."""
    risk_limits.reload()
    return {
        "max_trade_sol": risk_limits.max_trade_sol,
        "max_daily_sol": risk_limits.max_daily_sol,
        "max_slippage_bps": risk_limits.max_slippage_bps,
        "require_approval": risk_limits.require_approval,
        "paper_mode": risk_limits.paper_mode,
        "blocked_tokens": risk_limits.blocked_tokens,
        "allowed_programs": risk_limits.allowed_programs
    }


@mcp.tool(
    description="""Get a price quote for a Jupiter swap without executing it.
    Use this to research prices before proposing a trade."""
)
async def get_swap_quote(
    ctx: Context,
    input_mint: str,
    output_mint: str,
    amount_sol: float
) -> dict:
    """Get a price quote (read-only, no proposal created)."""
    amount_lamports = int(amount_sol * 1e9)
    quote = await jupiter_client.get_quote(input_mint, output_mint, amount_lamports)
    if not quote:
        return {"status": "error", "error": "Could not fetch quote"}
    return {
        "input_mint": input_mint,
        "output_mint": output_mint,
        "amount_in_sol": amount_sol,
        "out_amount": int(quote.get("outAmount", 0)) / 1e9,
        "price_impact_pct": quote.get("priceImpactPct"),
        "route": [r.get("swapInfo", {}).get("label") 
                  for r in quote.get("routePlan", [])],
    }


# ═══════════════════════════════════════════════════════════════════
# APPROVAL API (called from dashboard)
# ═══════════════════════════════════════════════════════════════════

# These are exposed as MCP resources, not tools, so the dashboard can call them

@mcp.resource("approval://execute/{proposal_id}")
async def execute_approved_proposal(proposal_id: str) -> str:
    """Execute an approved proposal (called by dashboard)."""
    proposal = proposal_db.get_proposal(proposal_id)
    if not proposal:
        return f"Proposal {proposal_id} not found"
    
    if proposal["status"] != "pending":
        return f"Proposal {proposal_id} is {proposal['status']}, not pending"
    
    params = json.loads(proposal["params"]) if isinstance(proposal["params"], str) else proposal["params"]
    tool_name = proposal["tool_name"]
    paper_mode = bool(proposal["paper_mode"])
    
    proposal_db.update_status(proposal_id, ProposalStatus.APPROVED)
    
    # Dispatch to correct handler
    result = await _dispatch_tool(tool_name, params, paper_mode)
    
    tx_sig = result.get("tx_signature") if isinstance(result, dict) else None
    proposal_db.update_status(proposal_id, ProposalStatus.EXECUTED,
                              result=str(result), tx_sig=tx_sig)
    
    sol_amount = float(params.get("sol_amount", params.get("amount_sol", 0)))
    if sol_amount > 0 and not paper_mode:
        proposal_db.add_daily_spend(sol_amount)
    
    import json as _json
    return _json.dumps(result)


async def _dispatch_tool(tool_name: str, params: dict, paper_mode: bool) -> dict:
    """Route an approved proposal to the correct client."""
    if tool_name == "buy_pumpfun_token":
        return await pumpfun_client.buy(
            params["mint_address"], params["sol_amount"],
            params.get("slippage_bps", 100), paper_mode
        )
    elif tool_name == "sell_pumpfun_token":
        return await pumpfun_client.sell(
            params["mint_address"], params["token_amount"],
            params.get("slippage_bps", 100), paper_mode
        )
    elif tool_name == "create_pumpfun_token":
        return await pumpfun_client.create_token(
            params["name"], params["symbol"], params["description"],
            params["image_url"], params.get("initial_buy_sol", 0), paper_mode
        )
    elif tool_name == "jupiter_swap":
        return await jupiter_client.swap(
            params["input_mint"], params["output_mint"],
            params["amount_sol"], params.get("slippage_bps", 50),
            paper_mode, params.get("amount_in_sol", True)
        )
    elif tool_name == "make_x402_payment":
        return await x402_client.make_payment(
            params["url"], params["max_amount_usdc"],
            params.get("purpose", ""), paper_mode
        )
    else:
        return {"status": "error", "error": f"Unknown tool: {tool_name}"}


def _get_agent_id(ctx: Context) -> str:
    try:
        if ctx and ctx.client_id:
            return ctx.client_id
    except Exception:
        pass
    return "unknown"


import json

if __name__ == "__main__":
    import uvicorn
    # Run with SSE transport for broad agent compatibility
    uvicorn.run(
        mcp.http_app(path="/mcp"),
        host=settings.mcp_server_host,
        port=settings.mcp_server_port
    )

from .server_tools_addon import register_extra_tools
register_extra_tools(mcp)
