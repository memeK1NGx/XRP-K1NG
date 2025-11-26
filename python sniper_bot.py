import os, json, time, asyncio, websockets, requests, traceback, threading
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import numpy as np
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AMMInfo
from xrpl.models.transactions import AMMDeposit
from xrpl.utils import xrp_to_drops
import telebot
from dotenv import load_dotenv
from bot_utils.helpers import write_log_rotating

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID          = os.getenv("TELEGRAM_CHAT_ID")
WALLET_SEED      = os.getenv("WALLET_SEED")
BUY_XRP          = float(os.getenv("BUY_XRP", "2.5"))
SELL_MULTIPLIER  = float(os.getenv("SELL_MULTIPLIER", "3.0"))
MIN_SCORE        = float(os.getenv("MIN_SCORE", "75"))
AUTO_TRADE       = os.getenv("AUTO_TRADE", "true").lower() == "true"
COOLDOWN         = int(os.getenv("COOLDOWN_SECONDS", "900"))
BITHOMP_KEY      = os.getenv("BITHOMP_API_KEY", "")

WALLET_SCORES = {
    k: int(v) for k, v in [
        line.split("=") for line in os.getenv("WATCHED_WALLETS", "").split(",")
        if "=" in line
    ]
}

RPC_URLS = [
    "https://xrplcluster.com",
    "https://s1.ripple.com:51234",
    "https://s2.ripple.com:51234"
]

WS_URLS = [
    "wss://xrplcluster.com",
    "wss://s1.ripple.com",
    "wss://s2.ripple.com"
]

bot = telebot.TeleBot(TELEGRAM_TOKEN)
clients = [JsonRpcClient(url) for url in RPC_URLS]
client_idx = 0
wallet = Wallet.from_seed(WALLET_SEED)

seen_issuers = set()
positions = {}
last_snipe_time = defaultdict(int)

def get_client():
    global client_idx
    c = clients[client_idx]
    client_idx = (client_idx + 1) % len(clients)
    return c

def alert(text):
    try:
        bot.send_message(CHAT_ID, text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception:
        pass

def get_dynamic_slippage(liquidity):
    if liquidity > 5000: return 1.0
    if liquidity > 1000: return 2.0
    return 3.5

def get_amm_data(issuer):
    try:
        currency = issuer.split("+")[0] if "+" in issuer else issuer
        req = AMMInfo(asset="XRP", asset2={"currency": currency, "issuer": issuer})
        resp = get_client().request(req)
        amm = resp.result.get("amm")
        if not amm: return None, None
        xrp = float(amm["amount"])
        token = float(amm["amount2"]["value"]) if isinstance(amm["amount2"], dict) else float(amm["amount2"])
        liq = xrp + (token * (xrp / token))
        return token / xrp, liq
    except:
        return None, None

def get_volume(issuer):
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/search?q={issuer}",
            timeout=4,
            headers={"User-Agent": "XRPLSniper/31"}
        )
        for p in r.json().get("pairs", []):
            if p.get("chainId") == "xrpl":
                return float(p.get("volume", {}).get("h24", 0))
    except:
        pass
    return 0.0

def quantum_score(volume, liquidity, wallet_bonus):
    if volume < 1000 or liquidity < 200: return 0
    score = np.log(volume / 1000 + 1) * 12
    score += np.log(liquidity / 1000 + 1) * 8
    score += wallet_bonus * 3
    return min(120, score)

async def process_pool(issuer, sender="unknown"):
    if issuer in seen_issuers:
        return

    if time.time() - last_snipe_time[issuer] < COOLDOWN:
        return

    token_per_xrp, liquidity = get_amm_data(issuer)
    if not token_per_xrp:
        return

    volume = get_volume(issuer)
    bonus = WALLET_SCORES.get(sender, 0)
    score = quantum_score(volume, liquidity, bonus)

    if score >= MIN_SCORE:
        seen_issuers.add(issuer)
        last_snipe_time[issuer] = time.time()
        alert(f"NEW GEM\n`{issuer}`\nScore: {score:.1f}\nAuto-buying…")
        snipe(issuer, token_per_xrp, liquidity)

def snipe(issuer, token_per_xrp, liquidity):
    if not AUTO_TRADE: return
    try:
        slip = get_dynamic_slippage(liquidity)
        drops = xrp_to_drops(BUY_XRP * (1 + slip/100))
        tx = AMMDeposit(
            account=wallet.classic_address,
            amount=drops,
            asset="XRP",
            asset2={"currency": issuer.split("+")[0], "issuer": issuer},
            flags=2147483648,
            fee="100"
        )
        signed = wallet.sign(tx)
        resp = get_client().submit_and_wait(signed)
        if resp.is_successful():
            alert(f"BURNA SNIPED `{issuer}`")
    except Exception as e:
        alert(f"Buy error: {e}")

async def ws_sniper():
    idx = 0
    while True:
        try:
            async with websockets.connect(
                WS_URLS[idx % len(WS_URLS)], ping_interval=12
            ) as ws:
                await ws.send(json.dumps({"command":"subscribe","streams":["transactions_proposed"]}))
                idx = 0
                async for msg in ws:
                    data = json.loads(msg)
                    if data.get("type") != "transaction": continue
                    tx = data["transaction"]
                    if tx.get("TransactionType") == "AMMCreate":
                        amt = tx.get("Amount") or tx.get("Amount2")
                        if isinstance(amt, dict):
                            issuer = amt.get("issuer")
                            asyncio.create_task(process_pool(issuer, tx.get("Account")))
        except:
            idx += 1
            await asyncio.sleep(2)

def run_forever():
    while True:
        try:
            asyncio.run(ws_sniper())
        except:
            alert("CRASH — restarting…")
            time.sleep(5)

alert("✅ BURNA BOT DEPLOYED SUCCESSFULLY")

if __name__ == "__main__":
    run_forever()
