# ==================== CONFIGURATION ====================
SMTP_SERVER = "mail.qudslab.online"  # e.g., smtp.gmail.com, smtp.mailtrap.io
SMTP_PORT = 587                 # 465 for SSL, 587 for STARTTLS
SENDER_EMAIL = "business@qudslab.online"
SENDER_PASSWORD = "Asdf.1234"  # Use an App Password, NOT your main password
RECEIVER_EMAIL = "mahir.shahriar4011@gmail.com"
# =======================================================
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
def send_test_email():
    message = MIMEMultipart()
    message["From"] = SENDER_EMAIL
    message["To"] = RECEIVER_EMAIL
    message["Subject"] = "aaPanel SMTP Working Test"
    body = "Success! The aaPanel SMTP test script successfully authenticated and sent this mail."
    message.attach(MIMEText(body, "plain"))
    # Force Python to tolerate the hostname mismatch (qudslab.com vs rezwanahmedsami.com)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        print(f"Opening connection to {SMTP_SERVER} on port {SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        # 1. Identify ourselves to the server
        print("Sending initial EHLO...")
        server.ehlo()
        # 2. Upgrade the unencrypted connection to secure TLS
        print("Securing connection with STARTTLS...")
        server.starttls(context=context)
        # 3. Re-identify ourselves over the newly encrypted channel (Postfix rules require this)
        print("Sending post-TLS EHLO...")
        server.ehlo()
        # 4. Authenticate
        print("Attempting login...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        # 5. Send mail
        print("Login successful! Sending email...")
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, message.as_string())
        print(f" Email successfully sent to {RECEIVER_EMAIL}!")
        server.quit()
    except Exception as e:
        print(f"\n An error occurred: {e}")
if __name__ == "__main__":
    send_test_email()
