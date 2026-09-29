import sqlite3

DATABASE = "notifications.db"


connection = sqlite3.connect(DATABASE)
cursor = connection.cursor()

# Existing users check karo
cursor.execute("""
    SELECT id, name, email
    FROM users
    ORDER BY id
""")

users = cursor.fetchall()

print("\n👤 Registered Users:\n")

for user in users:
    print(
        f"ID: {user[0]} | "
        f"Name: {user[1]} | "
        f"Email: {user[2]}"
    )

if not users:
    print("❌ No users found.")
    connection.close()
    exit()

print("\n⚠️ Existing notifications ko kis user ke account mein attach karna hai?")
user_id = input("User ID enter karo: ").strip()

if not user_id.isdigit():
    print("❌ Invalid User ID.")
    connection.close()
    exit()

user_id = int(user_id)

# User exist karta hai ya nahi
cursor.execute("""
    SELECT id, name, email
    FROM users
    WHERE id = ?
""", (user_id,))

user = cursor.fetchone()

if not user:
    print("❌ User ID not found.")
    connection.close()
    exit()

# Sirf old notifications jinka user_id NULL hai
cursor.execute("""
    UPDATE notifications
    SET user_id = ?
    WHERE user_id IS NULL
""", (user_id,))

updated = cursor.rowcount

connection.commit()
connection.close()

print("\n✅ Migration completed!")
print(f"👤 User: {user[1]} ({user[2]})")
print(f"📧 Notifications attached: {updated}")