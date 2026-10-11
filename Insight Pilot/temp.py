
from werkzeug.security import generate_password_hash
from database import get_db_connection

username = "admin"
new_password = input("Enter your new password: ")

if len(new_password) < 6:
    print("Password must contain at least 6 characters.")
else:
    password_hash = generate_password_hash(new_password)
    connection = get_db_connection()

    if connection is None:
        print("Database connection failed.")
    else:
        cursor = None

        try:
            cursor = connection.cursor()

            query = """
                UPDATE users
                SET password_hash = %s
                WHERE username = %s
            """

            cursor.execute(query, (password_hash, username))
            connection.commit()

            if cursor.rowcount == 1:
                print("Password reset successfully for admin.")
            else:
                print("Username admin was not found.")

        except Exception as error:
            print("Error:", error)

        finally:
            if cursor:
                cursor.close()
            connection.close()