# 🤖 Solana Trading MCP Server

An AI-powered Solana trading bot with a live dashboard, built on the MCP (Model Context Protocol) framework.

## Features
- MCP Server — exposes Solana trading tools via HTTP for any AI agent
- AI Agent — connects a local Ollama model (hermes3) to control the bot
- Live Dashboard — monitor trades, balances, and bot status
- Bot Studio — configure and control the bot from the browser
- Transaction Trail — full history of all transactions
- Paper Mode — test without real money

## Tech Stack
- Python, FastAPI, FastMCP 2.0
- Solana, solders, anchorpy
- Streamlit + Plotly dashboard
- LangChain + Ollama (hermes3)
- SQLite + Redis for state

## Setup

1. Clone the repo
```bash
git clone https://github.com/itsKazgar/solana-mcp-server.git
cd solana-mcp-server
```
2. Create virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
3. Copy and fill in your config
```bash
cp .env.example .env
```
4. Replace YOUR_IP in agent.py and mcp_config.json with your server IP
5. Start the server
```bash
python main.py
```
6. Start the dashboard
```bash
streamlit run dashboard/app.py
```

## Security
- Never commit your .env file
- Use PAPER_MODE=true before trading real funds
- Generate a strong token: openssl rand -hex 32

## License
MIT
