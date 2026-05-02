# main.py
"""
Main entrypoint — runs MCP server + internal execution API together.
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.server import mcp
from src.execution_api import internal_app
from src.config import settings
import structlog

log = structlog.get_logger()

# Combine MCP app with internal API
app = FastAPI(title="Solana Trading MCP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount MCP server at /mcp
mcp_app = mcp.http_app(path="/mcp")
app.mount("/mcp", mcp_app)

# Mount internal execution API
app.include_router(internal_app.router)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "paper_mode": settings.paper_mode,
        "network": settings.solana_network
    }

if __name__ == "__main__":
    log.info("starting_server", 
             host=settings.mcp_server_host, 
             port=settings.mcp_server_port)
    uvicorn.run(
        "main:app",
        host=settings.mcp_server_host,
        port=settings.mcp_server_port,
        reload=False,
        log_level="info"
    )
