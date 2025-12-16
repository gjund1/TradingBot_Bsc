# approve_infinity_wallet.py

from web3 import Web3
from getpass import getpass
import time

# ✅ RPC BSC
RPC = "https://bsc-dataseed.binance.org/"
w3 = Web3(Web3.HTTPProvider(RPC))

GWEI = 0.05
GAS_LIMIT_APPROVE = 100000

# ✅ Router Pancake
PANCAKE_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"

# ✅ TON TOKEN
TOKEN_ADDRESS = "0x14e3598571F4683CEA1Ff2a917F4a3354Cd5842b"  # 🔴 Mets l'adresse de votre Token ici

# ✅ ABI minimal pour allowance/approve
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"},{"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"},{"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function"
    }
]

token = w3.eth.contract(address=TOKEN_ADDRESS, abi=ERC20_ABI)

def main():
    print("⚠️  Colle ta PRIVATE KEY (0x...). Elle ne sera pas affichée.")
    priv = getpass("PRIVATE_KEY: ").strip()
    if not priv:
        print("❌ Aucune clé fournie — arrêt.")
        return

    # ✅ Adresse du wallet
    wallet = w3.eth.account.from_key(priv).address
    print(f"\n🔑 Wallet détecté : {wallet}")

    # ✅ Vérifie l'allowance
    MAX_UINT = int(2**256 - 1)
    allowance = token.functions.allowance(wallet, PANCAKE_ROUTER).call()

    if allowance >= MAX_UINT // 2:                             # ou bien  '> 0'
        print("✅ APPROVE déjà infini — rien à faire.")
        return

    print("⏳ Envoi de l'Approve Infinity...")

    tx = token.functions.approve(PANCAKE_ROUTER, MAX_UINT).build_transaction({
        "from": wallet,
        "nonce": w3.eth.get_transaction_count(wallet),
        "gas": GAS_LIMIT_APPROVE,
        "maxFeePerGas": int(GWEI*1e9),
        "maxPriorityFeePerGas": int(GWEI*1e9),
        "chainId": 56
    })

    signed = w3.eth.account.sign_transaction(tx, priv)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    print(f"✅ APPROVE INFINITY envoyé !")
    print(f"🔗 https://bscscan.com/tx/0x{tx_hash.hex()}")

    print("⏳ Attente 5 sec pour laisser le réseau confirmer...")
    time.sleep(5)

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status == 1:
        print(f"✅ Terminé ! Tu peux passer au wallet suivant.")
    else:
        print("❌ Approve échoué")

if __name__ == "__main__":
    main()
