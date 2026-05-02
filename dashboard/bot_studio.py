# dashboard/bot_studio.py
"""
Bot Studio — create, configure, run, and monitor trading bots.
Imported and rendered as a tab inside the main dashboard.
"""
import streamlit as st
import json
import pandas as pd
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.bot_engine import bot_db, bot_runner, generate_solana_wallet, encrypt, BotStatus
from src.config import risk_limits

# ── Strategy Templates ────────────────────────────────────────────
STRATEGY_TEMPLATES = {
    "DCA Buyer": {
        "strategy": "dca",
        "prompt": """You are a DCA (Dollar Cost Averaging) bot.
Every cycle, buy a fixed amount of SOL worth of the top trending pump.fun token by volume.
Ignore price fluctuations — just keep buying consistently.
Only buy tokens that are NOT yet graduated (still on bonding curve).
Skip any token you've already bought in the last 3 trades.""",
        "config": {
            "interval_seconds": 300,
            "max_sol_per_trade": 0.05,
            "paper_mode": True
        }
    },
    "Trend Sniper": {
        "strategy": "sniper",
        "prompt": """You are a trend-following sniper bot.
Look for pump.fun tokens with:
- Bonding curve < 30% (early stage)
- High recent volume relative to market cap
- Not yet graduated

Buy the ONE token that looks most promising.
If you already hold a position (check recent trades), only buy if it's a different token.
Sell any token where bonding curve > 80% (near graduation = sell pressure incoming).""",
        "config": {
            "interval_seconds": 60,
            "max_sol_per_trade": 0.1,
            "paper_mode": True
        }
    },
    "Momentum Trader": {
        "strategy": "momentum",
        "prompt": """You are a momentum trader.
Buy tokens that are rapidly climbing the trending list.
Look for tokens with market cap between $5,000 and $50,000 (sweet spot).
Only buy if bonding curve % is between 10% and 60%.
Take profit by selling when a token reaches bonding curve > 75%.
Never hold more than 3 positions at once.""",
        "config": {
            "interval_seconds": 120,
            "max_sol_per_trade": 0.08,
            "paper_mode": True
        }
    },
    "Safe DCA (USDC)": {
        "strategy": "dca_usdc",
        "prompt": """You are a conservative DCA bot focused on blue-chip Solana tokens.
Every cycle, swap SOL to USDC using Jupiter if SOL price seems high.
Or swap USDC back to SOL if SOL seems undervalued.
Never trade meme coins. Only SOL, USDC, USDT.
Keep 50% of portfolio in SOL and 50% in USDC at all times.""",
        "config": {
            "interval_seconds": 600,
            "max_sol_per_trade": 0.2,
            "paper_mode": True
        }
    },
    "Custom": {
        "strategy": "custom",
        "prompt": "",
        "config": {
            "interval_seconds": 120,
            "max_sol_per_trade": 0.1,
            "paper_mode": True
        }
    }
}

def time_ago(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        s = (datetime.utcnow() - dt).total_seconds()
        if s < 60: return f"{int(s)}s ago"
        if s < 3600: return f"{int(s//60)}m ago"
        if s < 86400: return f"{int(s//3600)}h ago"
        return f"{int(s//86400)}d ago"
    except: return "—"

def render_bot_studio():
    """Main render function — call this from dashboard tabs."""

    st.markdown('<div class="section-header">// bot studio</div>', unsafe_allow_html=True)

    # ── Top action bar ────────────────────────────────────────────
    col_new, col_refresh, col_info = st.columns([2, 1, 3])
    with col_new:
        if st.button("◆ Create New Bot", type="primary", use_container_width=True):
            st.session_state["show_create_bot"] = True
    with col_refresh:
        if st.button("↺ Refresh", use_container_width=True):
            st.rerun()
    with col_info:
        st.markdown("""
        <div style='font-family:"IBM Plex Mono",monospace;font-size:10px;color:#444;padding:8px;'>
        Bots use Claude AI to reason about trades. All wallets are generated locally and stored encrypted.
        Start in PAPER MODE first.
        </div>""", unsafe_allow_html=True)

    # ── Create Bot Modal ──────────────────────────────────────────
    if st.session_state.get("show_create_bot"):
        st.markdown("---")
        st.markdown('<div class="section-header">// new bot</div>', unsafe_allow_html=True)

        c1, c2 = st.columns([1, 1])
        with c1:
            bot_name = st.text_input("Bot Name", placeholder="e.g. Degen Sniper #1")
            template = st.selectbox("Strategy Template", list(STRATEGY_TEMPLATES.keys()))

            tpl = STRATEGY_TEMPLATES[template]

            # Wallet
            st.markdown('<div class="reasoning-label">wallet</div>', unsafe_allow_html=True)
            if st.button("⬡ Generate New Wallet", use_container_width=True):
                pub, priv = generate_solana_wallet()
                st.session_state["new_bot_wallet_pub"]  = pub
                st.session_state["new_bot_wallet_priv"] = priv

            wallet_pub = st.session_state.get("new_bot_wallet_pub", "")
            if wallet_pub:
                st.markdown(f"""
                <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;
                            color:#4caf50;padding:8px;background:#001500;
                            border:1px solid #1a3a1a;border-radius:3px;word-break:break-all;'>
                ✓ {wallet_pub}<br>
                <span style='color:#333;font-size:9px;'>Private key stored encrypted locally</span>
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;color:#444;
                            padding:8px;background:#0a0a0a;border:1px solid #1e1e1e;border-radius:3px;'>
                No wallet yet — click Generate
                </div>""", unsafe_allow_html=True)

        with c2:
            # Strategy prompt
            prompt = st.text_area(
                "Strategy Prompt",
                value=tpl["prompt"],
                height=200,
                help="Tell the bot exactly how to trade. Be specific."
            )

            # Config
            st.markdown('<div class="reasoning-label">config</div>', unsafe_allow_html=True)
            cc1, cc2 = st.columns(2)
            with cc1:
                interval = st.number_input("Interval (seconds)", 10, 3600,
                                            tpl["config"]["interval_seconds"], 10)
                max_sol  = st.number_input("Max SOL/trade", 0.001, 10.0,
                                            tpl["config"]["max_sol_per_trade"], 0.01,
                                            format="%.3f")
            with cc2:
                paper    = st.toggle("Paper Mode", value=tpl["config"].get("paper_mode", True))
                auto_approve = st.toggle("Auto-approve trades", value=False,
                                          help="Skip approval queue — bot trades autonomously")

        # Create button
        bc1, bc2 = st.columns([1, 1])
        with bc1:
            if st.button("◆ Create Bot", type="primary", use_container_width=True):
                if not bot_name.strip():
                    st.error("Enter a bot name")
                elif not wallet_pub:
                    st.error("Generate a wallet first")
                elif not prompt.strip():
                    st.error("Enter a strategy prompt")
                else:
                    priv_enc = encrypt(st.session_state.get("new_bot_wallet_priv", ""))
                    config = {
                        "interval_seconds": interval,
                        "max_sol_per_trade": max_sol,
                        "paper_mode": paper,
                        "auto_approve": auto_approve
                    }
                    bot_id = bot_db.create_bot(
                        name=bot_name.strip(),
                        strategy=tpl["strategy"],
                        prompt=prompt.strip(),
                        wallet_pub=wallet_pub,
                        wallet_priv_enc=priv_enc,
                        config=config
                    )
                    st.success(f"Bot #{bot_id} created!")
                    st.session_state["show_create_bot"] = False
                    st.session_state.pop("new_bot_wallet_pub", None)
                    st.session_state.pop("new_bot_wallet_priv", None)
                    st.rerun()
        with bc2:
            if st.button("✕ Cancel", use_container_width=True):
                st.session_state["show_create_bot"] = False
                st.session_state.pop("new_bot_wallet_pub", None)
                st.session_state.pop("new_bot_wallet_priv", None)
                st.rerun()

        st.markdown("---")

    # ── Bot List ──────────────────────────────────────────────────
    bots = bot_db.list_bots()

    if not bots:
        st.markdown("""
        <div style='text-align:center;padding:64px;font-family:"Ubuntu Mono",monospace;
                    font-size:12px;color:#333;border:1px solid #1a1a1a;border-radius:4px;'>
        NO BOTS YET<br>
        <span style='font-size:10px;color:#2a2a2a;'>Click "Create New Bot" to get started</span>
        </div>""", unsafe_allow_html=True)
        return

    # Summary row
    running_count = sum(1 for b in bots if b["status"] == BotStatus.RUNNING)
    total_trades  = sum(b["total_trades"] for b in bots)

    st.markdown(f"""
    <div style='display:flex;gap:24px;padding:12px 16px;background:#141414;
                border:1px solid #222;border-radius:4px;margin-bottom:16px;
                font-family:"Ubuntu Mono",monospace;font-size:11px;'>
      <span style='color:#e95420;'>{len(bots)} BOTS</span>
      <span style='color:#333;'>|</span>
      <span style='color:#4caf50;'>{running_count} RUNNING</span>
      <span style='color:#333;'>|</span>
      <span style='color:#aaa;'>{total_trades} TOTAL TRADES</span>
    </div>
    """, unsafe_allow_html=True)

    # ── Each bot card ─────────────────────────────────────────────
    for bot in bots:
        config   = json.loads(bot["config"]) if isinstance(bot["config"], str) else bot["config"]
        is_live  = bot_runner.is_running(bot["bot_id"] if "bot_id" in bot else bot["id"])
        bot_id   = bot["id"]
        status   = bot["status"]

        status_color = {
            "running": "#4caf50", "stopped": "#555",
            "paused": "#f59e0b", "error": "#f44336"
        }.get(status, "#555")

        paper_badge = '<span class="flag flag-paper">PAPER</span>' if config.get("paper_mode") else '<span class="flag flag-warn">LIVE</span>'

        with st.expander(
            f"{'▶' if status == 'running' else '■'}  {bot['name']}  ·  #{bot_id}  ·  {status.upper()}",
            expanded=(status == "running")
        ):
            # ── Control row ───────────────────────────────────────
            ctrl1, ctrl2, ctrl3, ctrl4, ctrl5 = st.columns([1,1,1,1,2])

            with ctrl1:
                if status != BotStatus.RUNNING:
                    if st.button("▶ Start", key=f"start_{bot_id}", type="primary", use_container_width=True):
                        bot_runner.start(bot_id)
                        st.rerun()
                else:
                    if st.button("■ Stop", key=f"stop_{bot_id}", use_container_width=True):
                        bot_runner.stop(bot_id)
                        st.rerun()

            with ctrl2:
                if status == BotStatus.RUNNING:
                    if st.button("⏸ Pause", key=f"pause_{bot_id}", use_container_width=True):
                        bot_runner.pause(bot_id)
                        st.rerun()
                elif status == BotStatus.PAUSED:
                    if st.button("▶ Resume", key=f"resume_{bot_id}", use_container_width=True):
                        bot_runner.resume(bot_id)
                        st.rerun()

            with ctrl3:
                if st.button("✎ Edit", key=f"edit_{bot_id}", use_container_width=True):
                    st.session_state[f"editing_{bot_id}"] = True

            with ctrl4:
                if st.button("🗑 Delete", key=f"del_{bot_id}", use_container_width=True):
                    bot_runner.stop(bot_id)
                    bot_db.delete_bot(bot_id)
                    st.rerun()

            with ctrl5:
                st.markdown(f"""
                <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;color:#444;padding:6px 0;'>
                <span style='color:{status_color};'>● {status.upper()}</span>
                &nbsp;·&nbsp; {paper_badge}
                &nbsp;·&nbsp; {bot['total_trades']} trades
                &nbsp;·&nbsp; every {config.get('interval_seconds',60)}s
                </div>""", unsafe_allow_html=True)

            # ── Edit panel ────────────────────────────────────────
            if st.session_state.get(f"editing_{bot_id}"):
                st.markdown("---")
                st.markdown('<div class="reasoning-label">edit bot</div>', unsafe_allow_html=True)

                ec1, ec2 = st.columns(2)
                with ec1:
                    new_name   = st.text_input("Name", value=bot["name"], key=f"en_{bot_id}")
                    new_prompt = st.text_area("Strategy Prompt", value=bot["prompt"],
                                              height=150, key=f"ep_{bot_id}")
                with ec2:
                    new_interval = st.number_input("Interval (s)", 10, 3600,
                                                    config.get("interval_seconds", 60),
                                                    key=f"ei_{bot_id}")
                    new_max_sol  = st.number_input("Max SOL/trade", 0.001, 10.0,
                                                    float(config.get("max_sol_per_trade", 0.1)),
                                                    format="%.3f", key=f"em_{bot_id}")
                    new_paper    = st.toggle("Paper Mode", config.get("paper_mode", True),
                                              key=f"epm_{bot_id}")
                    new_auto     = st.toggle("Auto-approve", config.get("auto_approve", False),
                                              key=f"ea_{bot_id}")

                save_col, cancel_col = st.columns(2)
                with save_col:
                    if st.button("💾 Save Changes", key=f"save_{bot_id}", type="primary", use_container_width=True):
                        new_config = {
                            "interval_seconds": new_interval,
                            "max_sol_per_trade": new_max_sol,
                            "paper_mode": new_paper,
                            "auto_approve": new_auto
                        }
                        bot_db.update_bot(bot_id,
                            name=new_name,
                            prompt=new_prompt,
                            config=json.dumps(new_config)
                        )
                        st.session_state[f"editing_{bot_id}"] = False
                        st.success("Saved!")
                        st.rerun()
                with cancel_col:
                    if st.button("✕ Cancel", key=f"cancel_{bot_id}", use_container_width=True):
                        st.session_state[f"editing_{bot_id}"] = False
                        st.rerun()

                st.markdown("---")

            # ── Info grid ─────────────────────────────────────────
            info1, info2, info3 = st.columns(3)

            with info1:
                st.markdown('<div class="reasoning-label">wallet</div>', unsafe_allow_html=True)
                st.markdown(f"""
                <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;
                            color:#aaa;padding:8px;background:#0a0a0a;
                            border:1px solid #1e1e1e;border-radius:3px;word-break:break-all;'>
                {bot['wallet_pub']}<br>
                <a href="https://solscan.io/account/{bot['wallet_pub']}"
                   target="_blank"
                   style='color:#2196f3;font-size:9px;text-decoration:none;'>
                   ↗ View on Solscan
                </a>
                </div>""", unsafe_allow_html=True)

            with info2:
                st.markdown('<div class="reasoning-label">strategy</div>', unsafe_allow_html=True)
                st.markdown(f"""
                <div class="reasoning-box" style='max-height:80px;overflow:hidden;font-size:10px;'>
                {bot['prompt'][:200]}{'...' if len(bot.get('prompt','')) > 200 else ''}
                </div>""", unsafe_allow_html=True)

            with info3:
                st.markdown('<div class="reasoning-label">stats</div>', unsafe_allow_html=True)
                last_run = time_ago(bot["last_run"]) if bot.get("last_run") else "never"
                st.markdown(f"""
                <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;
                            color:#444;line-height:2;'>
                TRADES &nbsp;{bot['total_trades']}<br>
                LAST &nbsp;&nbsp;{last_run}<br>
                MAX &nbsp;&nbsp;&nbsp;{config.get('max_sol_per_trade', 0)} SOL/trade<br>
                CREATED {bot['created_at'][:10]}
                </div>""", unsafe_allow_html=True)

            if bot.get("error_msg"):
                st.markdown(f"""
                <div style='font-family:"Ubuntu Mono",monospace;font-size:10px;
                            color:#f44336;padding:8px;background:#0f0000;
                            border:1px solid #3a0000;border-radius:3px;margin-top:8px;'>
                ⚠ ERROR: {bot['error_msg']}
                </div>""", unsafe_allow_html=True)

            # ── Tabs: Logs / Trades ───────────────────────────────
            log_tab, trade_tab = st.tabs(["LOGS", "TRADES"])

            with log_tab:
                logs = bot_db.get_logs(bot_id, limit=30)
                if not logs:
                    st.markdown('<div style="font-family:Ubuntu Mono,monospace;font-size:11px;color:#333;padding:12px;">No logs yet</div>', unsafe_allow_html=True)
                else:
                    log_lines = []
                    for l in reversed(logs):
                        level_color = {
                            "INFO": "#4caf50", "WARN": "#e95420",
                            "ERROR": "#f44336", "DEBUG": "#444"
                        }.get(l["level"], "#aaa")
                        ts = l["timestamp"][11:19]
                        log_lines.append(
                            f'<span style="color:#333;">{ts}</span> '
                            f'<span style="color:{level_color};">[{l["level"]}]</span> '
                            f'<span style="color:#aaa;">{l["message"]}</span>'
                        )
                    st.markdown(f"""
                    <div style='font-family:"Ubuntu Mono",monospace;font-size:11px;
                                background:#0a0a0a;border:1px solid #1e1e1e;
                                border-radius:3px;padding:12px;
                                max-height:200px;overflow-y:auto;line-height:1.8;'>
                    {"<br>".join(log_lines)}
                    </div>""", unsafe_allow_html=True)

            with trade_tab:
                trades = bot_db.get_trades(bot_id, limit=20)
                if not trades:
                    st.markdown('<div style="font-family:Ubuntu Mono,monospace;font-size:11px;color:#333;padding:12px;">No trades yet</div>', unsafe_allow_html=True)
                else:
                    rows = []
                    for t in trades:
                        rows.append({
                            "TIME":   t["timestamp"][11:19],
                            "ACTION": t["action"].upper(),
                            "MINT":   t["mint"][:12] + "...",
                            "SOL":    t["amount_sol"],
                            "RESULT": t["result"][:20],
                            "TX":     (t.get("tx_sig") or "—")[:16],
                        })
                    df = pd.DataFrame(rows)
                    def color_action(val):
                        return f"color:{'#4caf50' if val=='BUY' else '#f44336'};font-family:Ubuntu Mono,monospace;font-size:11px;"
                    st.dataframe(
                        df.style.applymap(color_action, subset=["ACTION"]),
                        use_container_width=True, hide_index=True, height=200
                    )
