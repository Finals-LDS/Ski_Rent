from __future__ import annotations

import base64
import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

OTP_CACHE_KEY = "contract_sms_otp:{contract_id}"
COOLDOWN_KEY = "contract_sms_cooldown:{contract_id}"
OTP_TTL = 600
COOLDOWN_SEC = 45


def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"\s+", "", raw.strip())
    if not s:
        return ""
    if s.startswith("+"):
        return s
    if s.startswith("8") and len(s) == 11:
        return "+7" + s[1:]
    if s.startswith("7") and len(s) == 11:
        return "+" + s
    if s.isdigit() and len(s) == 10:
        return "+7" + s
    return s


def generate_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def _twilio_send(to_e164: str, body: str) -> tuple[bool, str]:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "") or ""
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    from_num = getattr(settings, "TWILIO_FROM_NUMBER", "") or ""
    if not (sid and token and from_num):
        return False, "twilio_not_configured"
    data = urllib.parse.urlencode(
        {"To": to_e164, "From": from_num, "Body": body}
    ).encode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    req = urllib.request.Request(url, data=data, method="POST")
    cred = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {cred}")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            if resp.status in (200, 201):
                return True, "twilio_ok"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode()
        except OSError:
            return False, str(e)
        try:
            data = json.loads(raw)
            msg = data.get("message") or data.get("more_info") or raw[:400]
        except json.JSONDecodeError:
            msg = raw[:400] if raw else str(e)
        logger.warning("Twilio: %s", msg)
        return False, msg
    except OSError as e:
        logger.warning("Twilio: %s", e)
        return False, str(e)


def send_contract_otp_sms(phone: str, code: str) -> tuple[bool, str]:
    phone = normalize_phone(phone)
    if not phone:
        return False, "no_phone"

    text = f"Ski Rent: код подписания договора {code}. Никому не сообщайте."

    sid = (getattr(settings, "TWILIO_ACCOUNT_SID", "") or "").strip()
    token = (getattr(settings, "TWILIO_AUTH_TOKEN", "") or "").strip()
    from_num = (getattr(settings, "TWILIO_FROM_NUMBER", "") or "").strip()

    if sid and token and from_num:
        ok, msg = _twilio_send(phone, text)
        if ok:
            return True, msg
        return False, msg

    if getattr(settings, "SMS_ALLOW_CONSOLE", False) or settings.DEBUG:
        logger.warning("SMS (режим без Twilio) -> %s : %s", phone, text)
        return True, "console_log"

    return False, "twilio_not_configured"


def store_otp(contract_id: int, code: str) -> None:
    cache.set(OTP_CACHE_KEY.format(contract_id=contract_id), code, OTP_TTL)


def verify_and_clear_otp(contract_id: int, code: str) -> bool:
    key = OTP_CACHE_KEY.format(contract_id=contract_id)
    expected = cache.get(key)
    if not expected or not code:
        return False
    if code.strip() != str(expected):
        return False
    cache.delete(key)
    return True


def cooldown_remaining(contract_id: int) -> int:
    until = cache.get(COOLDOWN_KEY.format(contract_id=contract_id))
    if not until:
        return 0
    return max(0, int(float(until) - time.time()))


def set_cooldown(contract_id: int) -> None:
    cache.set(
        COOLDOWN_KEY.format(contract_id=contract_id),
        time.time() + COOLDOWN_SEC,
        COOLDOWN_SEC + 5,
    )
