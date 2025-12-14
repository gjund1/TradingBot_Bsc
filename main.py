#!/usr/bin/env python3

import os, time, json, random, traceback, requests
from decimal import Decimal, getcontext
from typing import Optional, Tuple
from cryptography.fernet import Fernet
from web3 import Web3
from eth_account import Account

# ==========================
# CONFIG (modifie ici)
# ==========================

DRY_RUN = True  # Mode test (pas d'envoi de tx)

WALLETS_KEYS = [
    (os.path.expanduser("~/Documents/code/BotMRS/key/wallet1.key"),
     os.path.expanduser("~/Documents/code/BotMRS/key/wallet1.enc")),
]

BSC_RPC = os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/")
ETHSCAN_API_KEY = "3CQGMXHAZGSJZE5PK2M7EV23S3QFED6CGV"

MRS_TOKEN_ADDRESS = "0x14e3598571F4683CEA1Ff2a917F4a3354Cd5842b"
PANCAKE_ROUTER_RAW = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
WBNB_RAW = "0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

ACTIVE_START_HOUR = 6                               # 6h - 22h
ACTIVE_END_HOUR = 22

BUY_PORTION = Decimal("0.20")
SELL_PORTION = Decimal("0.75")
MIN_BNB_USD_THRESHOLD = Decimal("5.0")

SLIPPAGE = Decimal("0.01")
GWEI = Decimal("0.05")                              # 0.05 Gwei
GAS_LIMIT_SWAP = 170000
GAS_LIMIT_APPROVE = 100000
MAX_GAS_USD = Decimal("0.012")                      # frais max 0.012 $

MIN_TRIGGER_MIN = 5                                 # tx apres 5 a 100 minutes
MAX_TRIGGER_MIN = 100

RETRY_WAIT_SECONDS = 10 * 60                        # 10s
DEXSCR_NULL_WAIT = 10 * 60

random.seed()
HTTP_TIMEOUT = 10
getcontext().prec = 28                              # Decimal : 28

# ===========================
# Setup Web3 / contrats / ABI
# ===========================

w3 = Web3(Web3.HTTPProvider(BSC_RPC))
CONTRACT_MRS = Web3.to_checksum_address(MRS_TOKEN_ADDRESS)
PANCAKE_ROUTER = Web3.to_checksum_address(PANCAKE_ROUTER_RAW)
WBNB = Web3.to_checksum_address(WBNB_RAW)

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

router = w3.eth.contract(address=PANCAKE_ROUTER, abi=PANCAKE_ROUTER_ABI)
token = w3.eth.contract(address=CONTRACT_MRS, abi=ERC20_ABI)

# ==========================
# UTILITAIRES
# ==========================

def load_private_key_pair(fernet_path: str, enc_path: str) -> str:
    if not os.path.exists(fernet_path) or not os.path.exists(enc_path):
        raise FileNotFoundError(f"Key files not found: {fernet_path} or {enc_path}")
    with open(fernet_path, "rb") as f:
        fernet_key = f.read().strip()
    cipher = Fernet(fernet_key)
    with open(enc_path, "rb") as f:
        encrypted = f.read()
    priv = cipher.decrypt(encrypted).decode().strip()
    return priv

def to_wei(amount, decimals=18) -> int:
    return int((Decimal(amount) * (Decimal(10) ** decimals)).to_integral_value())

def from_wei(amount_int, decimals=18) -> Decimal:
    return Decimal(amount_int) / (Decimal(10) ** decimals)

def get_bnb_price_h1() -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """Récupère prix BNB et % changement 1h via Dexscreener (WBNB)."""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{WBNB}"
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        j = r.json()
        pair = j.get("pairs", [])[0]
        price = Decimal(str(pair.get("priceUsd", "0")))
        change = Decimal(str(pair.get("priceChange", {}).get("h1", "0")))
        return price, change
    except Exception as e:
        print("get_bnb_price_h1 error:", e)
        return None, None

# ====================================== 
# Dernière transaction MRS via EtherScan
# ======================================

def get_last_mrs_tx_timestamp() -> int | None:
    """
    Utilise l'API V2 de BscScan pour récupérer la timestamp de la dernière transaction du token MRS.
    """
    try:
        url = (
            f"https://api.etherscan.io/v2/api"
            f"?chainid=56"                                      # 56 = BSC
            f"&module=account"
            f"&action=tokentx"
            f"&contractaddress={CONTRACT_MRS}"
            f"&page=1&offset=1&sort=desc"
            f"&apikey={ETHSCAN_API_KEY}"
        )
        r = requests.get(url, timeout=10)
        data = r.json()

        if data.get("status") != "1" or "result" not in data or not data["result"]:
            print("❌ Clé API invalide ou aucun résultat.")
            print("Message:", data.get("message"))
            return None

        last_tx = data["result"][0]
        timestamp_unix = int(last_tx["timeStamp"])
        print(f"⏱ Dernière TX MRS détectée : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp_unix))}")
        return timestamp_unix

    except Exception as e:
        print(f"❌ Erreur lors de l'appel API : {e}")
        return None

# =================================
# TX helpers (approve / buy / sell)
# =================================

def current_gas_fee_usd(bnb_price_usd: Decimal, gas_limit: int = GAS_LIMIT_SWAP) -> Tuple[Decimal, int]:
    gas_price_wei = int(GWEI * Decimal(10**9))
    fee_wei = gas_price_wei * gas_limit
    fee_bnb = Decimal(fee_wei) / Decimal(10**18)
    fee_usd = fee_bnb * bnb_price_usd
    return fee_usd, gas_price_wei

def ensure_approval(wallet_addr: str, private_key: str, amount_token_wei: int) -> bool:
    try:
        allowance = token.functions.allowance(wallet_addr, PANCAKE_ROUTER).call()
    except Exception as e:
        print("Allowance read error:", e)
        allowance = 0
    if allowance >= amount_token_wei:
        return True
    approve_amount = int(amount_token_wei)
    nonce = w3.eth.get_transaction_count(wallet_addr, "pending")
    tx = token.functions.approve(PANCAKE_ROUTER, approve_amount).build_transaction({
        "from": wallet_addr,
        "nonce": nonce,
        "gas": GAS_LIMIT_APPROVE,
        "gasPrice": int(GWEI * Decimal(10**9)),
        "chainId": 56
    })
    print("[DEBUG] Approve tx prepared (DRY_RUN=%s): gas=%s gasPrice=%s wei amount=%s" % (DRY_RUN, tx["gas"], tx["gasPrice"], approve_amount))
    if DRY_RUN:
        return True
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print("Approve tx sent:", tx_hash.hex())
    return True
# ====================
# BUY :     MRS -> BNB
# ====================

def buy_with_bnb(wallet_addr: str, private_key: str, bnb_amount: Decimal):
    path = [WBNB, CONTRACT_MRS]
    amount_in_wei = to_wei(bnb_amount, 18)
    try:
        amounts = router.functions.getAmountsOut(amount_in_wei, path).call()
        expected_token = amounts[-1]
    except Exception as e:
        print("getAmountsOut failed (buy):", e)
        expected_token = 0
    amount_out_min = int(Decimal(expected_token) * (Decimal(1) - SLIPPAGE))
    nonce = w3.eth.get_transaction_count(wallet_addr, "pending")
    tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        amount_out_min,
        path,
        wallet_addr,
        int(time.time() + 180)
    ).build_transaction({
        "from": wallet_addr,
        "value": amount_in_wei,
        "nonce": nonce,
        "gas": GAS_LIMIT_SWAP,
        "gasPrice": int(GWEI * Decimal(10**9)),
        "chainId": 56
    })
    print("[DEBUG] BUY tx prepared (DRY_RUN=%s): spend %s BNB -> amount_out_min %s" % (DRY_RUN, bnb_amount, amount_out_min))
    if DRY_RUN:
        return None
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print("BUY tx sent:", tx_hash.hex())
    return tx_hash.hex()

# ====================
# SELL :    BNB -> MRS
# ====================

def sell_mrs_amount(wallet_addr: str, private_key: str, amount_token_wei: int):
    path = [CONTRACT_MRS, WBNB]
    ensure_approval(wallet_addr, private_key, amount_token_wei)
    try:
        amounts_out = router.functions.getAmountsOut(amount_token_wei, path).call()
        expected_bnb_out = amounts_out[-1]
        amount_out_min = int(Decimal(expected_bnb_out) * (Decimal(1) - SLIPPAGE))
    except Exception as e:
        print("getAmountsOut failed (sell):", e)
        amount_out_min = 0
    nonce = w3.eth.get_transaction_count(wallet_addr, "pending")
    tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
        amount_token_wei,
        int(amount_out_min),
        path,
        wallet_addr,
        int(time.time() + 180)
    ).build_transaction({
        "from": wallet_addr,
        "nonce": nonce,
        "gas": GAS_LIMIT_SWAP,
        "gasPrice": int(GWEI * Decimal(10**9)),
        "chainId": 56
    })
    print("[DEBUG] SELL tx prepared (DRY_RUN=%s): token_units=%s amount_out_min=%s" % (DRY_RUN, amount_token_wei, amount_out_min))
    if DRY_RUN:
        return None
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print("SELL tx sent:", tx_hash.hex())
    return tx_hash.hex()

# ==========================
# MAIN LOOP
# ==========================

def in_active_hours(now=None):
    if now is None:
        now = time.localtime()
    return (now.tm_hour >= ACTIVE_START_HOUR) and (now.tm_hour < ACTIVE_END_HOUR)

def main_loop():
    wallets = []
    for idx, (kf, ef) in enumerate(WALLETS_KEYS):
        try:
            priv = load_private_key_pair(kf, ef)
            addr = Account.from_key(priv).address
            wallets.append({"priv": priv, "addr": Web3.to_checksum_address(addr)})
            print(f"Wallet {idx+1} loaded: {addr}")
        except Exception as e:
            print(f"Erreur chargement wallet {idx+1}: {e}")
    if not wallets:
        print("Aucun wallet chargé, abort.")
        return

    wallet_count = len(wallets)
    current_idx = 0
    print("Bot démarré. DRY_RUN =", DRY_RUN)

    while True:
        try:
            now = time.localtime()
            if not in_active_hours(now):
                print("Hors plage active, sleep 10 min...")
                time.sleep(10 * 60)
                continue

            last_tx_ts = get_last_mrs_tx_timestamp()
            if last_tx_ts is None:
                print("BscScan returned None for last tx -> wait 10 minutes.")
                time.sleep(DEXSCR_NULL_WAIT)
                continue

            wait_minutes = random.randint(MIN_TRIGGER_MIN, MAX_TRIGGER_MIN)
            wait_seconds = wait_minutes * 60
            target_ts = int(last_tx_ts) + wait_seconds
            now_ts = int(time.time())
            to_wait = target_ts - now_ts

            if to_wait > 0:
                print(f"Dernière tx à {time.ctime(last_tx_ts)}. Attente planifiée = {wait_minutes} min -> target {time.ctime(target_ts)}")
                check_interval = 30
                while to_wait > 0:
                    new_last = get_last_mrs_tx_timestamp()
                    if new_last is None:
                        print("BscScan renvoie None pendant attente -> attendre 10 minutes puis re-eval.")
                        time.sleep(DEXSCR_NULL_WAIT)
                        break
                    if new_last > last_tx_ts:
                        print(f"Nouvelle tx détectée à {time.ctime(new_last)} -> reset timer.")
                        last_tx_ts = new_last
                        wait_minutes = random.randint(MIN_TRIGGER_MIN, MAX_TRIGGER_MIN)
                        wait_seconds = wait_minutes * 60
                        target_ts = int(last_tx_ts) + wait_seconds
                        to_wait = target_ts - int(time.time())
                        print(f"Nouveau target à {time.ctime(target_ts)} (attente {wait_minutes} min)")
                        continue
                    if to_wait <= 300:
                        bnb_price, _ = get_bnb_price_h1()
                        if bnb_price is not None:
                            fee_usd, _ = current_gas_fee_usd(bnb_price, GAS_LIMIT_SWAP)
                            if fee_usd > MAX_GAS_USD:
                                print(f"Gas trop élevé ({fee_usd}$) -> attendre {DEXSCR_NULL_WAIT}s puis retenter.")
                                time.sleep(DEXSCR_NULL_WAIT)
                                break
                    sleep_for = min(check_interval, max(1, to_wait))
                    time.sleep(sleep_for)
                    to_wait = target_ts - int(time.time())

                last_after = get_last_mrs_tx_timestamp()
                if last_after is None:
                    print("Après attente, pas de nouvelle tx détectée. On continue la boucle principale.")
                    last_after = last_tx_ts  # réutiliser l'ancienne valeur
                if last_after > target_ts:
                    continue

            wallet_obj = wallets[current_idx]
            wallet_addr = wallet_obj["addr"]
            priv = wallet_obj["priv"]
            print(f"=== Execution avec wallet {current_idx+1} : {wallet_addr} ===")

            bnb_price, bnb_change = get_bnb_price_h1()
            if bnb_price is None:
                print("Impossible récupérer prix BNB avant action -> retry plus tard.")
                time.sleep(RETRY_WAIT_SECONDS)
                continue

            fee_usd_now, gas_price_wei = current_gas_fee_usd(bnb_price, GAS_LIMIT_SWAP)
            print(f"Gas cost estimé: ${fee_usd_now:.6f} (gasPrice {gas_price_wei} wei)")
            if fee_usd_now > MAX_GAS_USD:
                print(f"Gas {fee_usd_now} > seuil {MAX_GAS_USD} -> retry in {RETRY_WAIT_SECONDS}s")
                time.sleep(RETRY_WAIT_SECONDS)
                continue

            bnb_bal = from_wei(w3.eth.get_balance(wallet_addr), 18)
            mrs_bal_units = token.functions.balanceOf(wallet_addr).call()
            try:
                mrs_decimals = token.functions.decimals().call()
            except Exception:
                mrs_decimals = 18
            mrs_bal = from_wei(mrs_bal_units, mrs_decimals)

            bnb_value_usd = bnb_bal * bnb_price
            print(f"Balances wallet: {bnb_bal:.6f} BNB (~${bnb_value_usd:.2f}), {mrs_bal:.6f} MRS")

            if bnb_value_usd < MIN_BNB_USD_THRESHOLD and mrs_bal_units > 0:
                print(f"BNB < ${MIN_BNB_USD_THRESHOLD} -> vendre {int(SELL_PORTION*100)}% MRS")
                sell_amount = int(Decimal(mrs_bal_units) * SELL_PORTION)
                sell_mrs_amount(wallet_addr, priv, sell_amount)
            else:
                if Decimal(bnb_change) > 0:
                    buy_amount_bnb = bnb_bal * BUY_PORTION
                    if buy_amount_bnb <= Decimal("0.0000001"):
                        print("Montant BNB trop petit pour acheter -> skip")
                    else:
                        print(f"BNB en hausse -> acheter pour {buy_amount_bnb:.6f} BNB (~${(buy_amount_bnb*bnb_price):.2f})")
                        buy_with_bnb(wallet_addr, priv, buy_amount_bnb)
                else:
                    if mrs_bal_units == 0:
                        print("Pas de MRS à vendre.")
                    else:
                        sell_amount = int(Decimal(mrs_bal_units) * SELL_PORTION)
                        print(f"BNB en baisse -> vendre {int(SELL_PORTION*100)}% soit {sell_amount} unités")
                        sell_mrs_amount(wallet_addr, priv, sell_amount)

            current_idx = (current_idx + 1) % wallet_count
            time.sleep(5)

        except Exception as e:
            print("Erreur non gérée dans main loop:", e)
            traceback.print_exc()
            print(f"Attente {RETRY_WAIT_SECONDS}s avant retry.")
            time.sleep(RETRY_WAIT_SECONDS)

if __name__ == "__main__":
    try:
        # ts = get_last_mrs_tx_timestamp()               # teste
        # print("Dernière tx timestamp:", ts)
        main_loop()
    except KeyboardInterrupt:
        print("🛑 Arrêt manuel du Bot !")