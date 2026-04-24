import re
import requests
from django.conf import settings

def normalize_phone(phone):
    phone = re.sub(r'\D', '', phone)
    if phone.startswith('8'):
        phone = '7' + phone[1:]
    return '+' + phone

def send_sms(phone, message):

    try:

        url = "https://smsc.kz/sys/send.php"

        params = {

            "login": settings.SMSC_LOGIN,

            "psw": settings.SMSC_PASSWORD,

            "phones": phone,

            "mes": message,

            "fmt": 3

        }

        r = requests.get(url, params=params)

        data = r.json()

        if "error" in data:

            return False, data["error"]

        return True, None

    except Exception as e:

        return False, str(e)