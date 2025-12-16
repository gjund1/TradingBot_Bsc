import time, socket, smtplib, email.utils
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ==============================
# ⚙️ CONFIGURATION GLOBALE
# ==============================

EMAIL = True
EMAIL_SENDER = "Email_Sender"
EMAIL_PASSWORD = "VotreMotDePasseIcI"
EMAIL_RECEIVER = "Email_Receiver"

# ==============================
# 🧩 FONCTIONS UTILES
# ==============================

# Affiche dans le terminal avec date et heure.
def log(message: str):
    now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{now} {message}")

# Teste la connexion Internet (Google DNS par défaut).
def internet_ok(host="8.8.8.8", port=53, timeout=3):
    while True:
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except Exception as e:
            log(f"⚠️ Internet check failed: {e}")

        log(f"🌐 Ping failed, retry in 15 min.")
        time.sleep(15 * 60)

# ==============================
# 📧 E-MAIL
# ==============================

# Envoye de l'email
def send_mail(corps, subject):
    internet_ok()

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.attach(MIMEText(corps, "plain", "utf-8"))

    try:
        serveur = smtplib.SMTP("smtp.free.fr", 587)
        serveur.starttls()
        serveur.login(EMAIL_SENDER, EMAIL_PASSWORD)
        serveur.send_message(msg)
        serveur.quit()
        log("📧 Mail envoyé avec succès !")
    except Exception as e:
        log(f"❌ Erreur lors de l'envoi du mail : {e}")
