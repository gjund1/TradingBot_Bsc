#!/usr/bin/env python3

import os, time, json, random, requests
from decimal import Decimal, getcontext
from datetime import datetime
from cryptography.fernet import Fernet
from web3 import Web3
from eth_account import Account
from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware
from key.wallets import KEY_PATHS, ENC_PATHS, nameWallets
from key.email import send_mail

# =========================
# 🧩 Configuration initiale
# =========================

DRY_RUN = True                 # True MODE ESSAI, False pour vrai trading
DRY_RUN_SLEEP = 10              # 1 min (1 * 60)  /  10s (10)
WALLETS_RANDOM = False           # Wallets aleatoire
TRADING = True                  # Buy or Sell (On/Off)
APPROVE = False                 # Approve Wallets Infinity
H1 = "m5"                       # "h1" ou "m5"

BUY_PORTION = Decimal("0.233")                      # ~1/5 BNB wallet
SELL_PORTION = Decimal("0.733")                     # ~3/4 MRS wallet
MIN_BNB_USD_THRESHOLD = Decimal("5.0")
MIN_MRS_USD_THRESHOLD = Decimal("5.0")
# MAX_MRS_USD_SELL = Decimal("150.0")                 # ~$150                                                                     # A FAIRE !
MAX_GAS_USD = Decimal("0.01")
GWEI = 0.05                                         # Frais de Gas
GAS_LIMIT = 170000                                  # 170.000 / buy 140.000 / Sell 170.000
GAS_LIMIT_APPROVE = 100000
SLIPPAGE = 0.01                                     # 1% buy/sell slippage

START_HOUR, END_HOUR = 6, 21                        # 6h - 22h (+1h UTC)
RANDOM_MIN = 60*(35)  if H1=="h1" else 60*5         # tx (h1) apres 35 min a 1h35 / 60 * (35) / 60 * (60 + 45)
RANDOM_MAX = 60*(60+45) if H1=="h1" else 60*9       # tx (m5) apres 5-9 min

RETRY_WAIT_SECONDS = 15                             # 15s
getcontext().prec = 28                              # Decimal : 28

# ==============================
# 📜 Setup Web3 / contrats / ABI
# ==============================

BSC_RPC = os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/")
w3 = Web3(Web3.HTTPProvider(BSC_RPC))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

CONTRACT_MRS = Web3.to_checksum_address("0x14e3598571F4683CEA1Ff2a917F4a3354Cd5842b")
PANCAKE_ROUTER = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
WBNB = Web3.to_checksum_address("0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")

PANCAKE_ROUTER_ABI = json.loads("""[
  {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"payable","type":"function"},
  {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForETHSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"nonpayable","type":"function"},
  {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"","type":"uint256[]"}],"stateMutability":"view","type":"function"}
]""")

ERC20_ABI = json.loads("""[
  {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
  {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},
  {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]""")

router = w3.eth.contract(address = PANCAKE_ROUTER, abi = PANCAKE_ROUTER_ABI)
token = w3.eth.contract(address = CONTRACT_MRS, abi = ERC20_ABI)

# ==========================
# ⚙️  UTILITAIRES
# ==========================

# Affiche dans le terminal avec date et heure.
def log(message: str):
    now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{now} {message}")

def ping():
    while True:
        try:
            payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
            r = requests.post("https://bsc-dataseed.binance.org/", json=payload, timeout=3)
            r.raise_for_status()  # lève une erreur si le HTTP status n'est pas 200
            if "result" in r.json():
                return True
        except Exception as e:
            log(f"⚠️ Ping error: {e}")
        
        log(f"🌐 Ping failed, retry in {RETRY_WAIT_SECONDS} min.")
        if False:
            mail(f"🌐 Ping failed, retry in {RETRY_WAIT_SECONDS} min.")
        time.sleep(RETRY_WAIT_SECONDS * 60)

def in_active_hours():
    h = datetime.now().hour
    return (START_HOUR <= h < END_HOUR) or (2 <= h < 3)

# Message de l'email
def mail(resultats):
        corps = ""
        subject = f"MRS Trading Bot (H1) - {resultats}"
        send_mail(corps, subject)

# ==========================
# 👛  WALLET
# ==========================

def load_private_key(key_path, enc_path):
    with open(key_path,"rb") as f:
        fernet_key = f.read().strip()
    cipher = Fernet(fernet_key)
    with open(enc_path,"rb") as f:
        encrypted = f.read()
    return cipher.decrypt(encrypted).decode().strip()

def get_wallet_address(private_key):
    return Web3.to_checksum_address(Account.from_key(private_key).address)

def get_wallet_name(addr):
    suffix = addr[-5:].upper()
    for name, tag in nameWallets.items():
        if tag.upper() == suffix:
            return name
    return f"Wallet-{suffix}"

def get_balances(wallet):
    bnb = from_wei(w3.eth.get_balance(wallet))
    mrs_wei = token.functions.balanceOf(wallet).call()
    decimals = token.functions.decimals().call()
    mrs_decimal = from_wei(mrs_wei, decimals)
    return bnb, mrs_decimal, mrs_wei

# ====================================
# 🎯 TX helpers (approve / buy / sell)
# ====================================

def to_wei(amount, decimals = 18):
    return int((Decimal(amount)*(10**decimals)).to_integral_value())

def from_wei(amount, decimals = 18):
    return Decimal(amount) / (10**decimals)

def adjust_gas(current_gwei):
    VARIATION_GAS_THRESHOLD = 0.4                       # 40%
    MAX_JUMP = 10.0                                     # +1000%
    try:
        new_gwei = float(w3.eth.gas_price) / 1e9
        var_gwei = abs(new_gwei - current_gwei) / current_gwei
        if new_gwei != current_gwei:
            mail(f"✨ Variation du Gwei {new_gwei:.3f} ({var_gwei * 100:.0f}%)")
        # 🚫 Si variation > +1000% → on ignore
        if var_gwei > MAX_JUMP:                                                                                             # Atention A/b, b!=0 
            log(f"⚠️ Variation Gas trop élevée {new_gwei:.3f}, Gwei NON modifié !")
            return current_gwei
        if var_gwei > VARIATION_GAS_THRESHOLD:
            log(f"🔄 Gwei ajusté : {current_gwei:.3f} Gwei -> {new_gwei:.3f} Gwei")
            return new_gwei
        # log(f"✅ Gwei stable: {current_gwei:.3f} Gwei")
        # mail(f"✅ Gwei stable: {current_gwei:.3f} Gwei")
        return current_gwei
    except Exception as e:
        log(f"⚠️ Erreur fetch Gwei: {e}")
        mail(f"⚠️ Erreur fetch Gwei: {e}")
        return current_gwei

def gas_fee_usd(bnb_price, gwei):
    fee_wei = int(gwei * 1e9 * GAS_LIMIT)
    fee_bnb = Decimal(fee_wei) / Decimal(1e18)
    return fee_bnb * bnb_price

def get_bnb_price():
    url = f"https://api.dexscreener.com/latest/dex/tokens/{WBNB}"
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=8).json()
            pair = r["pairs"][0]
            price = Decimal(str(pair["priceUsd"]))
            change = float(pair["priceChange"][H1])
            return price, change
        except Exception as e:
            log(f"⚠️ get_bnb_price erreur ({attempt+1}/5): {e}")
            time.sleep(60)

    log("❌ get_bnb_price échec après 5 tentatives")
    return None, None
    
def get_mrs_price():
    url = f"https://api.dexscreener.com/latest/dex/tokens/{CONTRACT_MRS}"
    try:
        r = requests.get(url, timeout = 8).json()
        pair = r["pairs"][0]
        price = Decimal(str(pair["priceUsd"]))
        return price
    except Exception as e:
        log(f"❌ get_mrs_price error: {e}")
        return None

def get_mrs_last_tx():
    url = f"https://api.dexscreener.com/latest/dex/tokens/{CONTRACT_MRS}"
    try:
        j = requests.get(url,timeout = 8).json()
        pairs = j.get("pairs", [])
        if not pairs:
            return None
        pair = next((p for p in pairs if p.get("chain")=="bsc"),pairs[0])
        h1 = pair.get("txns", {}).get(H1, {})
        total = h1.get("buys", 0) + h1.get("sells", 0)
        return total
    except:
        return None

def wait_random():
    delay = random.randint(RANDOM_MIN,RANDOM_MAX)
    if DRY_RUN:
        log(f"⏳ Attente aléatoire de {DRY_RUN_SLEEP//60} min avant prochaine tx...")
    else:
        log(f"⏳ Attente aléatoire de {delay//60} min avant prochaine tx...")
    time.sleep(delay if not DRY_RUN else DRY_RUN_SLEEP)

# ==============================
# ✔️  Approve Wallets "infinity"
# ==============================

def approve_infinity(wallet, private_key, gwei):  
    MAX_UINT = int(2**256 - 1)

    try:
        current_allowance = token.functions.allowance(wallet, PANCAKE_ROUTER).call()
        if current_allowance > 0:
            log(f"📌 Wallet {wallet} already approved (infinity)")
            return
        
        tx = token.functions.approve(PANCAKE_ROUTER, MAX_UINT).build_transaction({
            "from": wallet,
            "nonce": w3.eth.get_transaction_count(wallet),
            "gas": GAS_LIMIT_APPROVE,
            "maxFeePerGas": int(gwei * 1e9),
            "maxPriorityFeePerGas": int(gwei * 1e9),
            "chainId": 56
        })

        # Signature & envoi
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

        log(f"🚀 Approve envoyé, attente de confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            log(f"✅ APPROVE CONFIRMÉ : https://bscscan.com/tx/0x{tx_hash.hex()}")
            mail(f"✅ APPROVE CONFIRMÉ : https://bscscan.com/tx/0x{tx_hash.hex()}")
        else:
            log("❌ Approve échoué")
            mail("❌ Approve échoué")
        time.sleep(10)

    except Exception as e:
        log(f"⚠️ Erreur lors de l'approve infinity pour {wallet}: {e}")
        time.sleep(5)

# =======================
# ✅  BUY :    MRS -> BNB
# =======================

def buy(wallet, private_key, bnb_amount, gwei):
    bnb_price, _ = get_bnb_price()
    if bnb_price is None:
        log("❌ Impossible de récupérer le prix BNB → BUY annulé")
        mail("❌ Impossible de récupérer le prix BNB → BUY annulé")
        return
    gas_usd = gas_fee_usd(bnb_price, gwei)
    if gas_usd > MAX_GAS_USD:
        log(f"⛔ Gas trop cher ({gas_usd:.4f}$) > {MAX_GAS_USD}$ — BUY annulé")
        mail(f"⛔ Gas trop cher ({gas_usd:.4f}$) > {MAX_GAS_USD}$ — BUY annulé")
        return
    
    amount_in_wei = to_wei(bnb_amount)
    path = [WBNB, CONTRACT_MRS]
    amounts = router.functions.getAmountsOut(amount_in_wei, path).call()
    min_out = int(amounts[-1] * (1 - SLIPPAGE))             # Slippage Max

    tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        min_out,path,wallet,int(time.time())+120
    ).build_transaction({
        "from":wallet,
        "value":amount_in_wei,
        "gas":GAS_LIMIT,
        "maxFeePerGas": w3.to_wei(gwei, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(gwei, "gwei"),
        "nonce":w3.eth.get_transaction_count(wallet),
        "chainId": 56
    })

    if DRY_RUN: 
        log(f"[DRY_RUN] BUY {bnb_amount:.5f} BNB tx prepared. min_out = {from_wei(min_out, token.functions.decimals().call()):.2f} MRS")
    else:
        # Signature & envoi
        if TRADING:
            signed = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                log(f"✅ BUY sent: https://bscscan.com/tx/0x{tx_hash.hex()}")
            else:
                log(f"⛔ BUY FAILED : https://bscscan.com/tx/0x{tx_hash.hex()}")
                mail(f"⛔ BUY FAILED : https://bscscan.com/tx/0x{tx_hash.hex()}")

# =======================
# 🟥  SELL :   BNB -> MRS
# =======================

def sell(wallet, private_key, token_wei, gwei):
    bnb_price, _ = get_bnb_price()
    if bnb_price is None:
        log("❌ Impossible de récupérer le prix BNB → SELL annulé")
        mail("❌ Impossible de récupérer le prix BNB → SELL annulé")
        return
    gas_usd = gas_fee_usd(bnb_price, gwei)
    if gas_usd > MAX_GAS_USD:
        log(f"⛔ Gas trop cher ({gas_usd:.4f}$) > {MAX_GAS_USD}$ — SELL annulé")
        mail(f"⛔ Gas trop cher ({gas_usd:.4f}$) > {MAX_GAS_USD}$ — SELL annulé")
        return

    path = [CONTRACT_MRS,WBNB]
    amounts = router.functions.getAmountsOut(token_wei, path).call()
    min_out = int(amounts[-1] * (1 - SLIPPAGE))
    decimals = token.functions.decimals().call()
    token_amount = from_wei(token_wei, decimals)

    tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
        token_wei,min_out,path,wallet,int(time.time())+120
    ).build_transaction({
        "from":wallet,
        "gas":GAS_LIMIT,
        "maxFeePerGas": w3.to_wei(gwei, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(gwei, "gwei"),
        "nonce":w3.eth.get_transaction_count(wallet),
        "chainId": 56
    })

    if DRY_RUN: 
        log(f"[DRY_RUN] SELL {token_amount:.2f} MRS tx prepared. min_out = {from_wei(min_out, token.functions.decimals().call()):.5f} BNB")
    else:
        # Signature & envoi
        if TRADING:
            signed = w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt.status == 1:
                log(f"🟥 SELL sent: https://bscscan.com/tx/0x{tx_hash.hex()}")
            else:
                log(f"⛔ SELL FAILED : https://bscscan.com/tx/0x{tx_hash.hex()}")
                mail(f"⛔ SELL FAILED : https://bscscan.com/tx/0x{tx_hash.hex()}")

# =====================
# 🔁  Boucle principale
# =====================

def main_loop():
    wallets = []
    gwei = GWEI
    print("")
    for kp,ep in zip(KEY_PATHS, ENC_PATHS):
        pk = load_private_key(kp, ep)
        addr = get_wallet_address(pk)
        wallets.append({"pk":pk, "addr":addr})
        log(f"🔑 Wallet loaded: {get_wallet_name(addr)} {addr}")
        if not DRY_RUN:
            if APPROVE:
                approve_infinity(addr, pk, gwei)
    if DRY_RUN:
        log(f"🤖 Bot démarré {"(H1)" if H1 == "h1" else "(m5)"} - MODE ESSAI {"ON 💡" if DRY_RUN else "OFF" } ({gwei:.2f} Gwei)")
    else:
        log(f"🤖 Bot démarré {"(H1)" if H1 == "h1" else "(m5)"} - Trading {"ON" if TRADING else "OFF"} ({gwei:.2f} Gwei)")
        mail(f"🤖 Bot démarré {"(H1)" if H1 == "h1" else "(m5)"} - Trading {"ON" if TRADING else "OFF"} ({gwei:.2f} Gwei)")
    
    wallet_idx = 0
    first_tx = True
    while True:
        if not in_active_hours():
            log(f"🕒 Hors plage horaire ({START_HOUR}h-{END_HOUR}h). Vérification dans 1 heures.")
            time.sleep(60 * 60)
            continue
        ping()
        if get_wallet_name(addr) == "Account22":
            gwei = adjust_gas(GWEI)
        
        if WALLETS_RANDOM:
            if wallet_idx == datetime.today().weekday() or wallet_idx == 2*datetime.today().weekday() or wallet_idx == random.randint(0, 13):
                wallet_idx = random.randint(0, 13)
        wallet = wallets[wallet_idx]
        wallet_idx = (wallet_idx+1)%len(wallets)
        pk, addr = wallet["pk"], wallet["addr"]

        bnb_price, bnb_change = get_bnb_price()
        mrs_price = get_mrs_price()
        if bnb_price is None or bnb_change is None or mrs_price is None:
            log(f"❌ Erreur BNB price, retry in {RETRY_WAIT_SECONDS} min.")
            mail(f"❌ Erreur BNB price, retry in {RETRY_WAIT_SECONDS} min.")
            time.sleep(RETRY_WAIT_SECONDS * 60)
            continue

        if first_tx:
            last_tx = get_mrs_last_tx()
            if last_tx is None:
                log("❌ Dexscreener returned None -> trade direct")
                mail("❌ Dexscreener returned None -> trade direct")
            elif last_tx > 0:
                log(f"⏳ {last_tx} txs dans h1 -> attente aléatoire {RANDOM_MIN//60}-{RANDOM_MAX//60} min avant première tx")
                wait_random()
            first_tx = False
        else:
            wait_random()
            
        ping()
        bnb_bal, mrs_bal_decimal, mrs_bal_wei = get_balances(addr)
        bnb_value_usd = bnb_bal * bnb_price                     # Wallet bnb USB
        mrs_value_usd = mrs_bal_decimal * mrs_price             # Wallet MRS USB
        wallet_name = get_wallet_name(addr)
        print("")
        log(f"📜 Wallet {wallet_name}: BNB ${bnb_value_usd:.2f}, {mrs_bal_decimal:.2f} MRS")
        
        # IF Wallet BNB < $5 -> SELL MRS
        if bnb_value_usd < MIN_BNB_USD_THRESHOLD and mrs_bal_wei > 0:
            sell_amount = int(mrs_bal_wei * SELL_PORTION)
            log(f"💧 BNB < ${MIN_BNB_USD_THRESHOLD}, SELL {SELL_PORTION*100:.1f}% MRS")
            sell(addr, pk, sell_amount, gwei)
            continue

        # IF Wallet MRS < $5 -> BUY MRS
        if mrs_value_usd < MIN_MRS_USD_THRESHOLD and bnb_value_usd > 0:
            buy_amount = bnb_bal * BUY_PORTION
            log(f"💧 MRS < ${MIN_MRS_USD_THRESHOLD}, BUY {BUY_PORTION*100:.1f}% BNB -> MRS")
            buy(addr, pk, buy_amount, gwei)
            continue

        # BUY
        if bnb_change >= 0:
            buy_amount = bnb_bal * BUY_PORTION
            if buy_amount > 0: 
                log(f"↗️  BNB Up +{bnb_change:.2f}% (${bnb_price:.2f}) : BUY {buy_amount:.5f} BNB -> MRS")
                buy(addr, pk, buy_amount, gwei)
        # SELL
        else:
            if mrs_bal_wei > 0:
                sell_amount = int(mrs_bal_wei * SELL_PORTION)
                log(f"↘️  BNB Down {bnb_change:.2f}%🔻 (${bnb_price:.2f}) -> SELL {SELL_PORTION*100:.1f}% MRS")
                sell(addr, pk, sell_amount, gwei)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("/n")
        log("🛑 Arrêt manuel du bot")
