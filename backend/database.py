import sqlite3

DATABASE = "notifications.db"


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_connection():
    return sqlite3.connect(DATABASE)


# ==========================================
# USERS TABLE
# ==========================================

def create_users_table():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()


# ==========================================
# NOTIFICATIONS TABLE
# ==========================================

def create_table():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            sender TEXT,
            subject TEXT,
            email_date TEXT,
            whatsapp_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()


# ==========================================
# SAVE NOTIFICATION
# ==========================================

def save_notification(
    user_id,
    sender,
    subject,
    email_date,
    whatsapp_status
):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO notifications
        (
            user_id,
            sender,
            subject,
            email_date,
            whatsapp_status
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        sender,
        subject,
        email_date,
        whatsapp_status
    ))

    connection.commit()
    connection.close()


# ==========================================
# GET USER NOTIFICATIONS
# ==========================================

def get_notifications(user_id):

    connection = get_connection()
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            sender,
            subject,
            email_date,
            whatsapp_status,
            created_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))

    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]


# ==========================================
# NOTIFICATION STATS
# ==========================================

def get_notification_stats(user_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ?
    """, (user_id,))

    total = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ?
        AND whatsapp_status = 'sent'
    """, (user_id,))

    sent = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ?
        AND whatsapp_status != 'sent'
    """, (user_id,))

    failed = cursor.fetchone()[0]

    connection.close()

    return {
        "total": total,
        "sent": sent,
        "failed": failed
    }


# ==========================================
# REGISTER USER
# ==========================================

def register_user(name, email, password_hash):

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            INSERT INTO users
            (name, email, password_hash)
            VALUES (?, ?, ?)
        """, (
            name,
            email,
            password_hash
        ))

        connection.commit()

        return True

    except sqlite3.IntegrityError:

        return False

    finally:

        connection.close()


# ==========================================
# GET USER BY EMAIL
# ==========================================

def get_user_by_email(email):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            password_hash
        FROM users
        WHERE email = ?
    """, (email,))

    row = cursor.fetchone()

    connection.close()

    if row:

        return {
            "id": row[0],
            "name": row[1],
            "email": row[2],
            "password_hash": row[3]
        }

    return None


# ==========================================
# ADD USER ID TO NOTIFICATIONS
# ==========================================

def add_user_id_to_notifications():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        PRAGMA table_info(notifications)
    """)

    columns = [row[1] for row in cursor.fetchall()]

    if "user_id" not in columns:

        cursor.execute("""
            ALTER TABLE notifications
            ADD COLUMN user_id INTEGER
        """)

        connection.commit()

    connection.close()


# ==========================================
# GMAIL CONNECTIONS TABLE
# ==========================================

def create_gmail_connections_table():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gmail_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            google_email TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            token_expiry TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()


# ==========================================
# SAVE GMAIL CONNECTION
# ==========================================

def save_gmail_connection(
    user_id,
    google_email,
    access_token,
    refresh_token,
    token_expiry
):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO gmail_connections
        (
            user_id,
            google_email,
            access_token,
            refresh_token,
            token_expiry
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            google_email = excluded.google_email,
            access_token = excluded.access_token,
            refresh_token = excluded.refresh_token,
            token_expiry = excluded.token_expiry
    """, (
        user_id,
        google_email,
        access_token,
        refresh_token,
        token_expiry
    ))

    connection.commit()
    connection.close()


# ==========================================
# GET GMAIL CONNECTION
# ==========================================

def get_gmail_connection(user_id):

    connection = get_connection()
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            google_email,
            access_token,
            refresh_token,
            token_expiry,
            created_at
        FROM gmail_connections
        WHERE user_id = ?
    """, (user_id,))

    row = cursor.fetchone()

    connection.close()

    if row:
        return dict(row)

    return None


# ==========================================
# GET ALL GMAIL CONNECTIONS
# ==========================================

def get_all_gmail_connections():

    connection = get_connection()
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            google_email,
            access_token,
            refresh_token,
            token_expiry,
            created_at
        FROM gmail_connections
        ORDER BY id ASC
    """)

    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]


# ==========================================
# DELETE GMAIL CONNECTION
# ==========================================

def delete_gmail_connection(user_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM gmail_connections
        WHERE user_id = ?
    """, (user_id,))

    connection.commit()
    connection.close()


# ==========================================
# WHATSAPP CONNECTIONS TABLE
# ==========================================

def create_whatsapp_connections_table():

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            phone_number TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()

    print("WhatsApp connections table created successfully.")


# ==========================================
# SAVE / UPDATE WHATSAPP NUMBER
# ==========================================

def save_whatsapp_connection(user_id, phone_number):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO whatsapp_connections
        (
            user_id,
            phone_number
        )
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            phone_number = excluded.phone_number,
            updated_at = CURRENT_TIMESTAMP
    """, (
        user_id,
        phone_number
    ))

    connection.commit()
    connection.close()


# ==========================================
# GET USER WHATSAPP CONNECTION
# ==========================================

def get_whatsapp_connection(user_id):

    connection = get_connection()
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            phone_number,
            created_at,
            updated_at
        FROM whatsapp_connections
        WHERE user_id = ?
    """, (user_id,))

    row = cursor.fetchone()

    connection.close()

    if row:
        return dict(row)

    return None


# ==========================================
# GET ALL WHATSAPP CONNECTIONS
# ==========================================

def get_all_whatsapp_connections():

    connection = get_connection()
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            user_id,
            phone_number,
            created_at,
            updated_at
        FROM whatsapp_connections
        ORDER BY id ASC
    """)

    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]


# ==========================================
# DELETE WHATSAPP CONNECTION
# ==========================================

def delete_whatsapp_connection(user_id):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM whatsapp_connections
        WHERE user_id = ?
    """, (user_id,))

    connection.commit()
    connection.close()


# ==========================================
# INITIALIZE DATABASE
# ==========================================

def initialize_database():

    create_users_table()

    create_table()

    add_user_id_to_notifications()

    create_gmail_connections_table()

    create_whatsapp_connections_table()


# ==========================================
# RUN DATABASE INITIALIZATION
# ==========================================

if __name__ == "__main__":

    initialize_database()

    print("Database initialized successfully! ✅")