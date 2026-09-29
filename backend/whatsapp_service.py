import os
import requests
from dotenv import load_dotenv


def send_whatsapp_message(to_number, message):

    # Load latest environment variables
    load_dotenv(".env", override=True)

    WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION")

    # Check configuration
    if not WHATSAPP_ACCESS_TOKEN:
        return {
            "error": "WHATSAPP_ACCESS_TOKEN not found"
        }

    if not WHATSAPP_PHONE_NUMBER_ID:
        return {
            "error": "WHATSAPP_PHONE_NUMBER_ID not found"
        }

    url = (
        f"https://graph.facebook.com/"
        f"{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=data
    )

    return response.json()