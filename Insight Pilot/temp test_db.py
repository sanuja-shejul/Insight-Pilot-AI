from database import get_db_connection

connection = get_db_connection()

if connection:
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE(), CURRENT_USER()")
        print("Connected successfully!")
        print(cursor.fetchone())
        cursor.close()
    finally:
        connection.close()
else:
    print("Connection failed. Check your .env settings.")