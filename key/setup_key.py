# setup_key.py

import os
from cryptography.fernet import Fernet
from getpass import getpass

key_path = os.path.join(".mrs_bot_key")         # clé de chiffrement (binaire)
enc_path = os.path.join(".mrs_bot_key.enc")     # clé privée chiffrée

def save_file(path, data):
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)
    print(f"Wrote {path} (chmod 600)")

def main():
    # Récupère ta clé privée (tu la colles ici une seule fois)
    print("⚠️  Colle ta PRIVATE KEY (0x...) puis ENTER. Le texte ne sera pas affiché.")
    priv = getpass("PRIVATE_KEY: ").strip()
    if not priv:
        print("Aucune clé fournie — abort.")
        return

    # Génère une clé symétrique Fernet
    fernet_key = Fernet.generate_key()
    f = Fernet(fernet_key)

    # Chiffre la clé privée
    encrypted = f.encrypt(priv.encode())

    # Sauvegarde la clé de chiffrement et le fichier chiffré
    save_file(key_path, fernet_key)
    save_file(enc_path, encrypted)

    print("\n✅ Clé chiffrée créée.")
    print(f"Fichiers :\n  {key_path}\n  {enc_path}")
#    print("Garde ces fichiers sur le serveur. Ne partage rien.")
#    print("Pour sécurité supplémentaire : restreins l'accès SSH et fais backup chiffré.")

if __name__ == "__main__":
    main()
