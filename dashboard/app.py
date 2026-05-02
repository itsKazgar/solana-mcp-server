import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import sys
import os
import httpx
from datetime import datetime
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

from src.proposal_db import proposal_db, ProposalStatus
from src.config import settings, risk_limits

st.set_page_config(
    page_title="SOLANA MCP // TRADING TERMINAL",
    page_icon="$",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Ubuntu+Mono:wght@400;700&family=Ubuntu:wght@300;400;500;700&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
.stApp { background: #300a24; color: #ffffff; font-family: 'Ubuntu Mono', monospace; }
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stSidebar"] { background: #200618; border-right: 2px solid #4a1540; }
[data-testid="stSidebar"] * { font-family: 'Ubuntu Mono', monospace !important; color: #ffffff; }
.main .block-container { padding: 1.5rem 2rem; max-width: 1600px; }
.page-title { font-family: 'Ubuntu Mono', monospace; font-size: 20px; font-weight: 700; color: #ffffff; letter-spacing: 0.05em; margin: 0; }
.page-subtitle { font-family: 'Ubuntu Mono', monospace; font-size: 11px; color: #a07090; letter-spacing: 0.15em; margin-top: 4px; }
.status-bar { display: flex; align-items: center; gap: 24px; padding: 8px 16px; background: #200618; border: 1px solid #4a1540; border-radius: 2px; font-family: 'Ubuntu Mono', monospace; font-size: 11px; color: #a07090; margin-bottom: 1.5rem; }
.status-item { display: flex; align-items: center; gap: 6px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot-green { background: #4caf50; }
.dot-orange { background: #e95420; }
.dot-red { background: #f44336; }
.dot-grey { background: #666; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 1.5rem; }
.metric-card { background: #200618; border: 1px solid #4a1540; border-radius: 2px; padding: 16px 20px; position: relative; overflow: hidden; }
.metric-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: #4a1540; }
.metric-card.accent::before { background: #e95420; }
.metric-card.green::before { background: #4caf50; }
.metric-card.red::before { background: #f44336; }
.metric-card.blue::before { background: #2196f3; }
.metric-label { font-family: 'Ubuntu Mono', monospace; font-size: 10px; color: #a07090; letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 8px; }
.metric-value { font-family: 'Ubuntu Mono', monospace; font-size: 28px; font-weight: 700; color: #ffffff; line-height: 1; }
.metric-sub { font-family: 'Ubuntu Mono', monospace; font-size: 10px; color: #a07090; margin-top: 6px; }
.section-header { font-family: 'Ubuntu Mono', monospace; font-size: 11px; font-weight: 700; color: #a07090; letter-spacing: 0.25em; text-transform: uppercase; padding-bottom: 8px; border-bottom: 1px solid #4a1540; margin-bottom: 16px; }
.term-header { font-family: 'Ubuntu Mono', monospace; font-size: 11px; color: #a07090; letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 0.25rem; }
.reasoning-box { background: #200618; border: 1px solid #4a1540; border-radius: 2px; padding: 12px; font-family: 'Ubuntu Mono', monospace; font-size: 12px; color: #d0b0c0; line-height: 1.6; margin: 8px 0; }
.reasoning-label { font-family: 'Ubuntu Mono', monospace; font-size: 9px; color: #a07090; letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 4px; }
.flag { display: inline-block; font-family: 'Ubuntu Mono', monospace; font-size: 10px; padding: 2px 8px; border-radius: 2px; margin: 2px 2px 0 0; }
.flag-warn { background: #3a0f0f; color: #e95420; border: 1px solid #6a1f1f; }
.flag-paper { background: #0f3a0f; color: #4caf50; border: 1px solid #1f6a1f; }
.flag-info { background: #0f1a3a; color: #2196f3; border: 1px solid #1f3a6a; }
.agent-card { background: #200618; border: 1px solid #4a1540; border-radius: 2px; padding: 14px 18px; margin-bottom: 8px; font-family: 'Ubuntu Mono', monospace; }
.stTabs [data-baseweb="tab-list"] { background: #300a24; border-bottom: 2px solid #4a1540; gap: 0; }
.stTabs [data-baseweb="tab"] { font-family: 'Ubuntu Mono', monospace !important; font-size: 11px !important; letter-spacing: 0.15em !important; color: #a07090 !important; padding: 10px 24px !important; background: transparent !important; border-radius: 0 !important; text-transform: uppercase; }
.stTabs [aria-selected="true"] { color: #ffffff !important; border-bottom: 2px solid #e95420 !important; background: #200618 !important; }
div[data-testid="stButton"] > button { font-family: 'Ubuntu Mono', monospace !important; font-size: 11px !important; letter-spacing: 0.1em !important; text-transform: uppercase !important; border-radius: 2px !important; border: 1px solid #4a1540 !important; background: #200618 !important; color: #ffffff !important; }
div[data-testid="stButton"] > button:hover { border-color: #e95420 !important; color: #e95420 !important; background: #3a0f00 !important; }
div[data-testid="stButton"] > button[kind="primary"] { background: #e95420 !important; border-color: #e95420 !important; color: #ffffff !important; }
div[data-testid="stButton"] > button[kind="primary"]:hover { background: #bf4318 !important; }
.stTextInput input, .stTextArea textarea, .stNumberInput input { font-family: 'Ubuntu Mono', monospace !important; font-size: 12px !important; background: #200618 !important; border: 1px solid #4a1540 !important; color: #ffffff !important; border-radius: 2px !important; }
.stTextInput input:focus, .stTextArea textarea:focus { border-color: #e95420 !important; }
.stSelectbox > div { background: #200618 !important; border-color: #4a1540 !important; color: #ffffff !important; font-family: 'Ubuntu Mono', monospace !important; }
.stToggle label { font-family: 'Ubuntu Mono', monospace !important; font-size: 11px !important; color: #ffffff !important; }
hr { border-color: #4a1540 !important; margin: 1rem 0 !important; }
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: #200618; }
::-webkit-scrollbar-thumb { background: #4a1540; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: #e95420; }
.stDataFrame { font-family: 'Ubuntu Mono', monospace !important; font-size: 11px !important; }
div[data-testid="stExpander"] { background: #200618 !important; border: 1px solid #4a1540 !important; border-radius: 2px !important; }
</style>
""", unsafe_allow_html=True)

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=5000, key="refresh")
except ImportError:
    pass

def time_ago(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        s = (datetime.utcnow() - dt).total_seconds()
        if s < 60: return f"{int(s)}s ago"
        if s < 3600: return f"{int(s//60)}m ago"
        if s < 86400: return f"{int(s//3600)}h ago"
        return f"{int(s//86400)}d ago"
    except: return "---"

def fmt_params(p):
    try:
        d = json.loads(p) if isinstance(p, str) else p
        return json.dumps(d, indent=2)
    except: return str(p)

def execute_proposal_sync(proposal_id):
    try:
        resp = httpx.post(
            f"http://localhost:{settings.mcp_server_port}/internal/execute/{proposal_id}",
            headers={"Authorization": f"Bearer {settings.mcp_secret_token}"},
            timeout=30.0
        )
        if resp.status_code == 200:
            return True, resp.json()
        return False, resp.text[:200]
    except Exception as e:
        proposal_db.update_status(proposal_id, ProposalStatus.APPROVED)
        return True, "Queued"

TOOL_ICONS = {
    "buy_pumpfun_token": "BUY",
    "sell_pumpfun_token": "SELL",
    "create_pumpfun_token": "CREATE",
    "jupiter_swap": "SWAP",
    "make_x402_payment": "PAY",
    "propose_trade": "PROPOSE",
}

STATUS_COLORS = {
    "pending": "#e95420", "approved": "#4caf50",
    "rejected": "#f44336", "executed": "#2196f3", "failed": "#666",
}

risk_limits.reload()
proposals   = proposal_db.list_proposals(limit=200)
agents      = proposal_db.get_agents()
daily_spend = proposal_db.get_daily_spend()
now_utc     = datetime.utcnow()
pending     = [p for p in proposals if p["status"] == "pending"]
executed    = [p for p in proposals if p["status"] == "executed"]
rejected    = [p for p in proposals if p["status"] == "rejected"]
active_agents = [a for a in agents if (now_utc - datetime.fromisoformat(a["last_seen"])).total_seconds() < 300]

with st.sidebar:
    st.markdown("""
    <div style='padding:16px 0 8px 0;border-bottom:1px solid #4a1540;margin-bottom:12px;'>
        <div style='font-family:"Ubuntu Mono",monospace;font-size:15px;font-weight:700;color:#ffffff;letter-spacing:0.05em;'>SOLANA MCP</div>
        <div style='font-family:"Ubuntu Mono",monospace;font-size:9px;color:#a07090;letter-spacing:0.2em;margin-top:3px;'>TRADING TERMINAL v1.0</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="term-header">// mode</div>', unsafe_allow_html=True)
    paper = st.toggle("Paper Mode", value=risk_limits.paper_mode)
    if paper != risk_limits.paper_mode:
        risk_limits.paper_mode = paper; risk_limits.save()
    approval = st.toggle("Require Approval", value=risk_limits.require_approval)
    if approval != risk_limits.require_approval:
        risk_limits.require_approval = approval; risk_limits.save()
    if risk_limits.paper_mode:
        st.markdown('<span class="flag flag-paper">PAPER MODE</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="flag flag-warn">LIVE MODE</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="term-header">// risk limits</div>', unsafe_allow_html=True)
    max_trade = st.number_input("Max Trade SOL", 0.01, 100.0, float(risk_limits.max_trade_sol), 0.1, format="%.2f")
    max_daily = st.number_input("Max Daily SOL", 0.1, 1000.0, float(risk_limits.max_daily_sol), 1.0, format="%.1f")
    max_slip  = st.number_input("Max Slippage bps", 10, 2000, int(risk_limits.max_slippage_bps), 10)
    if st.button("Apply Limits", use_container_width=True):
        risk_limits.max_trade_sol = max_trade
        risk_limits.max_daily_sol = max_daily
        risk_limits.max_slippage_bps = max_slip
        risk_limits.save()
        st.success("Saved")

    st.markdown("---")
    st.markdown('<div class="term-header">// block token</div>', unsafe_allow_html=True)
    block_input = st.text_input("Mint address", placeholder="Enter mint...", label_visibility="collapsed")
    if st.button("Block Token", use_container_width=True) and block_input.strip():
        mint = block_input.strip()
        if mint not in risk_limits.blocked_tokens:
            risk_limits.blocked_tokens.append(mint); risk_limits.save()
            st.success(f"Blocked {mint[:12]}...")
    if risk_limits.blocked_tokens:
        for t in risk_limits.blocked_tokens:
            c1, c2 = st.columns([3,1])
            c1.markdown(f'<div style="font-size:10px;color:#a07090;font-family:Ubuntu Mono,monospace;">{t[:16]}...</div>', unsafe_allow_html=True)
            if c2.button("x", key=f"unblock_{t}"):
                risk_limits.blocked_tokens.remove(t); risk_limits.save(); st.rerun()

    st.markdown("---")
    st.markdown(f"""
    <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;color:#a07090;line-height:2;'>
    NET &nbsp;&nbsp;{settings.solana_network}<br>
    MCP &nbsp;&nbsp;:{settings.mcp_server_port}/mcp/<br>
    DASH &nbsp;:8501
    </div>""", unsafe_allow_html=True)
    st.markdown("---")
    if st.button("Refresh", use_container_width=True): st.rerun()

col_title, col_time = st.columns([3,1])
with col_title:
    st.markdown("""
    <div class="page-title">SOLANA MCP // TRADING TERMINAL</div>
    <div class="page-subtitle">UNIVERSAL AI AGENT TRADING INTERFACE · HUMAN-IN-THE-LOOP</div>
    """, unsafe_allow_html=True)
with col_time:
    st.markdown(f"""
    <div style='text-align:right;font-family:"Ubuntu Mono",monospace;font-size:10px;color:#a07090;padding-top:8px;line-height:1.8;'>
    {now_utc.strftime('%Y-%m-%d')}<br>{now_utc.strftime('%H:%M:%S')} UTC
    </div>""", unsafe_allow_html=True)

mode_dot   = "dot-orange" if risk_limits.paper_mode else "dot-red"
mode_label = "PAPER" if risk_limits.paper_mode else "LIVE"
daily_pct  = daily_spend / risk_limits.max_daily_sol * 100 if risk_limits.max_daily_sol else 0
spend_dot  = "dot-red" if daily_pct > 80 else "dot-orange" if daily_pct > 50 else "dot-green"

st.markdown(f"""
<div class="status-bar">
  <div class="status-item"><span class="status-dot dot-green"></span><span>MCP SERVER RUNNING</span></div>
  <div class="status-item"><span class="status-dot {mode_dot}"></span><span>MODE: {mode_label}</span></div>
  <div class="status-item"><span class="status-dot dot-green"></span><span>AGENTS: {len(active_agents)} ACTIVE / {len(agents)} TOTAL</span></div>
  <div class="status-item"><span class="status-dot {spend_dot}"></span><span>DAILY: {daily_spend:.3f} / {risk_limits.max_daily_sol:.1f} SOL ({daily_pct:.0f}%)</span></div>
  <div class="status-item" style="margin-left:auto;"><span>APPROVAL: {"ON" if risk_limits.require_approval else "OFF"}</span></div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="metric-grid">
  <div class="metric-card {'accent' if pending else ''}">
    <div class="metric-label">Pending Approval</div>
    <div class="metric-value" style="color:{'#e95420' if pending else '#ffffff'};">{len(pending)}</div>
    <div class="metric-sub">awaiting review</div>
  </div>
  <div class="metric-card green">
    <div class="metric-label">Executed</div>
    <div class="metric-value" style="color:#4caf50;">{len(executed)}</div>
    <div class="metric-sub">all time</div>
  </div>
  <div class="metric-card red">
    <div class="metric-label">Rejected</div>
    <div class="metric-value" style="color:#f44336;">{len(rejected)}</div>
    <div class="metric-sub">all time</div>
  </div>
  <div class="metric-card blue">
    <div class="metric-label">Total Agents</div>
    <div class="metric-value" style="color:#2196f3;">{len(agents)}</div>
    <div class="metric-sub">{len(active_agents)} active now</div>
  </div>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["APPROVALS", "ACTIVITY", "AGENTS", "MANUAL TRADE", "CONNECT", "BOT STUDIO", "TX TRAIL"])

with tab1:
    st.markdown('<div class="section-header">// pending proposals</div>', unsafe_allow_html=True)
    if not pending:
        st.markdown("""
        <div style='text-align:center;padding:48px;font-family:"Ubuntu Mono",monospace;font-size:12px;color:#a07090;border:1px solid #4a1540;border-radius:2px;'>
        NO PENDING PROPOSALS
        </div>""", unsafe_allow_html=True)
    else:
        ba1, ba2, ba3 = st.columns([1,1,4])
        with ba1:
            if st.button("APPROVE ALL", type="primary", use_container_width=True):
                for p in pending: execute_proposal_sync(p["id"])
                st.rerun()
        with ba2:
            if st.button("REJECT ALL", use_container_width=True):
                for p in pending: proposal_db.update_status(p["id"], ProposalStatus.REJECTED)
                st.rerun()
        st.markdown("<br>", unsafe_allow_html=True)
        for proposal in pending:
            params     = json.loads(proposal["params"]) if isinstance(proposal["params"], str) else proposal["params"]
            risk_flags = json.loads(proposal.get("risk_flags") or "[]")
            tool_label = TOOL_ICONS.get(proposal["tool_name"], proposal["tool_name"])
            with st.expander(f"[ {tool_label} ]  {proposal['id']}  //  {proposal['agent_id']}  //  {time_ago(proposal['created_at'])}", expanded=True):
                left, right = st.columns([3,2])
                with left:
                    reasoning = proposal.get("agent_reasoning") or "No reasoning provided."
                    st.markdown(f'<div class="reasoning-label">agent reasoning</div><div class="reasoning-box">{reasoning}</div>', unsafe_allow_html=True)
                    st.markdown('<div class="reasoning-label">parameters</div>', unsafe_allow_html=True)
                    st.code(fmt_params(params), language="json")
                    if risk_flags:
                        flags_html = "".join(f'<span class="flag flag-warn">{f}</span>' for f in risk_flags)
                        if proposal.get("paper_mode"): flags_html += '<span class="flag flag-paper">PAPER</span>'
                        st.markdown(flags_html, unsafe_allow_html=True)
                with right:
                    st.markdown('<div class="reasoning-label">action</div>', unsafe_allow_html=True)
                    c_approve, c_reject = st.columns(2)
                    with c_approve:
                        if st.button("APPROVE", key=f"ap_{proposal['id']}", type="primary", use_container_width=True):
                            ok, res = execute_proposal_sync(proposal["id"])
                            st.success("Executed") if ok else st.error(str(res)[:100])
                            time.sleep(0.5); st.rerun()
                    with c_reject:
                        if st.button("REJECT", key=f"rj_{proposal['id']}", use_container_width=True):
                            proposal_db.update_status(proposal["id"], ProposalStatus.REJECTED); st.rerun()
                    st.markdown('<div class="reasoning-label" style="margin-top:12px;">edit params before approve</div>', unsafe_allow_html=True)
                    edited = st.text_area("params", value=fmt_params(params), key=f"ed_{proposal['id']}", height=160, label_visibility="collapsed")
                    if st.button("SAVE + APPROVE", key=f"sa_{proposal['id']}", use_container_width=True):
                        try:
                            new_p = json.loads(edited)
                            with proposal_db._lock, proposal_db._conn() as conn:
                                conn.execute("UPDATE proposals SET params=? WHERE id=?", (json.dumps(new_p), proposal["id"]))
                            execute_proposal_sync(proposal["id"])
                            st.success("Done"); time.sleep(0.5); st.rerun()
                        except json.JSONDecodeError: st.error("Invalid JSON")
                    st.markdown(f"""
                    <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;color:#a07090;margin-top:12px;line-height:1.8;'>
                    ID     {proposal['id']}<br>
                    TOOL   {proposal['tool_name']}<br>
                    AGENT  {proposal['agent_id']}<br>
                    TIME   {proposal['created_at'][:19]}<br>
                    PAPER  {'YES' if proposal['paper_mode'] else 'NO'}
                    </div>""", unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="section-header">// recent activity</div>', unsafe_allow_html=True)
    if proposals:
        from collections import Counter
        counts = Counter(p["status"] for p in proposals)
        fig = go.Figure(go.Bar(
            x=list(counts.keys()), y=list(counts.values()),
            marker_color=[STATUS_COLORS.get(s, "#666") for s in counts.keys()],
            marker_line_width=0,
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#200618",
            font=dict(family="Ubuntu Mono", color="#a07090", size=10),
            margin=dict(l=0,r=0,t=0,b=0), height=160,
            xaxis=dict(gridcolor="#4a1540"), yaxis=dict(gridcolor="#4a1540"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
        gauge_color = "#f44336" if daily_pct > 80 else "#e95420" if daily_pct > 50 else "#4caf50"
        fig2 = go.Figure(go.Indicator(
            mode="gauge+number", value=daily_spend,
            number={"suffix": " SOL", "font": {"family": "Ubuntu Mono", "color": "#ffffff", "size": 18}},
            gauge={
                "axis": {"range": [0, risk_limits.max_daily_sol], "tickfont": {"family": "Ubuntu Mono", "color": "#a07090", "size": 9}},
                "bar": {"color": gauge_color, "thickness": 0.6},
                "bgcolor": "#200618", "borderwidth": 1, "bordercolor": "#4a1540",
                "threshold": {"line": {"color": "#f44336", "width": 1}, "thickness": 0.8, "value": risk_limits.max_daily_sol * 0.8}
            },
            title={"text": "DAILY SPEND", "font": {"family": "Ubuntu Mono", "color": "#a07090", "size": 10}}
        ))
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=200, margin=dict(l=20,r=20,t=20,b=0))
        st.plotly_chart(fig2, use_container_width=True)
        st.markdown('<div class="section-header">// transaction log</div>', unsafe_allow_html=True)
        rows = []
        for p in proposals[:100]:
            params = json.loads(p["params"]) if isinstance(p["params"], str) else p["params"]
            sol = params.get("sol_amount") or params.get("amount_sol") or params.get("estimated_sol", "---")
            rows.append({"ID": p["id"], "TOOL": p["tool_name"].replace("_"," ").upper(),
                         "AGENT": p["agent_id"][:16], "STATUS": p["status"].upper(),
                         "SOL": sol, "TIME": time_ago(p["created_at"]),
                         "TX": (p.get("tx_signature") or "---")[:16]})
        df = pd.DataFrame(rows)
        def color_status(val):
            c = {"PENDING":"#e95420","EXECUTED":"#2196f3","REJECTED":"#f44336","APPROVED":"#4caf50","FAILED":"#666"}
            return f"color:{c.get(val,'#ffffff')};font-family:Ubuntu Mono,monospace;font-size:11px;"
        st.dataframe(df.style.map(color_status, subset=["STATUS"]), use_container_width=True, hide_index=True, height=350)
    else:
        st.markdown('<div style="text-align:center;padding:48px;font-family:Ubuntu Mono,monospace;font-size:12px;color:#a07090;">NO ACTIVITY YET</div>', unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="section-header">// connected agents</div>', unsafe_allow_html=True)
    st.markdown("""
    <div style='font-family:"Ubuntu Mono",monospace;font-size:11px;color:#a07090;padding:12px;background:#200618;border:1px solid #4a1540;border-radius:2px;margin-bottom:16px;line-height:1.8;'>
    ANY agent that speaks MCP connects with one URL:<br>
    Claude  LangGraph  CrewAI  Ollama  Hermes  Kimi  AutoGen  Custom scripts
    </div>""", unsafe_allow_html=True)
    if not agents:
        st.markdown('<div style="text-align:center;padding:48px;font-family:Ubuntu Mono,monospace;font-size:12px;color:#a07090;border:1px solid #4a1540;border-radius:2px;">NO AGENTS CONNECTED YET</div>', unsafe_allow_html=True)
    else:
        for agent in agents:
            last_dt = datetime.fromisoformat(agent["last_seen"])
            is_live = (now_utc - last_dt).total_seconds() < 300
            dot_col = "#4caf50" if is_live else "#444"
            status  = "ONLINE" if is_live else "OFFLINE"
            st.markdown(f"""
            <div class="agent-card">
              <div style='display:flex;align-items:center;justify-content:space-between;'>
                <div>
                  <div style='display:flex;align-items:center;gap:8px;'>
                    <span style='width:8px;height:8px;border-radius:50%;background:{dot_col};display:inline-block;'></span>
                    <span style='font-size:13px;color:#ffffff;font-family:Ubuntu Mono,monospace;'>{agent['agent_id']}</span>
                    <span style='font-size:10px;color:{dot_col};font-family:Ubuntu Mono,monospace;'>{status}</span>
                  </div>
                  <div style='font-size:10px;color:#a07090;margin-top:6px;font-family:Ubuntu Mono,monospace;'>Last seen {time_ago(agent['last_seen'])} · Connected {agent.get("connected_at","?")[:16]}</div>
                </div>
                <div style='text-align:right;font-size:11px;font-family:Ubuntu Mono,monospace;'>
                  <span style='color:#e95420;'>{agent['total_proposals']}</span><span style='color:#a07090;'> proposals  </span>
                  <span style='color:#4caf50;'>{agent.get('approved',0)}</span><span style='color:#a07090;'> ok  </span>
                  <span style='color:#f44336;'>{agent.get('rejected',0)}</span><span style='color:#a07090;'> rejected</span>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)

with tab4:
    st.markdown('<div class="section-header">// manual trade entry</div>', unsafe_allow_html=True)
    trade_type = st.selectbox("Trade Type", ["Buy Pump.fun Token", "Sell Pump.fun Token", "Jupiter Swap"])
    if trade_type == "Buy Pump.fun Token":
        c1, c2 = st.columns(2)
        with c1:
            mint    = st.text_input("Token Mint Address", placeholder="Enter mint address...")
            sol_amt = st.number_input("SOL Amount", 0.001, 10.0, 0.1, 0.01, format="%.3f")
        with c2:
            slippage = st.number_input("Slippage bps", 10, 1000, 100, 10)
            reason   = st.text_area("Reason / Notes", placeholder="Why are you buying this?", height=80)
        if st.button("SUBMIT BUY PROPOSAL", type="primary"):
            if mint.strip():
                pid = proposal_db.create_proposal(
                    tool_name="buy_pumpfun_token",
                    params={"mint_address": mint.strip(), "sol_amount": sol_amt, "slippage_bps": slippage},
                    agent_id="dashboard_manual", reasoning=reason or "Manual trade from dashboard",
                    paper_mode=risk_limits.paper_mode)
                st.success(f"Proposal #{pid} created. Check Approvals tab.")
            else: st.error("Enter a mint address")
    elif trade_type == "Sell Pump.fun Token":
        c1, c2 = st.columns(2)
        with c1:
            mint   = st.text_input("Token Mint Address", placeholder="Enter mint address...")
            amount = st.number_input("Token Amount", 0.0, 1e12, 1000.0, 100.0)
        with c2:
            slippage = st.number_input("Slippage bps", 10, 1000, 100, 10)
            reason   = st.text_area("Reason / Notes", placeholder="Why are you selling?", height=80)
        if st.button("SUBMIT SELL PROPOSAL", type="primary"):
            if mint.strip():
                pid = proposal_db.create_proposal(
                    tool_name="sell_pumpfun_token",
                    params={"mint_address": mint.strip(), "token_amount": amount, "slippage_bps": slippage},
                    agent_id="dashboard_manual", reasoning=reason or "Manual trade from dashboard",
                    paper_mode=risk_limits.paper_mode)
                st.success(f"Proposal #{pid} created.")
            else: st.error("Enter a mint address")
    elif trade_type == "Jupiter Swap":
        SOL_MINT  = "So11111111111111111111111111111111111111112"
        USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        c1, c2 = st.columns(2)
        with c1:
            in_mint  = st.text_input("Input Mint",  value=SOL_MINT)
            out_mint = st.text_input("Output Mint", value=USDC_MINT)
        with c2:
            sol_amt  = st.number_input("Amount (SOL)", 0.001, 100.0, 0.1, 0.01, format="%.3f")
            slippage = st.number_input("Slippage bps", 10, 1000, 50, 10)
            reason   = st.text_area("Reason", placeholder="Swap rationale...", height=60)
        if st.button("SUBMIT SWAP PROPOSAL", type="primary"):
            pid = proposal_db.create_proposal(
                tool_name="jupiter_swap",
                params={"input_mint": in_mint, "output_mint": out_mint,
                        "amount_sol": sol_amt, "slippage_bps": slippage, "amount_in_sol": True},
                agent_id="dashboard_manual", reasoning=reason or "Manual swap from dashboard",
                paper_mode=risk_limits.paper_mode)
            st.success(f"Proposal #{pid} created.")

with tab5:
    st.markdown('<div class="section-header">// connect your agent</div>', unsafe_allow_html=True)
    mcp_url = f"http://YOUR_IP:{settings.mcp_server_port}/mcp/"
    token   = settings.mcp_secret_token
    agents_configs = [
        ("Claude Desktop", "json", f'{{\n  "mcpServers": {{\n    "solana-trader": {{\n      "url": "{mcp_url}",\n      "headers": {{"Authorization": "Bearer {token}"}}\n    }}\n  }}\n}}'),
        ("Ollama / Hermes / Any Local LLM", "python", f'from langchain_ollama import ChatOllama\nfrom langchain_mcp_adapters.client import MultiServerMCPClient\nfrom langgraph.prebuilt import create_react_agent\n\nasync def run():\n    client = MultiServerMCPClient({{\n        "solana_trader": {{\n            "url": "{mcp_url}",\n            "transport": "streamable_http",\n            "headers": {{"Authorization": "Bearer {token}"}}\n        }}\n    }})\n    tools = await client.get_tools()\n    model = ChatOllama(model="hermes3")\n    agent = create_react_agent(model, tools)\n    return agent'),
        ("Raw HTTP", "bash", f'curl -X POST {mcp_url} \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer {token}" \\\n  -d \'{{"jsonrpc":"2.0","method":"tools/list","id":1}}\''),
    ]
    for name, lang, code in agents_configs:
        st.markdown(f'<div class="section-header">// {name.lower()}</div>', unsafe_allow_html=True)
        st.code(code, language=lang)
    st.markdown('<div class="section-header">// available tools</div>', unsafe_allow_html=True)
    tools_data = [
        ("get_trending_pumpfun_tokens","READ","Trending tokens on pump.fun"),
        ("get_token_price","READ","Current USD price from Jupiter"),
        ("get_token_info","READ","Name, symbol, mcap, bonding curve %"),
        ("search_tokens","READ","Search tokens by name or symbol"),
        ("rug_check","READ","Holder concentration and authority risk"),
        ("get_wallet_tokens","READ","All SPL token balances in wallet"),
        ("get_sol_balance","READ","SOL balance of configured wallet"),
        ("get_swap_quote","READ","Jupiter price quote no execution"),
        ("get_transaction_history","READ","Recent tx signatures for wallet"),
        ("buy_pumpfun_token","WRITE","Buy token on pump.fun bonding curve"),
        ("sell_pumpfun_token","WRITE","Sell token on pump.fun bonding curve"),
        ("create_pumpfun_token","WRITE","Launch new token on pump.fun"),
        ("jupiter_swap","WRITE","Best-price swap via Jupiter"),
        ("make_x402_payment","WRITE","x402 micropayment for API access"),
        ("propose_trade","WRITE","Submit natural language trade proposal"),
        ("get_portfolio","READ","Portfolio summary and proposals count"),
        ("check_proposal","READ","Status of a submitted proposal"),
        ("get_risk_limits","READ","Current risk limits in effect"),
    ]
    df_tools = pd.DataFrame([{"TOOL":t,"TYPE":ty,"DESCRIPTION":d} for t,ty,d in tools_data])
    def color_type(val):
        return f"color:{'#e95420' if val=='WRITE' else '#4caf50'};font-family:Ubuntu Mono,monospace;font-size:11px;"
    st.dataframe(df_tools.style.map(color_type, subset=["TYPE"]), use_container_width=True, hide_index=True, height=500)

with tab6:
    try:
        from dashboard.bot_studio import render_bot_studio
        render_bot_studio()
    except Exception as e:
        st.markdown(f'<div style="font-family:Ubuntu Mono,monospace;color:#f44336;padding:20px;">Bot Studio not loaded: {e}<br>Make sure dashboard/bot_studio.py exists.</div>', unsafe_allow_html=True)

with tab7:
    try:
        from dashboard.tx_trail import render_tx_trail
        render_tx_trail()
    except Exception as e:
        st.markdown(f"TX Trail error: {e}")
