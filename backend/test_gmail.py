from gmail_service import get_gmail_service

service = get_gmail_service()

results = service.users().messages().list(
    userId="me",
    labelIds=["INBOX"],
    maxResults=10
).execute()

messages = results.get("messages", [])

print("Total Inbox Emails:", len(messages))
print("=" * 60)

for message in messages:

    email_data = service.users().messages().get(
        userId="me",
        id=message["id"],
        format="metadata",
        metadataHeaders=["From", "Subject", "Date"]
    ).execute()

    headers = email_data["payload"]["headers"]

    sender = ""
    subject = ""
    date = ""

    for header in headers:

        if header["name"] == "From":
            sender = header["value"]

        elif header["name"] == "Subject":
            subject = header["value"]

        elif header["name"] == "Date":
            date = header["value"]

    print("From   :", sender)
    print("Subject:", subject)
    print("Date   :", date)
    print("ID     :", message["id"])
    print("-" * 60)