"""Gmail API email sender — замена Django SMTP backend."""
import base64
import os
import pickle
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from googleapiclient.discovery import build


def _get_credentials():
    # На Render: храни token.pickle как base64 в env GMAIL_TOKEN_B64
    token_b64 = os.getenv("GMAIL_TOKEN_B64")
    if token_b64:
        return pickle.loads(base64.b64decode(token_b64))

    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.pickle")
    with open(token_path, "rb") as f:
        return pickle.load(f)


def _get_service():
    creds = _get_credentials()
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def send_email(to, subject, text_body, html_body=None, attachments=None):
    """
    to          : str или list[str]
    attachments : list of (filename, bytes, mimetype)  — например PDF
    """
    service = _get_service()

    if html_body or attachments:
        msg = MIMEMultipart("mixed")
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body:
            alt.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt)
        if attachments:
            for filename, data, mimetype in attachments:
                part = MIMEApplication(data, _subtype=mimetype.split("/")[-1])
                part.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(part)
    else:
        msg = MIMEText(text_body, "plain", "utf-8")

    msg["to"] = ", ".join(to) if isinstance(to, list) else to
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
