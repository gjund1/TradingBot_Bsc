#!/usr/bin/env python3
# read_key.py
"""
Lecture / vérification de la clé privée chiffrée créée par setup_key.py

- Par défaut affiche une version masquée (premiers 6 + derniers 4 caractères)
- Avec --full affiche la clé complète (demande confirmation interactive)
"""

import os
import argparse
from cryptography.fernet import Fernet

KEY_PATH = os.path.join(".mrs_bot_key")
ENC_PATH = os.path.join(".mrs_bot_key.enc")

def load_and_decrypt():
    if not os.path.exists(KEY_PATH):
        raise FileNotFoundError(f"Fichier de clé de chiffrement introuvable: {KEY_PATH}")
    if not os.path.exists(ENC_PATH):
        raise FileNotFoundError(f"Fichier chiffré introuvable: {ENC_PATH}")

    with open(KEY_PATH, "rb") as f:
        fernet_key = f.read()
    with open(ENC_PATH, "rb") as f:
        encrypted = f.read()

    f = Fernet(fernet_key)
    try:
        priv = f.decrypt(encrypted)
    except Exception as e:
        raise RuntimeError("Échec du déchiffrement : clé de chiffrement invalide ou fichier corrompu.") from e

    return priv.decode().strip()

def mask_key(pk: str) -> str:
    if len(pk) <= 12:
        return pk[0:3] + "..." + pk[-3:]
    return pk[:6] + "..." + pk[-4:]

def main():
    parser = argparse.ArgumentParser(description="Vérifie et affiche (masqué) la clé privée chiffrée.")
    parser.add_argument("--full", action="store_true", help="Afficher la clé complète (demande confirmation).")
    args = parser.parse_args()

    try:
        priv = load_and_decrypt()
    except Exception as e:
        print("Erreur :", e)
        return

    print("✅ Déchiffrement réussi.")
    print("Chemins utilisés :")
    print("  clé de chiffrement :", KEY_PATH)
    print("  fichier chiffré     :", ENC_PATH)
    print()

    print("Clé privée (masquée) :", mask_key(priv))
    if args.full:
        # confirmation interactive pour éviter affichage accidentel
        confirm = input("\nAffichage COMPLET de la clé privée ? (tape 'YES' pour confirmer) : ")
        if confirm == "YES":
            print("\n----- CLÉ PRIVÉE EN CLAIR -----")
            print(priv)
            print("----- FIN -----")
        else:
            print("Confirmation non reçue — affichage complet annulé.")

if __name__ == "__main__":
    main()

