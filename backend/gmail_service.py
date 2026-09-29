import os
import json
from datetime import datetime

# =========================================================
# LOCAL DEVELOPMENT OAUTH
# =========================================================

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from database import (
    save_gmail_connection,
    get_gmail_connection
)


# =========================================================
# GMAIL SCOPES
# =========================================================

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly"
]


# =========================================================
# PATHS
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


CREDENTIALS_FILE = os.path.join(
    BASE_DIR,
    "credentials.json"
)


# =========================================================
# REDIRECT URI
# =========================================================

REDIRECT_URI = "http://localhost:5000/gmail/callback"


# =========================================================
# GOOGLE CLIENT CONFIG
# =========================================================

def get_google_client_config():

    try:

        with open(
            CREDENTIALS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)


        if "web" in data:

            config = data["web"]

        elif "installed" in data:

            config = data["installed"]

        else:

            raise ValueError(
                "Invalid credentials.json file."
            )


        return {
            "client_id": config.get("client_id"),

            "client_secret": config.get(
                "client_secret"
            ),

            "token_uri": config.get(
                "token_uri",
                "https://oauth2.googleapis.com/token"
            )
        }


    except Exception as e:

        print(
            "❌ Could not read Google client configuration:",
            e
        )

        return None


# =========================================================
# CREATE GOOGLE OAUTH FLOW
# =========================================================

def create_google_flow(
    code_verifier=None
):

    flow = Flow.from_client_secrets_file(

        CREDENTIALS_FILE,

        scopes=SCOPES,

        redirect_uri=REDIRECT_URI,

        autogenerate_code_verifier=False
    )


    if code_verifier:

        flow.code_verifier = code_verifier


    return flow


# =========================================================
# GET GOOGLE AUTHORIZATION URL
# =========================================================

def get_google_authorization_url():

    flow = Flow.from_client_secrets_file(

        CREDENTIALS_FILE,

        scopes=SCOPES,

        redirect_uri=REDIRECT_URI,

        autogenerate_code_verifier=True
    )


    authorization_url, state = flow.authorization_url(

        access_type="offline",

        include_granted_scopes="true",

        prompt="consent"
    )


    # IMPORTANT:
    # code_verifier must be returned and saved
    # in Flask session.

    code_verifier = flow.code_verifier


    return (
        authorization_url,
        state,
        code_verifier
    )


# =========================================================
# COMPLETE GOOGLE OAUTH
# =========================================================

def complete_google_oauth(
    state,
    authorization_response,
    code_verifier
):

    flow = create_google_flow(
        code_verifier=code_verifier
    )


    flow.state = state


    flow.fetch_token(

        authorization_response=authorization_response
    )


    return flow.credentials


# =========================================================
# SAVE USER GMAIL CONNECTION
# =========================================================

def save_user_gmail_connection(
    user_id,
    credentials
):

    try:

        service = build(
            "gmail",
            "v1",
            credentials=credentials
        )


        profile = (
            service
            .users()
            .getProfile(
                userId="me"
            )
            .execute()
        )


        google_email = profile.get(
            "emailAddress"
        )


        if not google_email:

            return {
                "success": False,
                "error": "Could not identify Gmail account."
            }


        token_expiry = None


        if credentials.expiry:

            token_expiry = (
                credentials
                .expiry
                .isoformat()
            )


        save_gmail_connection(

            user_id=user_id,

            google_email=google_email,

            access_token=credentials.token,

            refresh_token=credentials.refresh_token,

            token_expiry=token_expiry
        )


        print(
            f"✅ Gmail connected for user {user_id}: "
            f"{google_email}"
        )


        return {
            "success": True,
            "email": google_email
        }


    except Exception as e:

        print(
            "❌ Gmail connection save failed:",
            e
        )


        return {
            "success": False,
            "error": str(e)
        }


# =========================================================
# GET USER GMAIL CREDENTIALS
# =========================================================

def get_user_gmail_credentials(
    user_id
):

    connection = get_gmail_connection(
        user_id
    )


    if not connection:

        return None


    access_token = connection.get(
        "access_token"
    )


    refresh_token = connection.get(
        "refresh_token"
    )


    token_expiry = connection.get(
        "token_expiry"
    )


    expiry = None


    if token_expiry:

        try:

            expiry = datetime.fromisoformat(
                token_expiry
            )

        except Exception:

            expiry = None


    client_config = get_google_client_config()


    if not client_config:

        return None


    credentials = Credentials(

        token=access_token,

        refresh_token=refresh_token,

        token_uri=client_config["token_uri"],

        client_id=client_config["client_id"],

        client_secret=client_config["client_secret"],

        scopes=SCOPES,

        expiry=expiry
    )


    return credentials


# =========================================================
# GET USER GMAIL SERVICE
# =========================================================

def get_user_gmail_service(
    user_id
):

    credentials = get_user_gmail_credentials(
        user_id
    )


    if not credentials:

        return None


    # -----------------------------------------------------
    # Refresh expired token
    # -----------------------------------------------------

    if credentials.expired:

        if not credentials.refresh_token:

            print(
                "❌ Gmail refresh token missing."
            )

            return None


        try:

            credentials.refresh(
                Request()
            )


            connection = get_gmail_connection(
                user_id
            )


            if connection:

                token_expiry = None


                if credentials.expiry:

                    token_expiry = (
                        credentials
                        .expiry
                        .isoformat()
                    )


                save_gmail_connection(

                    user_id=user_id,

                    google_email=connection.get(
                        "google_email"
                    ),

                    access_token=credentials.token,

                    refresh_token=(
                        credentials.refresh_token
                        or connection.get(
                            "refresh_token"
                        )
                    ),

                    token_expiry=token_expiry
                )


            print(
                f"🔄 Gmail token refreshed for user {user_id}"
            )


        except Exception as e:

            print(
                "❌ Gmail token refresh failed:",
                e
            )

            return None


    # -----------------------------------------------------
    # Create Gmail service
    # -----------------------------------------------------

    try:

        return build(
            "gmail",
            "v1",
            credentials=credentials
        )


    except Exception as e:

        print(
            "❌ Gmail service creation failed:",
            e
        )

        return None