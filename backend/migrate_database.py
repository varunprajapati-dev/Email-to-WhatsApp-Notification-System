from database import (
    add_user_id_to_notifications,
    create_gmail_connections_table
)

add_user_id_to_notifications()
create_gmail_connections_table()

print("Database migration completed! ✅")