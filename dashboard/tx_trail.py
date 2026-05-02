import streamlit as st
import json
import time
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.proposal_db import proposal_db
try:
    from src.bot_engine import bot_db
    HAS_BOTS = True
except:
    HAS_BOTS = False


def time_ago(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        s = (datetime.utcnow() - dt).total_seconds()
        if s < 60: return f"{int(s)}s"
        if s < 3600: return f"{int(s//60)}m"
        if s < 86400: return f"{int(s//3600)}h"
        return f"{int(s//86400)}d"
    except:
        return "?"


def get_all_transactions():
    txs = []
    proposals = proposal_db.list_proposals(limit=100)
    for p in proposals:
        params = json.loads(p["params"]) if isinstance(p["params"], str) else p["params"]
        tool = p["tool_name"]
        action = "BUY" if "buy" in tool else "SELL" if "sell" in tool else "SWAP" if "swap" in tool else "CREATE" if "create" in tool else "PAY"
        sol = float(params.get("sol_amount") or params.get("amount_sol") or 0)
        mint = params.get("mint_address") or params.get("input_mint") or params.get("output_mint") or "unknown"
        txs.append({
            "id": p["id"], "time": p["created_at"], "action": action,
            "tool": tool, "agent": p["agent_id"], "mint": mint[:8] if mint else "???",
            "sol": sol, "status": p["status"], "tx_sig": p.get("tx_signature") or "",
            "paper": bool(p.get("paper_mode", 1)), "source": "agent"
        })
    if HAS_BOTS:
        try:
            bots = bot_db.list_bots()
            for bot in bots:
                trades = bot_db.get_trades(bot["id"], limit=20)
                for t in trades:
                    txs.append({
                        "id": f"BOT{t['id']}", "time": t["timestamp"],
                        "action": t["action"].upper(), "tool": f"bot_{t['action']}",
                        "agent": f"bot_{bot['id']}", "mint": t["mint"][:8] if t.get("mint") else "???",
                        "sol": float(t.get("amount_sol") or 0),
                        "status": "executed" if t.get("tx_sig") else "pending",
                        "tx_sig": t.get("tx_sig") or "", "paper": True, "source": "bot"
                    })
        except:
            pass
    txs.sort(key=lambda x: x["time"], reverse=True)
    return txs[:50]


def render_tx_trail():
    st.markdown('<div class="section-header">// transaction trail</div>', unsafe_allow_html=True)

    txs = get_all_transactions()

    st.markdown('<div class="section-header">// live network</div>', unsafe_allow_html=True)

    nodes = [
        {"id": "WALLET",  "label": "WALLET",   "type": "wallet", "x": 400, "y": 250},
        {"id": "PUMPFUN", "label": "PUMP.FUN", "type": "dex",    "x": 150, "y": 120},
        {"id": "JUPITER", "label": "JUPITER",  "type": "dex",    "x": 650, "y": 120},
        {"id": "RAYDIUM", "label": "RAYDIUM",  "type": "dex",    "x": 650, "y": 380},
        {"id": "x402",    "label": "x402",     "type": "pay",    "x": 150, "y": 380},
    ]

    if HAS_BOTS:
        try:
            bots = bot_db.list_bots()
            bot_positions = [(400,450),(250,480),(550,480),(200,380),(600,280),(300,50)]
            for i, bot in enumerate(bots[:6]):
                bx, by = bot_positions[i % len(bot_positions)]
                nodes.append({"id": f"BOT_{bot['id']}", "label": bot["name"][:10], "type": "bot", "x": bx+(i*15), "y": by+(i*10)})
        except:
            pass

    seen_mints = set()
    token_positions = [(280,180),(520,180),(280,320),(520,320),(400,100)]
    ti = 0
    for tx in txs[:10]:
        mint = tx["mint"]
        if mint and mint != "unknown" and mint not in seen_mints and ti < 5:
            seen_mints.add(mint)
            bx, by = token_positions[ti]
            nodes.append({"id": mint, "label": mint[:6], "type": "token", "x": bx, "y": by})
            ti += 1

    edges = []
    for tx in txs[:15]:
        action = tx["action"]
        agent  = tx["agent"]
        mint   = tx["mint"]
        sol    = tx["sol"]
        status = tx["status"]
        src = f"BOT_{agent.replace('bot_','')}" if "bot_" in agent else "WALLET"
        if src not in [n["id"] for n in nodes]:
            src = "WALLET"
        if action in ("BUY","CREATE"):
            edges.append({"from": src, "to": "PUMPFUN", "label": f"{sol:.3f} SOL", "status": status, "action": action})
            if mint in seen_mints:
                edges.append({"from": "PUMPFUN", "to": mint, "label": mint[:6], "status": status, "action": action})
        elif action == "SELL":
            if mint in seen_mints:
                edges.append({"from": mint, "to": "PUMPFUN", "label": mint[:6], "status": status, "action": action})
            edges.append({"from": "PUMPFUN", "to": src, "label": f"{sol:.3f} SOL", "status": status, "action": action})
        elif action == "SWAP":
            edges.append({"from": src, "to": "JUPITER", "label": f"{sol:.3f} SOL", "status": status, "action": action})
        elif action == "PAY":
            edges.append({"from": src, "to": "x402", "label": "USDC", "status": status, "action": action})

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    txs_json   = json.dumps(txs[:20])

    html = f"""<!DOCTYPE html><html><head><style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#300a24;font-family:'Ubuntu Mono',monospace;overflow:hidden;}}
canvas{{display:block;}}
#info{{position:absolute;bottom:12px;left:12px;font-size:10px;color:#a07090;letter-spacing:0.1em;}}
#legend{{position:absolute;top:12px;right:12px;font-size:9px;color:#a07090;line-height:2;}}
.leg{{display:flex;align-items:center;gap:6px;}}
.dot{{width:8px;height:8px;border-radius:50%;}}
</style></head><body>
<canvas id="c"></canvas>
<div id="info">LIVE TRANSACTION NETWORK · <span id="tx_count">0</span> TXS</div>
<div id="legend">
<div class="leg"><span class="dot" style="background:#e95420"></span>WALLET</div>
<div class="leg"><span class="dot" style="background:#2196f3"></span>DEX</div>
<div class="leg"><span class="dot" style="background:#4caf50"></span>BOT</div>
<div class="leg"><span class="dot" style="background:#9c27b0"></span>TOKEN</div>
<div class="leg"><span class="dot" style="background:#ff9800"></span>x402</div>
</div>
<script>
const NODES={nodes_json};
const EDGES={edges_json};
const TXS={txs_json};
const canvas=document.getElementById('c');
const ctx=canvas.getContext('2d');
canvas.width=window.innerWidth||800;
canvas.height=window.innerHeight||480;
const scaleX=canvas.width/800;
const scaleY=canvas.height/500;
NODES.forEach(n=>{{n.x*=scaleX;n.y*=scaleY;}});
const NODE_COLORS={{wallet:'#e95420',dex:'#2196f3',bot:'#4caf50',token:'#9c27b0',pay:'#ff9800'}};
let particles=[],pulses=[],frame=0;
function spawnParticles(){{
  EDGES.forEach(e=>{{
    if(Math.random()<0.08){{
      const src=NODES.find(n=>n.id===e.from);
      const dst=NODES.find(n=>n.id===e.to);
      if(!src||!dst)return;
      const color=e.action==='BUY'?'#4caf50':e.action==='SELL'?'#f44336':e.action==='SWAP'?'#2196f3':e.action==='PAY'?'#ff9800':'#a07090';
      particles.push({{sx:src.x,sy:src.y,ex:dst.x,ey:dst.y,t:0,speed:0.008+Math.random()*0.012,color,size:3+Math.random()*2,label:e.label}});
    }}
  }});
}}
function spawnPulse(nodeId){{
  const n=NODES.find(x=>x.id===nodeId);
  if(n)pulses.push({{x:n.x,y:n.y,r:0,alpha:1}});
}}
NODES.forEach(n=>spawnPulse(n.id));
document.getElementById('tx_count').textContent=TXS.length;
function draw(){{
  frame++;
  ctx.fillStyle='rgba(48,10,36,0.85)';
  ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle='rgba(74,21,64,0.3)';
  ctx.lineWidth=0.5;
  for(let x=0;x<canvas.width;x+=40){{ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,canvas.height);ctx.stroke();}}
  for(let y=0;y<canvas.height;y+=40){{ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();}}
  EDGES.forEach(e=>{{
    const src=NODES.find(n=>n.id===e.from);
    const dst=NODES.find(n=>n.id===e.to);
    if(!src||!dst)return;
    const color=e.status==='executed'?'rgba(76,175,80,0.15)':e.status==='pending'?'rgba(233,84,32,0.15)':'rgba(160,112,144,0.1)';
    ctx.beginPath();ctx.moveTo(src.x,src.y);
    const mx=(src.x+dst.x)/2,my=(src.y+dst.y)/2-30;
    ctx.quadraticCurveTo(mx,my,dst.x,dst.y);
    ctx.strokeStyle=color;ctx.lineWidth=1;ctx.setLineDash([4,4]);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle='rgba(160,112,144,0.5)';ctx.font='8px Ubuntu Mono';ctx.fillText(e.label,mx-10,my-4);
  }});
  spawnParticles();
  particles=particles.filter(p=>p.t<1);
  particles.forEach(p=>{{
    p.t+=p.speed;
    const x=p.sx+(p.ex-p.sx)*p.t,y=p.sy+(p.ey-p.sy)*p.t;
    const grd=ctx.createRadialGradient(x,y,0,x,y,p.size*3);
    grd.addColorStop(0,p.color);grd.addColorStop(1,'transparent');
    ctx.beginPath();ctx.arc(x,y,p.size*3,0,Math.PI*2);ctx.fillStyle=grd;ctx.fill();
    ctx.beginPath();ctx.arc(x,y,p.size,0,Math.PI*2);ctx.fillStyle=p.color;ctx.fill();
  }});
  pulses=pulses.filter(p=>p.alpha>0.01);
  pulses.forEach(p=>{{
    p.r+=0.8;p.alpha*=0.96;
    ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
    ctx.strokeStyle=`rgba(233,84,32,${{p.alpha}})`;ctx.lineWidth=1;ctx.stroke();
  }});
  NODES.forEach(n=>{{
    const color=NODE_COLORS[n.type]||'#a07090';
    const r=n.type==='wallet'?18:n.type==='dex'?14:10;
    const grd=ctx.createRadialGradient(n.x,n.y,0,n.x,n.y,r*3);
    grd.addColorStop(0,color+'44');grd.addColorStop(1,'transparent');
    ctx.beginPath();ctx.arc(n.x,n.y,r*3,0,Math.PI*2);ctx.fillStyle=grd;ctx.fill();
    ctx.beginPath();ctx.arc(n.x,n.y,r+2,0,Math.PI*2);ctx.strokeStyle=color+'66';ctx.lineWidth=1;ctx.stroke();
    ctx.beginPath();ctx.arc(n.x,n.y,r,0,Math.PI*2);ctx.fillStyle='#200618';ctx.fill();
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
    if(n.type==='wallet'&&frame%60===0)spawnPulse(n.id);
    ctx.fillStyle='#ffffff';ctx.font=`bold ${{r>12?10:8}}px Ubuntu Mono`;ctx.textAlign='center';
    ctx.fillText(n.label,n.x,n.y+r+14);ctx.textAlign='left';
  }});
  requestAnimationFrame(draw);
}}
draw();
setInterval(()=>{{
  const active=NODES.filter(n=>n.type!=='token');
  if(active.length)spawnPulse(active[Math.floor(Math.random()*active.length)].id);
}},800);
</script></body></html>"""

    st.components.v1.html(html, height=480, scrolling=False)

    st.markdown('<div class="section-header">// transaction feed</div>', unsafe_allow_html=True)

    if not txs:
        st.markdown('<div style="text-align:center;padding:32px;font-family:Ubuntu Mono,monospace;font-size:12px;color:#a07090;border:1px solid #4a1540;border-radius:2px;">NO TRANSACTIONS YET</div>', unsafe_allow_html=True)
        return

    feed_html = """<style>
@import url('https://fonts.googleapis.com/css2?family=Ubuntu+Mono:wght@400;700&display=swap');
.feed{font-family:'Ubuntu Mono',monospace;background:#200618;border:1px solid #4a1540;border-radius:2px;padding:8px;max-height:420px;overflow-y:auto;}
.tx-row{display:flex;align-items:center;gap:12px;padding:8px 10px;border-bottom:1px solid #3a1530;animation:fadeIn 0.3s ease;}
.tx-row:last-child{border-bottom:none;}
@keyframes fadeIn{from{opacity:0;transform:translateX(-8px);}to{opacity:1;transform:translateX(0);}}
.tx-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;box-shadow:0 0 6px currentColor;}
.tx-dot.buy{background:#4caf50;color:#4caf50;}.tx-dot.sell{background:#f44336;color:#f44336;}
.tx-dot.swap{background:#2196f3;color:#2196f3;}.tx-dot.create{background:#9c27b0;color:#9c27b0;}
.tx-dot.pay{background:#ff9800;color:#ff9800;}.tx-dot.propose{background:#a07090;color:#a07090;}
.tx-time{font-size:10px;color:#a07090;width:32px;flex-shrink:0;}
.tx-action{font-size:11px;font-weight:700;width:56px;flex-shrink:0;}
.tx-action.buy{color:#4caf50;}.tx-action.sell{color:#f44336;}.tx-action.swap{color:#2196f3;}
.tx-action.create{color:#9c27b0;}.tx-action.pay{color:#ff9800;}.tx-action.propose{color:#a07090;}
.tx-agent{font-size:10px;color:#a07090;width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0;}
.tx-mint{font-size:10px;color:#d0b0c0;width:80px;flex-shrink:0;}
.tx-sol{font-size:11px;color:#ffffff;width:80px;flex-shrink:0;text-align:right;}
.tx-status{font-size:9px;padding:2px 6px;border-radius:2px;flex-shrink:0;}
.tx-status.executed{background:#0f3a0f;color:#4caf50;}.tx-status.pending{background:#3a1a00;color:#e95420;}
.tx-status.rejected{background:#3a0000;color:#f44336;}.tx-status.approved{background:#0f3a0f;color:#4caf50;}
.tx-status.paper{background:#1a1a00;color:#888;}
.tx-sig{font-size:9px;color:#4a1540;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tx-sig a{color:#4a2a50;text-decoration:none;}.tx-sig a:hover{color:#e95420;}
.pulse{display:inline-block;width:6px;height:6px;border-radius:50%;background:#e95420;animation:pulse 1.5s infinite;margin-right:4px;}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.3;transform:scale(0.6);}}
</style><div class="feed">"""

    for tx in txs:
        action_class = tx["action"].lower()
        status_class = "paper" if tx["paper"] else tx["status"]
        status_label = "PAPER" if tx["paper"] else tx["status"].upper()
        sol_str = f"{tx['sol']:.3f} SOL" if tx["sol"] > 0 else "---"
        ago = time_ago(tx["time"])
        is_pending = tx["status"] == "pending"
        pulse_html = '<span class="pulse"></span>' if is_pending else ""
        sig_html = ""
        if tx.get("tx_sig") and not tx["paper"]:
            sig_html = f'<div class="tx-sig"><a href="https://solscan.io/tx/{tx["tx_sig"]}" target="_blank">↗ {tx["tx_sig"][:16]}...</a></div>'
        elif tx.get("tx_sig"):
            sig_html = f'<div class="tx-sig">{tx["tx_sig"][:20]}...</div>'
        feed_html += f'<div class="tx-row"><div class="tx-dot {action_class}"></div><div class="tx-time">{ago}</div><div class="tx-action {action_class}">{pulse_html}{tx["action"]}</div><div class="tx-agent">{tx["agent"][:18]}</div><div class="tx-mint">{tx["mint"]}</div><div class="tx-sol">{sol_str}</div><div class="tx-status {status_class}">{status_label}</div>{sig_html}</div>'

    feed_html += "</div>"
    st.markdown(feed_html, unsafe_allow_html=True)

    buys  = sum(1 for t in txs if t["action"]=="BUY")
    sells = sum(1 for t in txs if t["action"]=="SELL")
    swaps = sum(1 for t in txs if t["action"]=="SWAP")
    vol   = sum(t["sol"] for t in txs)
    papers= sum(1 for t in txs if t["paper"])

    st.markdown(f"""
    <div style='display:flex;gap:24px;padding:10px 16px;background:#200618;border:1px solid #4a1540;border-radius:2px;margin-top:8px;font-family:"Ubuntu Mono",monospace;font-size:11px;'>
    <span style='color:#4caf50;'>BUY {buys}</span>
    <span style='color:#f44336;'>SELL {sells}</span>
    <span style='color:#2196f3;'>SWAP {swaps}</span>
    <span style='color:#a07090;'>|</span>
    <span style='color:#ffffff;'>VOL {vol:.3f} SOL</span>
    <span style='color:#a07090;'>|</span>
    <span style='color:#666;'>PAPER {papers}</span>
    <span style='color:#a07090;'>|</span>
    <span style='color:#a07090;'>SHOWING {len(txs)} TXS</span>
    </div>""", unsafe_allow_html=True)
