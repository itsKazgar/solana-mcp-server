#!/bin/bash
cd ~/solana-mcp-server
source venv/bin/activate

tmux kill-session -t trading 2>/dev/null

tmux new-session -d -s trading -x 220 -y 50

tmux rename-window -t trading:0 "MCP-Server"
tmux send-keys -t trading:0 "cd ~/solana-mcp-server && source venv/bin/activate && python main.py" Enter

tmux new-window -t trading:1 -n "Dashboard"
tmux send-keys -t trading:1 "cd ~/solana-mcp-server && source venv/bin/activate && streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true" Enter

tmux select-window -t trading:0

echo ""
echo "=================================="
echo "  MCP Server:  http://localhost:8000/mcp/"
echo "  Dashboard:   http://localhost:8501"
echo "  Attach:      tmux attach -t trading"
echo "=================================="
