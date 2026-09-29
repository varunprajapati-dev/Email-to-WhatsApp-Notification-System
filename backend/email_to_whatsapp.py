from gmail_service import get_gmail_service
from whatsapp_service import send_whatsapp_message
from database import save_notification

print("🔥 NEW EMAIL_TO_WHATSAPP.PY VERSION LOADED 🔥")

import os
import time
import base64
import re
from dotenv import load_dotenv


# ==========================================
# LOAD ENVIRONMENT VARIABLES
# ==========================================

load_dotenv(".env")


# ==========================================
# DECODE GMAIL DATA
# ==========================================

def decode_base64(data):

    if not data:
        return ""

    try:

        # Gmail base64 padding fix
        data += "=" * (-len(data) % 4)

        decoded = base64.urlsafe_b64decode(
            data.encode("utf-8")
        )

        return decoded.decode(
            "utf-8",
            errors="ignore"
        )

    except Exception as e:

        print("❌ Body decode error:", e)

        return ""


# ==========================================
# REMOVE HTML TAGS
# ==========================================

def clean_html(html):

    if not html:
        return ""

    # Remove script and style
    html = re.sub(
        r"<script.*?>.*?</script>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE
    )

    html = re.sub(
        r"<style.*?>.*?</style>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Convert some HTML tags into new lines
    html = re.sub(
        r"<br\s*/?>",
        "\n",
        html,
        flags=re.IGNORECASE
    )

    html = re.sub(
        r"</p>",
        "\n",
        html,
        flags=re.IGNORECASE
    )

    html = re.sub(
        r"</div>",
        "\n",
        html,
        flags=re.IGNORECASE
    )

    # Remove all remaining HTML tags
    text = re.sub(
        r"<[^>]+>",
        "",
        html
    )

    # Clean extra spaces
    text = re.sub(
        r"\n\s*\n+",
        "\n\n",
        text
    )

    return text.strip()


# ==========================================
# GET BODY FROM GMAIL PARTS
# ==========================================

def extract_email_body(service, message_id, payload):

    plain_text = ""
    html_text = ""

    def search_parts(part):

        nonlocal plain_text
        nonlocal html_text

        mime_type = part.get("mimeType", "")

        body = part.get("body", {})

        data = body.get("data")


        # ==================================
        # TEXT / PLAIN
        # ==================================

        if mime_type == "text/plain":

            if data:

                text = decode_base64(data)

                if text and not plain_text:
                    plain_text = text


        # ==================================
        # TEXT / HTML
        # ==================================

        elif mime_type == "text/html":

            if data:

                text = decode_base64(data)

                if text and not html_text:
                    html_text = text


        # ==================================
        # ATTACHMENT ID BODY
        # ==================================

        attachment_id = body.get("attachmentId")

        if attachment_id and mime_type in [
            "text/plain",
            "text/html"
        ]:

            try:

                attachment = service.users().messages().attachments().get(
                    userId="me",
                    messageId=message_id,
                    id=attachment_id
                ).execute()

                attachment_data = attachment.get("data")

                if attachment_data:

                    text = decode_base64(
                        attachment_data
                    )

                    if mime_type == "text/plain":

                        if text and not plain_text:
                            plain_text = text

                    elif mime_type == "text/html":

                        if text and not html_text:
                            html_text = text

            except Exception as e:

                print(
                    "❌ Attachment body error:",
                    e
                )


        # ==================================
        # RECURSIVELY SEARCH ALL PARTS
        # ==================================

        for subpart in part.get("parts", []):

            search_parts(subpart)


    # Start searching from main payload
    search_parts(payload)


    # Prefer plain text
    if plain_text.strip():

        return plain_text.strip()


    # Otherwise use HTML
    if html_text.strip():

        return clean_html(html_text)


    return "No email message content found."


# ==========================================
# GET LATEST EMAIL
# ==========================================

def get_latest_email():

    service = get_gmail_service()


    # Get latest email
    results = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        maxResults=1
    ).execute()


    messages = results.get("messages", [])


    if not messages:

        return None


    message_id = messages[0]["id"]


    # ==========================================
    # GET COMPLETE EMAIL
    # ==========================================

    message = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full"
    ).execute()


    payload = message.get("payload", {})

    headers = payload.get(
        "headers",
        []
    )


    sender = ""
    subject = ""
    date = ""


    # ==========================================
    # GET EMAIL HEADERS
    # ==========================================

    for header in headers:

        name = header.get("name", "")
        value = header.get("value", "")


        if name.lower() == "from":

            sender = value


        elif name.lower() == "subject":

            subject = value


        elif name.lower() == "date":

            date = value


    # ==========================================
    # GET COMPLETE EMAIL BODY
    # ==========================================

    body = extract_email_body(
        service,
        message_id,
        payload
    )


    return {

        "id": message_id,

        "sender": sender,

        "subject": subject,

        "date": date,

        "body": body

    }


# ==========================================
# RUN EMAIL TO WHATSAPP AUTOMATION
# ==========================================

def run_email_to_whatsapp():

    last_email_id = None


    print("📧 Email to WhatsApp service started...")


    # ==========================================
    # SET CURRENT EMAIL AS BASELINE
    # ==========================================

    try:

        latest_email = get_latest_email()

        if latest_email:

            last_email_id = latest_email["id"]

            print(
                "📌 Latest email saved as baseline."
            )

            print(
                "📌 Monitoring new emails now..."
            )

    except Exception as e:

        print(
            "❌ Gmail connection error:",
            e
        )


    # ==========================================
    # CONTINUOUS MONITORING
    # ==========================================

    while True:

        try:

            email = get_latest_email()


            if email:


                # ==================================
                # NEW EMAIL FOUND
                # ==================================

                if email["id"] != last_email_id:


                    print()
                    print("=" * 50)

                    print("📧 New Email Received")

                    print("=" * 50)

                    print("From:")
                    print(email["sender"])

                    print()

                    print("Subject:")
                    print(email["subject"])

                    print()

                    print("Body:")
                    print(email["body"])

                    print()

                    print("Date:")
                    print(email["date"])

                    print("=" * 50)


                    # ==================================
                    # LIMIT VERY LARGE EMAIL BODY
                    # ==================================

                    email_body = email["body"]

                    if len(email_body) > 3000:

                        email_body = (
                            email_body[:3000]
                            + "\n\n...Email content truncated..."
                        )


                    # ==================================
                    # CREATE WHATSAPP MESSAGE
                    # ==================================

                    whatsapp_message = f"""📧 New Email Received

👤 From:
{email['sender']}

📝 Subject:
{email['subject']}

📩 Message:

{email_body}

📅 Date:
{email['date']}
"""


                    print()
                    print("📱 Sending WhatsApp message...")


                    # ==================================
                    # SEND WHATSAPP MESSAGE
                    # ==================================

                    result = send_whatsapp_message(

                        os.getenv(
                            "WHATSAPP_TO_NUMBER"
                        ),

                        whatsapp_message

                    )


                    print(
                        "📱 WhatsApp API Response:"
                    )

                    print(result)


                    # ==================================
                    # CHECK RESULT
                    # ==================================

                    if "error" in result:


                        print(
                            "❌ WhatsApp message failed!"
                        )


                        save_notification(

                            email["sender"],

                            email["subject"],

                            email["date"],

                            "Failed"

                        )


                    else:


                        print(
                            "✅ WhatsApp notification sent!"
                        )


                        save_notification(

                            email["sender"],

                            email["subject"],

                            email["date"],

                            "Sent"

                        )


                        print(
                            "✅ Notification saved in database."
                        )


                    # ==================================
                    # REMEMBER EMAIL
                    # ==================================

                    last_email_id = email["id"]


                else:

                    print(
                        "⏳ No new email."
                    )


            else:

                print(
                    "📭 No email found."
                )


        except Exception as e:

            print(
                "❌ Error:",
                e
            )


        # ==========================================
        # CHECK EVERY 10 SECONDS
        # ==========================================

        time.sleep(10)