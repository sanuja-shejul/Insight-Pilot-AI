
import os
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "indira_foods")
}


def get_db_connection():
    try:
        connection = mysql.connector.connect(**DB_CONFIG)

        if connection.is_connected():
            return connection

        connection.close()
        return None

    except Error as error:
        print("MySQL connection error:", error)
        return None


def create_user(username, password_hash):
    connection = get_db_connection()

    if connection is None:
        return False, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor()

        query = """
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
        """

        cursor.execute(query, (username, password_hash))
        connection.commit()

        return True, "User created successfully."

    except mysql.connector.IntegrityError:
        return False, "Username already exists."

    except Error as error:
        print("Create user error:", error)
        return False, "Unable to create user. Check the terminal."

    finally:
        if cursor:
            cursor.close()
        connection.close()


def get_user_by_username(username):
    connection = get_db_connection()

    if connection is None:
        return None

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT *
            FROM users
            WHERE username = %s
            LIMIT 1
        """

        cursor.execute(query, (username,))
        return cursor.fetchone()

    except Error as error:
        print("Find user error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def get_inventory():
    connection = get_db_connection()

    if connection is None:
        return None

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.unit,
                p.selling_price,
                p.minimum_stock,
                COALESCE(i.quantity, 0) AS current_stock
            FROM products AS p
            LEFT JOIN inventory AS i
                ON p.id = i.product_id
            ORDER BY p.id
        """

        cursor.execute(query)
        return cursor.fetchall()

    except Error as error:
        print("Get inventory error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()
        
def add_stock(product_id, quantity_to_add):
    """
    Add incoming packets to the existing stock quantity.
    If the product has no inventory row yet, create one.
    """
    connection = get_db_connection()

    if connection is None:
        return False, "Unable to connect to the database."

    cursor = None

    try:
        cursor = connection.cursor()

        query = """
            INSERT INTO inventory (product_id, quantity)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                quantity = quantity + %s
        """

        cursor.execute(
            query,
            (product_id, quantity_to_add, quantity_to_add)
        )

        connection.commit()
        return True, "Stock updated successfully."

    except Error as error:
        connection.rollback()
        print("Add stock error:", error)
        return False, "Unable to update stock. Check the terminal."

    finally:
        if cursor:
            cursor.close()
        connection.close()
        
from decimal import Decimal, ROUND_HALF_UP


def get_active_products():
    """Return active products and their selling prices."""
    connection = get_db_connection()
    if connection is None:
        return None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
    SELECT
        p.id,
        p.product_name,
        p.category,
        p.unit,
        p.selling_price,
        COALESCE(i.quantity, 0) AS current_stock
    FROM products AS p
    LEFT JOIN inventory AS i ON i.product_id = p.id
    WHERE p.is_active = 1
    ORDER BY p.product_name
""")
        return cursor.fetchall()

    except Error as error:
        print("Get active products error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def get_customers():
    """Return customers for the sale form."""
    connection = get_db_connection()
    if connection is None:
        return None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, customer_name, phone, customer_type
            FROM customers
            ORDER BY customer_name
        """)
        return cursor.fetchall()

    except Error as error:
        print("Get customers error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def create_sale(customer_id, payment_method, discount, items, created_by):
    """
    Save a sale and reduce inventory in a single transaction.

    items format:
    [{"product_id": 1, "quantity": 2}, ...]

    Returns:
    (success, message, sale_id)
    """
    allowed_payments = {"Cash", "UPI", "Bank Transfer", "Other"}

    if payment_method not in allowed_payments:
        return False, "Please select a valid payment method.", None

    try:
        discount = Decimal(str(discount)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except Exception:
        return False, "Enter a valid discount.", None

    if not discount.is_finite() or discount < 0:
        return False, "Discount cannot be negative.", None

    if not items:
        return False, "Add at least one product to the bill.", None

    # Combine duplicate product rows and validate quantities.
    combined_items = {}
    try:
        for item in items:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])

            if product_id <= 0 or quantity <= 0:
                return False, "Product and quantity must be valid.", None

            combined_items[product_id] = (
                combined_items.get(product_id, 0) + quantity
            )
    except (KeyError, TypeError, ValueError):
        return False, "Invalid product or quantity.", None

    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed.", None

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()

        # Validate the selected customer.
        if customer_id not in (None, ""):
            cursor.execute(
                "SELECT id FROM customers WHERE id = %s FOR UPDATE",
                (int(customer_id),)
            )
            if cursor.fetchone() is None:
                raise ValueError("The selected customer does not exist.")
            customer_id = int(customer_id)
        else:
            customer_id = None

        # Lock stock rows, validate availability and calculate prices.
        sale_lines = []
        subtotal = Decimal("0.00")

        for product_id, quantity in sorted(combined_items.items()):
            cursor.execute("""
                SELECT id, product_name, selling_price, is_active
                FROM products
                WHERE id = %s
                FOR UPDATE
            """, (product_id,))
            product = cursor.fetchone()

            if not product or not product["is_active"]:
                raise ValueError(
                    f"Product ID {product_id} is unavailable."
                )

            cursor.execute("""
                SELECT quantity
                FROM inventory
                WHERE product_id = %s
                FOR UPDATE
            """, (product_id,))
            stock = cursor.fetchone()

            available = stock["quantity"] if stock else 0

            if quantity > available:
                raise ValueError(
                    f"Insufficient stock for {product['product_name']}. "
                    f"Available: {available}, requested: {quantity}."
                )

            unit_price = Decimal(str(product["selling_price"])).quantize(
                Decimal("0.01")
            )
            line_total = (unit_price * quantity).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            subtotal += line_total

            sale_lines.append({
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": line_total,
            })

        subtotal = subtotal.quantize(Decimal("0.01"))
        if discount > subtotal:
            raise ValueError("Discount cannot exceed the subtotal.")

        grand_total = (subtotal - discount).quantize(Decimal("0.01"))

        # Save the bill header. Its generated ID identifies the bill.
        cursor.execute("""
            INSERT INTO sales (
                customer_id, sale_date, subtotal, discount,
                grand_total, payment_method, created_by
            )
            VALUES (%s, CURDATE(), %s, %s, %s, %s, %s)
        """, (
            customer_id, subtotal, discount,
            grand_total, payment_method, created_by
        ))

        sale_id = cursor.lastrowid

        # Save each line and deduct the corresponding stock.
        for line in sale_lines:
            cursor.execute("""
                INSERT INTO sale_items (
                    sale_id, product_id, quantity,
                    unit_price, total_price
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                sale_id,
                line["product_id"],
                line["quantity"],
                line["unit_price"],
                line["total_price"],
            ))

            cursor.execute("""
                UPDATE inventory
                SET quantity = quantity - %s
                WHERE product_id = %s AND quantity >= %s
            """, (
                line["quantity"],
                line["product_id"],
                line["quantity"],
            ))

            if cursor.rowcount != 1:
                raise ValueError(
                    "Stock changed while processing the sale. "
                    "Please try again."
                )

        connection.commit()
        return True, "Sale completed and stock updated.", sale_id

    except (ValueError, TypeError) as error:
        connection.rollback()
        return False, str(error), None

    except Error as error:
        connection.rollback()
        print("Create sale error:", error)
        return False, "Sale could not be saved. Check the terminal.", None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def get_sales_history():
    """Return the latest 200 sales."""
    connection = get_db_connection()
    if connection is None:
        return None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                s.id,
                s.sale_date,
                s.subtotal,
                s.discount,
                s.grand_total,
                s.payment_method,
                c.customer_name,
                u.username AS created_by_username
            FROM sales AS s
            LEFT JOIN customers AS c ON c.id = s.customer_id
            LEFT JOIN users AS u ON u.id = s.created_by
            ORDER BY s.id DESC
            LIMIT 200
        """)
        return cursor.fetchall()

    except Error as error:
        print("Sales history error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def get_sale_details(sale_id):
    """Return a bill and its product lines."""
    connection = get_db_connection()
    if connection is None:
        return None, None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                s.id,
                s.sale_date,
                s.subtotal,
                s.discount,
                s.grand_total,
                s.payment_method,
                c.customer_name,
                c.phone,
                c.address,
                u.username AS created_by_username
            FROM sales AS s
            LEFT JOIN customers AS c ON c.id = s.customer_id
            LEFT JOIN users AS u ON u.id = s.created_by
            WHERE s.id = %s
        """, (sale_id,))
        sale = cursor.fetchone()

        if not sale:
            return None, None

        cursor.execute("""
            SELECT
                p.product_name,
                p.unit,
                si.quantity,
                si.unit_price,
                si.total_price
            FROM sale_items AS si
            JOIN products AS p ON p.id = si.product_id
            WHERE si.sale_id = %s
            ORDER BY si.id
        """, (sale_id,))
        items = cursor.fetchall()

        return sale, items

    except Error as error:
        print("Sale details error:", error)
        return None, None

    finally:
        if cursor:
            cursor.close()
        connection.close()