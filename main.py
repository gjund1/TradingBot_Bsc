#!/usr/bin/env python3

import os, time, json, math, requests, random
from decimal import Decimal
from cryptography.fernet import Fernet
from web3 import Web3
from eth_account import Account

# ========== CONFIG ==========
KEY_PATH = os.path.expanduser("~/Documents/code/BotMRS/key/.mrs_bot_key")
ENC_PATH = os.path.expanduser("~/Documents/code/BotMRS/key/.mrs_bot_key.enc")

BSC_RPC = os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/")
w3 = Web3(Web3.HTTPProvider(BSC_RPC))

CONTRACT_MRS = Web3.to_checksum_address("0x14e3598571F4683CEA1Ff2a917F4a3354Cd5842b")
PANCAKE_ROUTER = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
WBNB = Web3.to_checksum_address("0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")

# Strategy params
DRY_RUN = True                      # True = simulation only

ACTIVE_START_HOUR = 6               # inclusive
ACTIVE_END_HOUR = 22                # exclusive -> active when hour in [6,21]
POLL_INTERVAL_SECONDS = 60          # internal small sleeps

BUY_PORTION = Decimal("0.2")        # 1/5 of BNB wallet
SELL_PORTION = Decimal("0.75")      # 3/4 of MRS wallet
MIN_BNB_USD_THRESHOLD = Decimal("5.0")  # if BNB value < $5 => sell 3/4 MRS
MAX_GAS_USD = Decimal("0.011")      # threshold
GWEI = 0.05                         # https://bscscan.com/gastracker
GAS_LIMIT_EST = 170000              # gas limit estimate for swaps 210 000 - 170 000

RETRY_WAIT_SECONDS = 5 * 60         # 5 minutes

# Router & token ABIs (minimal: swap support with fee-on-transfer + getAmountsOut)
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

# ========== HELPERS ==========

def load_private_key_from_encrypted_files():
    if not os.path.exists(KEY_PATH) or not os.path.exists(ENC_PATH):
        raise FileNotFoundError("Fichiers de clé introuvables. Exécute setup_key.py d'abord.")
    with open(KEY_PATH, "rb") as f:
        fernet_key = f.read().strip()
    cipher = Fernet(fernet_key)
    with open(ENC_PATH, "rb") as f:
        encrypted = f.read()
    decrypted = cipher.decrypt(encrypted).decode().strip()
    return decrypted

def get_wallet_address(private_key):
    acct = Account.from_key(private_key)
    return Web3.to_checksum_address(acct.address)

def to_wei(amount, decimals=18):
    # amount: Decimal or float or str -> returns int wei-like using decimals
    amt = Decimal(amount)
    return int((amt * (Decimal(10) ** decimals)).to_integral_value(rounding="ROUND_DOWN"))

def from_wei(amount_int, decimals=18):
    return Decimal(amount_int) / (Decimal(10) ** decimals)

# --- get BNB USD price from Dexscreener
def get_bnb_price_h1():
    url = f"https://api.dexscreener.com/latest/dex/tokens/{WBNB}"
    r = requests.get(url).json()
    pair = r["pairs"][0]
    price = float(pair["priceUsd"])
    change_h1 = float(pair["priceChange"]["h1"])
    return price, change_h1

# --- fetch Dexscreener price for MRS
def get_mrs_price_from_dexscreener():
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{CONTRACT_MRS}"
        r = requests.get(url, timeout=8)
        j = r.json()
        pairs = j.get("pairs", [])
        if not pairs:
            return None
        # prefer bsc chain pair
        for p in pairs:
            if p.get("chain") == "bsc" or p.get("chainId") == "bsc":
                return Decimal(str(p.get("priceUsd", 0)))
        return Decimal(str(pairs[0].get("priceUsd", 0)))
    except Exception as e:
        print("Erreur get_mrs_price:", e)
        return None

# --- wallet balances
def get_bnb_balance(wallet_addr):
    bal = w3.eth.get_balance(wallet_addr)
    return from_wei(bal, 18)

def get_mrs_balance(wallet_addr):
    try:
        bal = token.functions.balanceOf(wallet_addr).call()
        decimals = token.functions.decimals().call()
        return from_wei(bal, decimals), bal, decimals
    except Exception as e:
        print("Erreur get_mrs_balance:", e)
        return Decimal(0), 0, 18

# --- gas fee estimation in USD
def current_gas_fee_usd(bnb_price_usd, gas_limit=GAS_LIMIT_EST):
    gas_price_wei = GWEI * 10**9             # wei per unit
    # fee in wei = gas_price_wei * gas_limit
    fee_wei = gas_price_wei * gas_limit
    fee_bnb = Decimal(fee_wei) / Decimal(10**18)
    fee_usd = fee_bnb * Decimal(bnb_price_usd)
    return fee_usd, gas_price_wei

# --- Approval helper
def ensure_approval(wallet_addr, private_key, amount_token_wei):
    # check allowance
    try:
        allowance = token.functions.allowance(wallet_addr, PANCAKE_ROUTER).call()
    except Exception as e:
        print("Allowance read error:", e)
        allowance = 0
    if allowance >= amount_token_wei:
        return True
    # build approve tx
    approve_fn = token.functions.approve(PANCAKE_ROUTER, amount_token_wei)
    nonce = w3.eth.get_transaction_count(wallet_addr)
    tx = approve_fn.build_transaction({
        "from": wallet_addr,
        "nonce": nonce,
        "gas": 100000,
        "gasPrice": w3.eth.gas_price
    })
    if DRY_RUN:
        print("[DRY_RUN] Would send approve tx:", tx)
        return True
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print("Approve tx sent:", tx_hash.hex())
    # Wait for receipt? optional
    return True

# --- Buy MRS with BNB (supports fee-on-transfer)
def buy_with_bnb(wallet_addr, private_key, bnb_amount):
    path = [WBNB, CONTRACT_MRS]
    amount_in_wei = to_wei(bnb_amount, 18)
    # estimate amounts out (view)
    try:
        amounts = router.functions.getAmountsOut(amount_in_wei, path).call()
        expected_token = amounts[-1]
    except Exception as e:
        print("getAmountsOut failed:", e)
        expected_token = 0
    amount_out_min = int(expected_token * (1 - 0.20))  # conservative slippage 20% (token volatile)
    deadline = int(time.time()) + 120
    nonce = w3.eth.get_transaction_count(wallet_addr)
    tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        amount_out_min,
        path,
        wallet_addr,
        deadline
    ).build_transaction({
        "from": wallet_addr,
        "value": amount_in_wei,
        "gas": GAS_LIMIT_EST,
        "gasPrice": w3.eth.gas_price,
        "nonce": nonce
    })
    if DRY_RUN:
        print("[DRY_RUN] BUY tx prepared. BNB amount:", bnb_amount, "amount_out_min:", amount_out_min)
        return None
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print("Buy tx sent:", tx_hash.hex())
    return tx_hash.hex()

# --- Sell MRS for BNB
def sell_mrs_amount(wallet_addr, private_key, amount_token_wei):
    path = [CONTRACT_MRS, WBNB]
    # ensure approval
    ensure_approval(wallet_addr, private_key, amount_token_wei)
    amount_out_min = 0  # keep 0 for conservative; can compute estimate and subtract slippage
    deadline = int(time.time()) + 120
    nonce = w3.eth.get_transaction_count(wallet_addr)
    tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
        amount_token_wei,
        int(amount_out_min),
        path,
        wallet_addr,
        deadline
    ).build_transaction({
        "from": wallet_addr,
        "gas": GAS_LIMIT_EST,
        "gasPrice": w3.eth.gas_price,
        "nonce": nonce
    })
    if DRY_RUN:
        print("[DRY_RUN] SELL tx prepared. token_amount_wei:", amount_token_wei)
        return None
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print("Sell tx sent:", tx_hash.hex())
    return tx_hash.hex()

# ========== CORE LOGIC ==========

def in_active_hours(now=None):
    if now is None:
        now = time.localtime()
    hour = now.tm_hour
    return (hour >= ACTIVE_START_HOUR) and (hour < ACTIVE_END_HOUR)

def wait_until_next_hour():
    # attendre le prochain top d’heure
    now = time.time()
    next_hour = (int(now // 3600) + 1) * 3600
    to_wait_hour = next_hour - now

    # attente jusqu’au prochain top
    print(f"🕒 Attente {int(to_wait_hour)} sec jusqu’au prochain top d’heure...")
    if DRY_RUN:
        time.sleep(2)
    else:
        time.sleep(to_wait_hour)

    # délai aléatoire entre 2 et 58 minutes
    random_delay = random.randint(2 * 60, 58 * 60)
    print(f"🎲 Délai aléatoire : {random_delay//60} min")
    if DRY_RUN:
        time.sleep(2)
    else:
        time.sleep(random_delay)

def main_loop():
    print("Starting bot. DRY_RUN =", DRY_RUN)
    try:
        private_key = load_private_key_from_encrypted_files()
    except Exception as e:
        print("Cannot load private key:", e)
        return
    wallet = get_wallet_address(private_key)
    print("Wallet:", wallet)

    # Run forever
    while True:
        now = time.localtime()
        if not in_active_hours(now):
            print(f"Outside active hours ({ACTIVE_START_HOUR}-{ACTIVE_END_HOUR}). Next check at next hour.")
            wait_until_next_hour()
            continue

        # Align to start of hour: if current minute > 1s then wait until top of hour to avoid drift
        if now.tm_min != 0:
            print("Waiting until top of hour to run check.")
            wait_until_next_hour()

        # 1) Get BNB price now and 1h ago
        bnb_now, bnb_change = get_bnb_price_h1()
        if bnb_now is None or bnb_change is None:
            print("Cannot get BNB price history, retry in 60s.")
            time.sleep(60)
            continue
        bnb_now = Decimal(str(bnb_now))
        print(f"BNB price : {bnb_now:.2f}$ ({bnb_change:.2f}%)")

        # 2) Compute gas fee in USD and compare to threshold
        fee_usd, gas_price_wei = current_gas_fee_usd(bnb_now)
        print(f"Gas fee : {fee_usd:.6f}$    ({(gas_price_wei)/10**9:.2f} Gwei and limit {GAS_LIMIT_EST})")
        if fee_usd > MAX_GAS_USD:
            print(f"Gas fee {fee_usd:.6f}$ > threshold {MAX_GAS_USD}$. Retrying in {RETRY_WAIT_SECONDS}s.")
            time.sleep(RETRY_WAIT_SECONDS)
            continue

        # 3) Get wallet balances
        bnb_bal = get_bnb_balance(wallet)
        mrs_bal_decimal, mrs_bal_wei, mrs_decimals = get_mrs_balance(wallet)
        print(f"Wallet balances : {bnb_bal:.6f} BNB / {mrs_bal_decimal:.6f} MRS")

        # Compute BNB USD value of wallet
        bnb_value_usd = bnb_bal * bnb_now
        print(f"BNB wallet USD value: ${bnb_value_usd:.2f}")

        # If BNB wallet < threshold -> force SELL 3/4 MRS
        if bnb_value_usd < MIN_BNB_USD_THRESHOLD and mrs_bal_wei > 0:
            print(f"BNB USD value ${bnb_value_usd:.2f} < ${MIN_BNB_USD_THRESHOLD}. Selling {SELL_PORTION*100}% of MRS.")
            sell_amount_tokens = int(Decimal(mrs_bal_wei) * SELL_PORTION)
            sell_mrs_amount(wallet, private_key, sell_amount_tokens)
            # wait until next hour after action
            wait_until_next_hour()
            continue

        # 4) Decide action by BNB trend
        if bnb_change > 0:
            # BNB up -> BUY
            print("BNB is UP vs 1h ago -> BUY MRS")
            # buy amount = 1/5 of BNB wallet
            buy_bnb_amount = (Decimal(bnb_bal) * BUY_PORTION)
            # ensure we have > tiny amount
            if buy_bnb_amount <= Decimal("0.0000001"):
                print("Buy amount too small, skipping.")
            else:
                print(f"Preparing to buy MRS with {buy_bnb_amount:.6f} BNB (~${(buy_bnb_amount*bnb_now):.4f})")
                buy_with_bnb(wallet, private_key, buy_bnb_amount)
        else:
            # BNB down or flat -> SELL 3/4 MRS
            print("BNB is DOWN or flat vs 1h ago -> SELL 75% of MRS")
            if mrs_bal_wei == 0:
                print("No MRS balance to sell.")
            else:
                sell_amount_tokens = int(Decimal(mrs_bal_wei) * SELL_PORTION)
                print(f"Preparing to sell {SELL_PORTION*100}% of MRS (token units: {sell_amount_tokens})")
                sell_mrs_amount(wallet, private_key, sell_amount_tokens)

        # after action or no action, wait until next hour
        wait_until_next_hour()

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("🛑 Arrêt manuel du Bot !")
