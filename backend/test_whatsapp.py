from whatsapp_service import send_whatsapp_message
import os
from dotenv import load_dotenv

load_dotenv()

to_number = os.getenv("WHATSAPP_TO_NUMBER")

result = send_whatsapp_message(
    to_number,
    "Hello! This message is sent from Python Flask 🚀"
)

print(result)