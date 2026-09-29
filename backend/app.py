from flask import Flask, render_template, jsonify, request, redirect, url_for, session


from database import (
    get_notifications,
    get_notification_stats,
    save_notification,
    register_user,
    get_user_by_email,
    get_gmail_connection,
    get_all_gmail_connections,
    save_whatsapp_connection,
    get_whatsapp_connection,
    get_all_whatsapp_connections
)

from gmail_service import (
    get_user_gmail_service,
    get_google_authorization_url,
    complete_google_oauth,
    save_user_gmail_connection
)

import threading
import time
import os
import base64
import sqlite3
import re
import requests
import secrets
import json
from urllib.parse import urlencode

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash


# -----------------------------------
# LOAD ENVIRONMENT VARIABLES
# -----------------------------------

load_dotenv(".env")


# -----------------------------------
# META WHATSAPP EMBEDDED SIGNUP CONFIG
# -----------------------------------

META_APP_ID = os.getenv("META_APP_ID", "").strip()
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
META_WHATSAPP_CONFIG_ID = os.getenv("META_WHATSAPP_CONFIG_ID", "").strip()
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", os.getenv("WHATSAPP_API_VERSION", "v23.0")).strip()


# -----------------------------------
# FLASK APP
# -----------------------------------

app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static"
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "development-secret-key")


# -----------------------------------
# GLOBAL VARIABLES
# -----------------------------------

# Keep the latest processed/baseline email separately for every Gmail user.
last_email_ids = {}
processed_email_ids = set()
monitor_lock = threading.Lock()
monitor_started = False

# Persistent email-processing protection.
# This survives Flask restarts and prevents the same Gmail message ID
# from being sent to WhatsApp more than once.
def initialize_processed_emails_table():
    connection = sqlite3.connect("notifications.db")
    cursor = connection.cursor()

    cursor.execute("PRAGMA table_info(processed_emails)")
    columns = [row[1] for row in cursor.fetchall()]

    if not columns:
        cursor.execute("""
            CREATE TABLE processed_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                gmail_message_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, gmail_message_id)
            )
        """)
    elif "user_id" not in columns:
        # Migrate the old global table to a user-scoped table.
        cursor.execute("""
            ALTER TABLE processed_emails
            RENAME TO processed_emails_old
        """)

        cursor.execute("""
            CREATE TABLE processed_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                gmail_message_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, gmail_message_id)
            )
        """)

        # Old rows belonged to the previous single-user automation.
        # Attach them to the legacy automation user when available.
        legacy_user_id = int(os.getenv("AUTOMATION_USER_ID", "1"))

        cursor.execute("""
            INSERT OR IGNORE INTO processed_emails
            (user_id, gmail_message_id, status, created_at)
            SELECT ?, gmail_message_id, status, created_at
            FROM processed_emails_old
        """, (legacy_user_id,))

        cursor.execute("DROP TABLE processed_emails_old")

    connection.commit()
    connection.close()


def claim_email_for_processing(user_id, gmail_message_id):
    connection = sqlite3.connect("notifications.db")
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO processed_emails
            (user_id, gmail_message_id, status)
            VALUES (?, ?, 'processing')
        """, (user_id, gmail_message_id))

        connection.commit()
        return True

    except sqlite3.IntegrityError:
        connection.rollback()
        return False

    finally:
        connection.close()


def mark_email_processed(user_id, gmail_message_id, status):
    connection = sqlite3.connect("notifications.db")
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE processed_emails
        SET status = ?
        WHERE user_id = ?
        AND gmail_message_id = ?
    """, (status, user_id, gmail_message_id))

    connection.commit()
    connection.close()


def is_logged_in():
    return "user_id" in session

# -----------------------------------
# REGISTER
# -----------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # Basic validation
    if not name or not email or not password:
        return "Please fill all fields.", 400

    if len(password) < 8:
        return "Password must be at least 8 characters.", 400

    # Secure password hash
    password_hash = generate_password_hash(password)

    # Save user
    user_created = register_user(
        name,
        email,
        password_hash
    )

    if not user_created:
        return "Email is already registered.", 409

    return redirect(url_for("login"))

# -----------------------------------
# LOGIN
# -----------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # Check empty fields
    if not email or not password:
        return "Please enter email and password.", 400

    # Find user
    user = get_user_by_email(email)

    if not user:
        return "Invalid email or password.", 401

    if not check_password_hash(user["password_hash"], password):
        return "Invalid email or password.", 401

    # Create login session
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]

    print(f"✅ User logged in: {user['email']}")

    return redirect(url_for("home"))

# -----------------------------------
# LOGOUT
# -----------------------------------

@app.route("/logout")
def logout():

    session.clear()

    print("👋 User logged out successfully.")

    return redirect(url_for("login"))

# ==============================
# WHATSAPP EMBEDDED SIGNUP
# ==============================

def initialize_whatsapp_business_table():
    """Create the per-user Meta WhatsApp Business connection table."""
    connection = sqlite3.connect("notifications.db")
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_business_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            business_id TEXT,
            waba_id TEXT NOT NULL,
            phone_number_id TEXT NOT NULL,
            phone_number TEXT,
            access_token TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()


def get_whatsapp_business_connection(user_id):
    connection = sqlite3.connect("notifications.db")
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM whatsapp_business_connections
        WHERE user_id = ?
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    connection.close()

    return dict(row) if row else None


def save_whatsapp_business_connection(
    user_id,
    business_id,
    waba_id,
    phone_number_id,
    phone_number,
    access_token
):
    connection = sqlite3.connect("notifications.db")
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO whatsapp_business_connections
        (user_id, business_id, waba_id, phone_number_id, phone_number, access_token)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            business_id = excluded.business_id,
            waba_id = excluded.waba_id,
            phone_number_id = excluded.phone_number_id,
            phone_number = excluded.phone_number,
            access_token = excluded.access_token,
            updated_at = CURRENT_TIMESTAMP
    """, (
        user_id,
        business_id,
        waba_id,
        phone_number_id,
        phone_number,
        access_token
    ))

    connection.commit()
    connection.close()


def meta_graph_url(path):
    return f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path.lstrip('/') }"


def exchange_embedded_signup_code(code, redirect_uri):
    """Exchange Meta Embedded Signup authorization code server-side.

    The redirect URI must be exactly the same value used in the manual
    Facebook OAuth dialog request.
    """
    if not META_APP_ID or not META_APP_SECRET:
        return {"error": "META_APP_ID or META_APP_SECRET is missing in .env"}

    params = {
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    }

    # With current Facebook Login for Business / Embedded Signup flows,
    # redirect_uri may be unavailable to the JS SDK. Only send it when the
    # caller actually has the exact URI used for the OAuth request.
    if redirect_uri:
        params["redirect_uri"] = redirect_uri

    response = requests.get(
        meta_graph_url("oauth/access_token"),
        params=params,
        timeout=30
    )

    try:
        data = response.json()
    except ValueError:
        return {"error": f"Meta returned HTTP {response.status_code}: {response.text}"}

    if response.status_code >= 400 or "access_token" not in data:
        return data

    return data


def get_meta_redirect_uri():
    """Build the public redirect URI seen by Meta through the tunnel."""
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    forwarded_host = request.headers.get("X-Forwarded-Host", request.host)
    forwarded_proto = forwarded_proto.split(",")[0].strip()
    forwarded_host = forwarded_host.split(",")[0].strip()
    if forwarded_proto not in {"http", "https"}:
        forwarded_proto = request.scheme
    return f"{forwarded_proto}://{forwarded_host}/"


def build_whatsapp_oauth_url():
    """Create a manual Facebook OAuth URL so redirect_uri is fully controlled."""
    state = secrets.token_urlsafe(32)
    redirect_uri = get_meta_redirect_uri()

    session["whatsapp_oauth_state"] = state
    session["whatsapp_oauth_redirect_uri"] = redirect_uri

    extras = json.dumps({"setup": {}, "sessionInfoVersion": "3"}, separators=(",", ":"))

    params = {
        "client_id": META_APP_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "whatsapp_business_management,whatsapp_business_messaging",
        "config_id": META_WHATSAPP_CONFIG_ID,
        "state": state,
        "extras": extras
    }

    oauth_version = META_GRAPH_VERSION or "v26.0"
    return f"https://www.facebook.com/{oauth_version}/dialog/oauth?" + urlencode(params)


def debug_meta_token(access_token):
    """Validate the customer token and read its granted WABA targets."""
    if not META_APP_ID or not META_APP_SECRET:
        return {"error": "Meta App credentials are missing."}

    app_access_token = f"{META_APP_ID}|{META_APP_SECRET}"

    response = requests.get(
        meta_graph_url("debug_token"),
        params={"input_token": access_token},
        headers={"Authorization": f"Bearer {app_access_token}"},
        timeout=30
    )

    try:
        data = response.json()
    except ValueError:
        return {"error": f"Meta returned HTTP {response.status_code}: {response.text}"}

    return data


def get_waba_phone_numbers(waba_id, access_token):
    response = requests.get(
        meta_graph_url(f"{waba_id}/phone_numbers"),
        params={
            "fields": "id,display_phone_number,verified_name"
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30
    )

    try:
        data = response.json()
    except ValueError:
        return {"error": f"Meta returned HTTP {response.status_code}: {response.text}"}

    if response.status_code >= 400:
        return data

    return data


def subscribe_app_to_waba(waba_id, access_token):
    """Subscribe this Meta app to the customer's WABA."""
    response = requests.post(
        meta_graph_url(f"{waba_id}/subscribed_apps"),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30
    )

    try:
        return response.json()
    except ValueError:
        return {"error": f"Meta returned HTTP {response.status_code}: {response.text}"}


def send_customer_whatsapp_message(connection, message):
    """Send a WhatsApp message using the customer's own Embedded Signup token."""
    phone_number_id = connection["phone_number_id"]
    access_token = connection["access_token"]

    response = requests.post(
        meta_graph_url(f"{phone_number_id}/messages"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        },
        json={
            "messaging_product": "whatsapp",
            "to": re.sub(r"\D", "", connection.get("phone_number") or ""),
            "type": "text",
            "text": {"body": message}
        },
        timeout=30
    )

    try:
        return response.json()
    except ValueError:
        return {"error": f"Meta returned HTTP {response.status_code}: {response.text}"}


@app.route("/whatsapp/embedded-signup/start")
def whatsapp_embedded_signup_start():
    """Start Embedded Signup using a manually controlled OAuth redirect."""
    if not is_logged_in():
        return redirect(url_for("login"))

    if not META_APP_ID or not META_APP_SECRET or not META_WHATSAPP_CONFIG_ID:
        return redirect(url_for("home", whatsapp_error="Meta configuration is incomplete."))

    oauth_url = build_whatsapp_oauth_url()
    print(f"🔐 Starting Meta OAuth with redirect URI: {session.get('whatsapp_oauth_redirect_uri')}")
    return redirect(oauth_url)


def complete_whatsapp_embedded_signup_from_code(code, waba_id="", phone_number_id="", business_id=""):
    """Finish Embedded Signup after Meta redirects back to the dashboard."""
    redirect_uri = session.get("whatsapp_oauth_redirect_uri") or get_meta_redirect_uri()
    token_data = exchange_embedded_signup_code(code, redirect_uri)

    if "error" in token_data or "access_token" not in token_data:
        return {"success": False, "step": "code_exchange", "error": token_data}

    customer_token = token_data["access_token"]
    debug_data = debug_meta_token(customer_token)
    debug_info = debug_data.get("data", {}) if isinstance(debug_data, dict) else {}

    if not waba_id:
        for scope in debug_info.get("granular_scopes", []):
            if scope.get("scope") == "whatsapp_business_management":
                targets = scope.get("target_ids") or []
                if targets:
                    waba_id = str(targets[0])
                    break

    # Meta's Embedded Signup session message normally gives us the WABA ID.
    # The manual OAuth fallback does not have that browser postMessage, so
    # discover the WABA server-side from the customer token as well.
    discovery_errors = []

    if not waba_id:
        discovery_endpoints = [
            (
                "me/whatsapp_business_accounts",
                {"fields": "id,name"}
            ),
            (
                "me/businesses",
                {"fields": "id,name,whatsapp_business_accounts{id,name}"}
            ),
        ]

        for endpoint, params in discovery_endpoints:
            try:
                waba_response = requests.get(
                    meta_graph_url(endpoint),
                    params=params,
                    headers={"Authorization": f"Bearer {customer_token}"},
                    timeout=30
                )
                try:
                    waba_data = waba_response.json()
                except ValueError:
                    waba_data = {}

                if waba_response.status_code >= 400:
                    discovery_errors.append({
                        "endpoint": endpoint,
                        "status": waba_response.status_code,
                        "error": waba_data
                    })
                    continue

                # /me/whatsapp_business_accounts returns {data:[...]}.
                accounts = waba_data.get("data", []) if isinstance(waba_data, dict) else []
                for account in accounts:
                    if account.get("id"):
                        waba_id = str(account["id"])
                        break

                if waba_id:
                    break

                # /me/businesses returns businesses; each business can contain
                # whatsapp_business_accounts when the granted token exposes them.
                if endpoint == "me/businesses":
                    for business in accounts:
                        nested = business.get("whatsapp_business_accounts", {})
                        nested_accounts = nested.get("data", []) if isinstance(nested, dict) else []
                        for account in nested_accounts:
                            if account.get("id"):
                                waba_id = str(account["id"])
                                business_id = business_id or str(business.get("id") or "")
                                break
                        if waba_id:
                            break

                if waba_id:
                    break

            except requests.RequestException as exc:
                discovery_errors.append({
                    "endpoint": endpoint,
                    "error": str(exc)
                })

    if not waba_id:
        print("❌ Could not discover WABA from customer token.")
        print("❌ WABA discovery details:", discovery_errors)
        return {
            "success": False,
            "step": "find_waba",
            "error": {
                "message": "Meta returned the authorization token, but no WhatsApp Business Account ID was discoverable from that token.",
                "discovery": discovery_errors
            }
        }

    phone_data = get_waba_phone_numbers(waba_id, customer_token)
    if "error" in phone_data:
        return {"success": False, "step": "phone_numbers", "error": phone_data}

    phone_numbers = phone_data.get("data", [])
    selected_phone = next((item for item in phone_numbers if str(item.get("id")) == str(phone_number_id)), None) if phone_number_id else (phone_numbers[0] if phone_numbers else None)

    if not selected_phone:
        return {"success": False, "step": "find_phone", "error": "No WhatsApp phone number was returned for this WABA."}

    phone_number_id = str(selected_phone["id"])
    display_phone_number = selected_phone.get("display_phone_number", "")

    subscribe_result = subscribe_app_to_waba(waba_id, customer_token)
    if isinstance(subscribe_result, dict) and "error" in subscribe_result:
        print("⚠️ WABA subscription warning:", subscribe_result)

    save_whatsapp_business_connection(
        user_id=session["user_id"],
        business_id=business_id or None,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        phone_number=display_phone_number,
        access_token=customer_token
    )

    session.pop("whatsapp_oauth_state", None)
    session.pop("whatsapp_oauth_redirect_uri", None)

    print(f"✅ WhatsApp Embedded Signup completed for user {session['user_id']}. WABA={waba_id}, Phone={phone_number_id}")
    return {"success": True, "message": "WhatsApp Business connected successfully.", "phone_number": display_phone_number, "waba_id": waba_id}


@app.route("/connect-whatsapp", methods=["POST"])
def connect_whatsapp():
    """Legacy manual number route. Embedded Signup is now the main flow."""
    if not is_logged_in():
        return redirect(url_for("login"))

    return redirect(url_for("home", whatsapp_error="Please use Connect WhatsApp Business."))


@app.route("/whatsapp/embedded-signup", methods=["POST"])
def whatsapp_embedded_signup():
    """Complete Meta Embedded Signup using the token + WABA IDs returned by the browser flow.

    For current Facebook Login for Business / WhatsApp Embedded Signup flows,
    the browser can return a short-lived customer access token while the
    WA_EMBEDDED_SIGNUP postMessage supplies the selected WABA and phone IDs.
    We accept both pieces and do not depend on server-side WABA discovery.
    """
    if not is_logged_in():
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    if not META_APP_ID or not META_APP_SECRET or not META_WHATSAPP_CONFIG_ID:
        return jsonify({
            "success": False,
            "error": "Meta configuration is incomplete. Check META_APP_ID, META_APP_SECRET and META_WHATSAPP_CONFIG_ID in .env."
        }), 500

    payload = request.get_json(silent=True) or {}

    access_token = (payload.get("access_token") or "").strip()
    code = (payload.get("code") or "").strip()
    waba_id = (payload.get("waba_id") or "").strip()
    phone_number_id = (payload.get("phone_number_id") or "").strip()
    business_id = (payload.get("business_id") or payload.get("businessId") or "").strip()

    # Prefer the access token returned by the Embedded Signup browser flow.
    # If only an authorization code is available, keep the old exchange as a
    # compatibility fallback.
    if not access_token and code:
        redirect_uri = (
            payload.get("redirect_uri")
            or session.get("whatsapp_oauth_redirect_uri")
            or ""
        ).strip()

        token_data = exchange_embedded_signup_code(code, redirect_uri)
        if "error" in token_data or "access_token" not in token_data:
            return jsonify({
                "success": False,
                "step": "code_exchange",
                "error": token_data
            }), 400

        access_token = token_data["access_token"]

    if not access_token:
        return jsonify({
            "success": False,
            "step": "token",
            "error": "Meta did not return an access token."
        }), 400

    try:
        # Validate the customer token and use granular target IDs only as a
        # fallback when the browser did not send a WABA ID.
        debug_data = debug_meta_token(access_token)
        debug_info = debug_data.get("data", {}) if isinstance(debug_data, dict) else {}

        if not debug_info.get("is_valid", True):
            return jsonify({
                "success": False,
                "step": "debug_token",
                "error": debug_data
            }), 400

        if not waba_id:
            for scope in debug_info.get("granular_scopes", []):
                if scope.get("scope") == "whatsapp_business_management":
                    targets = scope.get("target_ids") or []
                    if targets:
                        waba_id = str(targets[0])
                        break

        if not waba_id:
            return jsonify({
                "success": False,
                "step": "find_waba",
                "error": "Meta did not return a WhatsApp Business Account ID. Complete the Embedded Signup popup and try again.",
                "debug": {
                    "scopes": debug_info.get("scopes", []),
                    "granular_scopes": debug_info.get("granular_scopes", [])
                }
            }), 400

        phone_data = get_waba_phone_numbers(waba_id, access_token)
        if "error" in phone_data:
            return jsonify({
                "success": False,
                "step": "phone_numbers",
                "error": phone_data
            }), 400

        phone_numbers = phone_data.get("data", [])

        selected_phone = None
        if phone_number_id:
            selected_phone = next(
                (item for item in phone_numbers if str(item.get("id")) == str(phone_number_id)),
                None
            )

        if not selected_phone and phone_numbers:
            selected_phone = phone_numbers[0]

        if not selected_phone:
            return jsonify({
                "success": False,
                "step": "find_phone",
                "error": "No WhatsApp phone number was returned for this WABA."
            }), 400

        phone_number_id = str(selected_phone["id"])
        display_phone_number = selected_phone.get("display_phone_number", "")

        subscribe_result = subscribe_app_to_waba(waba_id, access_token)
        if isinstance(subscribe_result, dict) and "error" in subscribe_result:
            print("⚠️ WABA subscription warning:", subscribe_result)

        user_id = session["user_id"]

        save_whatsapp_business_connection(
            user_id=user_id,
            business_id=business_id or None,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            phone_number=display_phone_number,
            access_token=access_token
        )

        # Clear any old OAuth session state after a successful connection.
        session.pop("whatsapp_oauth_state", None)
        session.pop("whatsapp_oauth_redirect_uri", None)

        print(
            f"✅ WhatsApp Embedded Signup completed for user {user_id}. "
            f"WABA={waba_id}, Phone={phone_number_id}"
        )

        return jsonify({
            "success": True,
            "message": "WhatsApp Business connected successfully.",
            "phone_number": display_phone_number,
            "waba_id": waba_id
        })

    except requests.RequestException as e:
        print("❌ Meta API request error:", e)
        return jsonify({
            "success": False,
            "error": "Could not reach Meta. Please try again."
        }), 502
    except Exception as e:
        print("❌ Embedded Signup error:", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/whatsapp/connection")
def whatsapp_connection_status():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    connection = get_whatsapp_business_connection(session["user_id"])

    return jsonify({
        "success": True,
        "connected": bool(connection),
        "phone_number": connection.get("phone_number") if connection else None,
        "waba_id": connection.get("waba_id") if connection else None
    })


# ==============================
# GMAIL OAUTH
# ==============================


# ==============================

@app.route("/connect-gmail")
def connect_gmail():

    if not is_logged_in():
        return redirect(url_for("login"))

    # Generate Google OAuth URL + state + PKCE code verifier
    authorization_url, state, code_verifier = get_google_authorization_url()

    # Save BOTH OAuth state and PKCE code verifier in the
    # logged-in user's Flask session. Google requires the
    # same code verifier when the callback exchanges the code.
    session["google_oauth_state"] = state
    session["google_oauth_code_verifier"] = code_verifier

    return redirect(authorization_url)


@app.route("/gmail/callback")
def gmail_callback():

    if not is_logged_in():
        return redirect(url_for("login"))

    try:

        state = session.get("google_oauth_state")
        code_verifier = session.get("google_oauth_code_verifier")

        if not state:
            return """
            <h2>Gmail Connection Error</h2>
            <p>OAuth session expired. Please try again.</p>
            <a href="/">Back to Dashboard</a>
            """

        if not code_verifier:
            return """
            <h2>Gmail Connection Error</h2>
            <p>OAuth code verifier is missing. Please click Connect Gmail and try again.</p>
            <a href="/">Back to Dashboard</a>
            """

        # Complete Google OAuth using the SAME PKCE code verifier
        # that was generated before redirecting to Google.
        credentials = complete_google_oauth(
            state=state,
            authorization_response=request.url,
            code_verifier=code_verifier
        )

        # Current logged-in user
        user_id = session["user_id"]

        # Save Gmail connection
        result = save_user_gmail_connection(
            user_id=user_id,
            credentials=credentials
        )

        # OAuth data is no longer needed after token exchange
        session.pop("google_oauth_state", None)
        session.pop("google_oauth_code_verifier", None)

        if result.get("success"):

            return redirect(
                url_for(
                    "home",
                    gmail_connected="1"
                )
            )

        return f"""
        <h2>Gmail Connection Failed</h2>
        <p>{result.get("error")}</p>
        <a href="/">Back to Dashboard</a>
        """

    except Exception as e:

        session.pop("google_oauth_state", None)
        session.pop("google_oauth_code_verifier", None)

        return f"""
        <h2>Gmail Connection Error</h2>
        <p>{str(e)}</p>
        <a href="/">Back to Dashboard</a>
        """


# -----------------------------------
# GET EMAIL BODY
# -----------------------------------

def get_email_body(payload):

    # -----------------------------------
    # SIMPLE EMAIL BODY
    # -----------------------------------

    if payload.get("body", {}).get("data"):

        data = payload["body"]["data"]

        try:

            return base64.urlsafe_b64decode(
                data.encode("UTF-8")
            ).decode(
                "UTF-8",
                errors="ignore"
            )

        except Exception as e:

            print("❌ Body decode error:", e)


    # -----------------------------------
    # MULTIPART EMAIL
    # -----------------------------------

    if "parts" in payload:

        # First preference: text/plain

        for part in payload["parts"]:

            if part.get("mimeType") == "text/plain":

                data = part.get("body", {}).get("data")

                if data:

                    try:

                        return base64.urlsafe_b64decode(
                            data.encode("UTF-8")
                        ).decode(
                            "UTF-8",
                            errors="ignore"
                        )

                    except Exception as e:

                        print("❌ Plain text decode error:", e)


            # -----------------------------------
            # NESTED PARTS
            # -----------------------------------

            if "parts" in part:

                for subpart in part["parts"]:

                    if subpart.get("mimeType") == "text/plain":

                        data = subpart.get(
                            "body",
                            {}
                        ).get("data")

                        if data:

                            try:

                                return base64.urlsafe_b64decode(
                                    data.encode("UTF-8")
                                ).decode(
                                    "UTF-8",
                                    errors="ignore"
                                )

                            except Exception as e:

                                print(
                                    "❌ Nested body decode error:",
                                    e
                                )


        # -----------------------------------
        # SECOND PREFERENCE: HTML
        # -----------------------------------

        for part in payload["parts"]:

            if part.get("mimeType") == "text/html":

                data = part.get("body", {}).get("data")

                if data:

                    try:

                        html_body = base64.urlsafe_b64decode(
                            data.encode("UTF-8")
                        ).decode(
                            "UTF-8",
                            errors="ignore"
                        )

                        return html_body

                    except Exception as e:

                        print(
                            "❌ HTML body decode error:",
                            e
                        )


    return "No email content found."


# -----------------------------------
# GET LATEST EMAIL
# -----------------------------------

def get_latest_email(user_id):

    service = get_user_gmail_service(user_id)

    if service is None:
        return None


    results = service.users().messages().list(
        userId="me",
        maxResults=1
    ).execute()


    messages = results.get("messages", [])


    if not messages:

        return None


    message_id = messages[0]["id"]


    # IMPORTANT:
    # format="full" gets complete email
    message = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full"
    ).execute()


    headers = message["payload"].get(
        "headers",
        []
    )


    sender = ""
    subject = ""
    date = ""


    # -----------------------------------
    # GET EMAIL HEADERS
    # -----------------------------------

    for header in headers:

        if header["name"] == "From":

            sender = header["value"]


        elif header["name"] == "Subject":

            subject = header["value"]


        elif header["name"] == "Date":

            date = header["value"]


    # -----------------------------------
    # GET EMAIL BODY
    # -----------------------------------

    body = get_email_body(
        message["payload"]
    )


    return {

        "id": message_id,

        "sender": sender,

        "subject": subject,

        "date": date,

        "body": body

    }


# -----------------------------------
# EMAIL MONITORING SERVICE
# -----------------------------------

def email_monitor():
    global last_email_ids

    print("📧 Multi-user email monitoring started automatically!")

    try:
        initialize_processed_emails_table()
    except Exception as e:
        print("❌ Could not initialize email-processing table:", e)
        return

    # -----------------------------------
    # SET BASELINE FOR ALL CONNECTED USERS
    # -----------------------------------

    try:
        connections = get_all_gmail_connections()

        if not connections:
            print("📭 No Gmail users connected yet.")
        else:
            for connection in connections:
                user_id = connection["user_id"]
                google_email = connection["google_email"]

                try:
                    email = get_latest_email(user_id)

                    if email:
                        last_email_ids[user_id] = email["id"]

                        print(
                            f"📌 Baseline saved for user {user_id}: "
                            f"{google_email}"
                        )
                    else:
                        print(
                            f"📭 No email found for user {user_id}: "
                            f"{google_email}"
                        )

                except Exception as e:
                    print(
                        f"❌ Gmail error for user {user_id} "
                        f"({google_email}): {e}"
                    )

            print("📌 Monitoring new emails for all connected users...")

    except Exception as e:
        print("❌ Could not load Gmail connections:", e)

    # -----------------------------------
    # CONTINUOUS EMAIL MONITORING
    # -----------------------------------

    while True:

        try:
            connections = get_all_gmail_connections()

            if not connections:
                print("📭 No connected Gmail users.")
                time.sleep(10)
                continue

            for connection in connections:

                user_id = connection["user_id"]
                google_email = connection["google_email"]

                try:
                    email = get_latest_email(user_id)

                    if not email:
                        print(
                            f"📭 No email found for user {user_id}: "
                            f"{google_email}"
                        )
                        continue

                    email_id = email["id"]

                    # First observation after a connection/restart becomes
                    # this user's baseline.
                    if user_id not in last_email_ids:
                        last_email_ids[user_id] = email_id

                        print(
                            f"📌 Baseline created for user {user_id}: "
                            f"{google_email}"
                        )
                        continue

                    if email_id == last_email_ids[user_id]:
                        continue

                    # Claim separately per user + Gmail message ID.
                    with monitor_lock:
                        claimed = claim_email_for_processing(
                            user_id,
                            email_id
                        )

                    if not claimed:
                        print(
                            f"⏭️ Email already processed for user {user_id}. "
                            f"Skipping."
                        )
                        last_email_ids[user_id] = email_id
                        continue

                    last_email_ids[user_id] = email_id

                    print("\n📧 New Email Received")
                    print("👤 User ID:", user_id)
                    print("📬 Gmail:", google_email)
                    print("From:", email["sender"])
                    print("Subject:", email["subject"])
                    print("Body:", email["body"])

                    whatsapp_connection = get_whatsapp_business_connection(user_id)

                    if not whatsapp_connection:
                        print(
                            f"⚠️ No WhatsApp Business connection for user "
                            f"{user_id}. Notification skipped."
                        )

                        save_notification(
                            user_id,
                            email["sender"],
                            email["subject"],
                            email["date"],
                            "Failed"
                        )

                        mark_email_processed(
                            user_id,
                            email_id,
                            "failed"
                        )

                        continue

                    whatsapp_number = whatsapp_connection.get("phone_number") or "Connected WhatsApp"

                    whatsapp_message = f"""📧 New Email Received

From: {email['sender']}

Subject: {email['subject']}

📩 Message:

{email['body']}

Date: {email['date']}
"""

                    print(
                        f"📱 Sending WhatsApp message to "
                        f"{whatsapp_number}..."
                    )

                    result = send_customer_whatsapp_message(
                        whatsapp_connection,
                        whatsapp_message
                    )

                    print("📱 WhatsApp API Response:")
                    print(result)

                    if "error" not in result:

                        save_notification(
                            user_id,
                            email["sender"],
                            email["subject"],
                            email["date"],
                            "Sent"
                        )

                        mark_email_processed(
                            user_id,
                            email_id,
                            "sent"
                        )

                        print(
                            f"✅ WhatsApp notification sent for user "
                            f"{user_id}!"
                        )
                        print("✅ Notification saved in database.")

                    else:

                        save_notification(
                            user_id,
                            email["sender"],
                            email["subject"],
                            email["date"],
                            "Failed"
                        )

                        mark_email_processed(
                            user_id,
                            email_id,
                            "failed"
                        )

                        print(
                            f"❌ WhatsApp message failed for user "
                            f"{user_id}!"
                        )

                except Exception as e:
                    print(
                        f"❌ Error processing user {user_id} "
                        f"({google_email}): {e}"
                    )

        except Exception as e:
            print("❌ Multi-user monitoring error:", e)

        time.sleep(10)


# -----------------------------------
# START BACKGROUND SERVICE
# -----------------------------------

def start_background_service():

    global monitor_started

    if monitor_started:
        print("ℹ️ Background automation is already running.")
        return

    monitor_started = True

    thread = threading.Thread(

        target=email_monitor,

        daemon=True

    )


    thread.start()


    print(
        "🚀 Background automation started!"
    )


# -----------------------------------
# HOME PAGE
# -----------------------------------

@app.route("/")
def home():

    if not is_logged_in():
        return redirect(url_for("login"))

    meta_code = (request.args.get("code") or "").strip()
    meta_state = (request.args.get("state") or "").strip()

    if meta_code:
        expected_state = session.get("whatsapp_oauth_state", "")
        if not expected_state or meta_state != expected_state:
            session.pop("whatsapp_oauth_state", None)
            session.pop("whatsapp_oauth_redirect_uri", None)
            return redirect(url_for("home", whatsapp_error="Meta OAuth state validation failed. Please try again."))

        try:
            result = complete_whatsapp_embedded_signup_from_code(meta_code)
        except requests.RequestException as e:
            print("❌ Meta API request error:", e)
            result = {"success": False, "error": "Could not reach Meta. Please try again."}
        except Exception as e:
            print("❌ Embedded Signup callback error:", e)
            result = {"success": False, "error": str(e)}

        if result.get("success"):
            return redirect(url_for("home", whatsapp_connected="1"))

        error_value = result.get("error", "WhatsApp connection failed.")
        if isinstance(error_value, dict):
            error_value = error_value.get("error", error_value)
        if isinstance(error_value, dict):
            error_value = error_value.get("message", str(error_value))
        session.pop("whatsapp_oauth_state", None)
        session.pop("whatsapp_oauth_redirect_uri", None)
        return redirect(url_for("home", whatsapp_error=str(error_value)))

    if request.args.get("error"):
        session.pop("whatsapp_oauth_state", None)
        session.pop("whatsapp_oauth_redirect_uri", None)
        return redirect(url_for("home", whatsapp_error=request.args.get("error_description") or request.args.get("error")))

    user_id = session["user_id"]

    notifications = get_notifications(user_id)
    stats = get_notification_stats(user_id)

    # Get the Gmail and WhatsApp connections for the current user.
    gmail_connection = get_gmail_connection(user_id)
    whatsapp_connection = get_whatsapp_business_connection(user_id)

    return render_template(
        "index.html",
        notifications=notifications,
        stats=stats,
        automation_running=True,
        gmail_connection=gmail_connection,
        whatsapp_connection=whatsapp_connection,
        meta_app_id=META_APP_ID,
        meta_whatsapp_config_id=META_WHATSAPP_CONFIG_ID
    )


# -----------------------------------
# SYSTEM STATUS API
# -----------------------------------

@app.route("/status")
def status():

    if not is_logged_in():
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]

    gmail_connection = get_gmail_connection(user_id)
    whatsapp_connection = get_whatsapp_connection(user_id)

    return jsonify({
        "gmail": "Connected" if gmail_connection else "Not Connected",
        "whatsapp": "Connected" if whatsapp_connection else "Not Connected",
        "automation": "Running"
    })


# -----------------------------------
# NOTIFICATIONS API
# -----------------------------------

@app.route("/notifications")
def notifications():

    if not is_logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    user_id = session["user_id"]

    notifications = get_notifications(user_id)

    data = []

    for notification in notifications:
        data.append({
            "id": notification["id"],
            "sender": notification["sender"],
            "subject": notification["subject"],
            "email_date": notification["email_date"],
            "whatsapp_status": notification["whatsapp_status"],
            "created_at": notification["created_at"]
        })

    return jsonify(data)


# -----------------------------------
# MAIN
# -----------------------------------

if __name__ == "__main__":

    initialize_whatsapp_business_table()

    # Start Email Monitoring Automatically

    start_background_service()


    # Start Flask Server

    # Meta Facebook Login / Embedded Signup requires HTTPS.
    # ssl_context="adhoc" creates a temporary local development certificate.
    app.run(
        debug=True,
        use_reloader=False,
        host="127.0.0.1",
        port=5000,
        ssl_context="adhoc"
    )