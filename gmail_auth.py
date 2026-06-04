"""
Запускать один раз локально для получения token.pickle:
    python gmail_auth.py

Нужен файл credentials.json рядом с этим скриптом.
После выполнения будет создан token.pickle.

Для Render — конвертируй token.pickle в base64:
    python -c "import base64; print(base64.b64encode(open('token.pickle','rb').read()).decode())"
И сохрани результат в переменную окружения GMAIL_TOKEN_B64.
"""
import base64
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("token.pickle", "wb") as f:
    pickle.dump(creds, f)

print("token.pickle создан.")
print()
print("Для Render скопируй эту строку в переменную GMAIL_TOKEN_B64:")
print(base64.b64encode(open("token.pickle", "rb").read()).decode())
