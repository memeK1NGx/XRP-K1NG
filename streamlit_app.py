import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="XRPL Quantum Sniper", layout="wide")
st.title("XRPL Quantum Sniper — Burna Dashboard")

def load_log(file):
    p = Path(file)
    return json.loads(p.read_text()) if p.exists() else []

scoring = load_log("scoring_log.json")
trades = load_log("sniper_log.json")
outcomes = load_log("trade_outcomes.json")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Active Positions", len([
        t for t in trades
        if t['side']=='BUY' and t['issuer'] not in {
            x['issuer'] for x in trades if x['side']=='SELL'
        }
    ]))

with col2:
    st.metric("Total Snipes", len(scoring))

with col3:
    wins = len([o for o in outcomes if o["result"] == "WIN"])
    st.metric("Wins", wins)

st.subheader("Quantum Scoreboard (Top 20)")
top = sorted(
    [s for s in scoring if s["result"] == "BUY"],
    key=lambda x: x["score"],
    reverse=True
)[:20]
st.dataframe(top, use_container_width=True)

st.subheader("Recent Trades")
recent = sorted(trades, key=lambda x: x["timestamp"], reverse=True)[:30]
st.dataframe(recent, use_container_width=True)
