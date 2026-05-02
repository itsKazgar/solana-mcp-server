# src/execution_api.py
"""
Internal HTTP API called by the dashboard to execute approved proposals.
Mounted alongside the MCP server.
"""
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
import asyncio

from .config import settings
from .proposal_db import proposal_db, ProposalStatus

internal_app = FastAPI(title="Internal Execution API")

@internal_app.post("/internal/execute/{proposal_id}")
async def execute_proposal(
    proposal_id: str,
    authorization: str = Header(None)
):
    """Called by dashboard to execute an approved proposal."""
    # Auth check
    expected = f"Bearer {settings.mcp_secret_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    proposal = proposal_db.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    if proposal["status"] not in ("pending", "approved"):
        return JSONResponse({"error": f"Cannot execute: status={proposal['status']}"})
    
    import json
    from .server import _dispatch_tool
    
    params = json.loads(proposal["params"]) if isinstance(proposal["params"], str) else proposal["params"]
    paper_mode = bool(proposal["paper_mode"])
    
    result = await _dispatch_tool(proposal["tool_name"], params, paper_mode)
    
    tx_sig = result.get("tx_signature") if isinstance(result, dict) else None
    proposal_db.update_status(
        proposal_id, ProposalStatus.EXECUTED,
        result=json.dumps(result), tx_sig=tx_sig
    )
    
    return result
