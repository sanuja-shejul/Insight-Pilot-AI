import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "indira_foods"),
}


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection():
    """Return an open MySQL connection, or None if connection fails."""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        if connection.is_connected():
            return connection
        connection.close()
        return None
    except Error as error:
        print("MySQL connection error:", error)
        return None


def _close_db(cursor=None, connection=None):
    """Safely close a cursor and connection."""
    if cursor is not None:
        try:
            cursor.close()
        except Error:
            pass
    if connection is not None:
        try:
            connection.close()
        except Error:
            pass


def _money(value):
    """Convert a numeric value to a two-decimal Decimal."""
    try:
        return Decimal(str(value or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


# =========================================================
# USERS
# =========================================================

def create_user(username, password_hash, email=None, full_name=None, role="Owner"):
    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, email, password_hash, full_name, role)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (username, email, password_hash, full_name, role),
        )
        connection.commit()
        return True, "User created successfully."
    except mysql.connector.IntegrityError:
        connection.rollback()
        return False, "Username or email already exists."
    except Error as error:
        connection.rollback()
        print("Create user error:", error)
        return False, "Unable to create user. Check the terminal."
    finally:
        _close_db(cursor, connection)


def get_user_by_username(username):
    connection = get_db_connection()
    if connection is None:
        return None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE username = %s
            LIMIT 1
            """,
            (username,),
        )
        return cursor.fetchone()
    except Error as error:
        print("Find user error:", error)
        return None
    finally:
        _close_db(cursor, connection)


# =========================================================
# INVENTORY AND STOCK HISTORY
# =========================================================

def get_inventory():
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                p.id AS product_id,
                p.id,
                p.product_name,
                p.category,
                p.unit,
                p.selling_price,
                p.minimum_stock,
                p.is_active,
                COALESCE(i.quantity, 0) AS quantity,
                COALESCE(i.quantity, 0) AS current_stock,
                i.updated_at
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = 1
            ORDER BY p.product_name
            """
        )
        return cursor.fetchall()
    except Error as error:
        print("Get inventory error:", error)
        return []
    finally:
        _close_db(cursor, connection)


def add_stock(product_id, quantity_to_add, created_by=None):
    try:
        quantity_to_add = int(quantity_to_add)
        product_id = int(product_id)
    except (TypeError, ValueError):
        return False, "Product and quantity must be valid numbers."

    if quantity_to_add <= 0:
        return False, "Quantity to add must be greater than zero."

    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT id FROM products WHERE id = %s AND is_active = 1 FOR UPDATE",
            (product_id,),
        )
        product = cursor.fetchone()
        if not product:
            connection.rollback()
            return False, "Product not found or inactive."

        cursor.execute(
            "SELECT quantity FROM inventory WHERE product_id = %s FOR UPDATE",
            (product_id,),
        )
        inventory_row = cursor.fetchone()
        stock_before = int(inventory_row["quantity"]) if inventory_row else 0
        stock_after = stock_before + quantity_to_add

        if inventory_row:
            cursor.execute(
                """
                UPDATE inventory
                SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = %s
                """,
                (stock_after, product_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO inventory (product_id, quantity)
                VALUES (%s, %s)
                """,
                (product_id, stock_after),
            )

        cursor.execute(
            """
            INSERT INTO stock_history
                (product_id, movement_type, quantity_change,
                 stock_before, stock_after, notes, created_by)
            VALUES (%s, 'Stock In', %s, %s, %s, %s, %s)
            """,
            (
                product_id,
                quantity_to_add,
                stock_before,
                stock_after,
                "Stock added through Add Stock",
                created_by,
            ),
        )

        connection.commit()
        return True, "Stock added successfully."
    except Error as error:
        connection.rollback()
        print("Add stock error:", error)
        return False, "Unable to add stock. Check the terminal."
    finally:
        _close_db(cursor, connection)


def get_active_products():
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                p.id, p.product_name, p.category, p.unit,
                p.selling_price, p.minimum_stock,
                COALESCE(i.quantity, 0) AS quantity
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = 1
            ORDER BY p.product_name
            """
        )
        return cursor.fetchall()
    except Error as error:
        print("Get active products error:", error)
        return []
    finally:
        _close_db(cursor, connection)


def get_low_stock_products():
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                p.id AS product_id,
                p.id,
                p.product_name,
                p.category,
                p.unit,
                p.minimum_stock,
                COALESCE(i.quantity, 0) AS quantity,
                COALESCE(i.quantity, 0) AS current_stock
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = 1
              AND COALESCE(i.quantity, 0) <= p.minimum_stock
            ORDER BY COALESCE(i.quantity, 0), p.product_name
            """
        )
        return cursor.fetchall()
    except Error as error:
        print("Get low-stock products error:", error)
        return []
    finally:
        _close_db(cursor, connection)


def get_stock_history(limit=200, product_id=None):
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT
                sh.*,
                p.product_name,
                p.unit,
                u.username AS created_by_username
            FROM stock_history sh
            LEFT JOIN products p ON p.id = sh.product_id
            LEFT JOIN users u ON u.id = sh.created_by
        """
        params = []
        if product_id is not None:
            query += " WHERE sh.product_id = %s"
            params.append(product_id)
        query += " ORDER BY sh.created_at DESC, sh.id DESC LIMIT %s"
        params.append(max(1, min(int(limit), 1000)))
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    except (Error, TypeError, ValueError) as error:
        print("Get stock history error:", error)
        return []
    finally:
        _close_db(cursor, connection)


# =========================================================
# CUSTOMERS
# =========================================================

def get_customers():
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, customer_name, phone, address, customer_type, created_at
            FROM customers
            ORDER BY customer_name
            """
        )
        return cursor.fetchall()
    except Error as error:
        print("Get customers error:", error)
        return []
    finally:
        _close_db(cursor, connection)


# =========================================================
# SALES AND BILLING
# =========================================================

def create_sale(
    customer_id,
    payment_method,
    discount,
    items,
    created_by,
    customer_name=None,
    customer_type="New",
    customer_phone=None,
    customer_address=None,
    payment_status="Pending",
):
    allowed_methods = {"Cash", "UPI", "Bank Transfer", "Other"}
    allowed_statuses = {"Pending", "Done"}
    allowed_customer_types = {"New", "Regular", "Wholesale"}

    if payment_method not in allowed_methods:
        return False, "Invalid payment method.", None
    if payment_status not in allowed_statuses:
        return False, "Invalid payment status.", None
    if customer_type not in allowed_customer_types:
        customer_type = "New"

    try:
        discount = _money(discount)
        if discount < 0:
            return False, "Discount cannot be negative.", None
    except (InvalidOperation, TypeError, ValueError):
        return False, "Enter a valid discount amount.", None

    if not isinstance(items, (list, tuple)) or not items:
        return False, "Add at least one product to the sale.", None

    normalized_items = []
    for item in items:
        try:
            if isinstance(item, dict):
                product_id = int(item.get("product_id", item.get("id")))
                quantity = int(item.get("quantity"))
            else:
                product_id = int(item[0])
                quantity = int(item[1])
        except (TypeError, ValueError, IndexError):
            return False, "Each sale item needs a valid product and quantity.", None

        if quantity <= 0:
            return False, "Sale quantities must be greater than zero.", None
        normalized_items.append((product_id, quantity))

    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed.", None

    cursor = None
    try:
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        # If a customer ID is supplied, make sure it exists.
        if customer_id not in (None, "", 0, "0"):
            try:
                customer_id = int(customer_id)
            except (TypeError, ValueError):
                connection.rollback()
                return False, "Invalid customer.", None

            cursor.execute(
                "SELECT id FROM customers WHERE id = %s FOR UPDATE",
                (customer_id,),
            )
            if cursor.fetchone() is None:
                connection.rollback()
                return False, "Selected customer was not found.", None
        else:
            customer_id = None
            if customer_name and str(customer_name).strip():
                cursor.execute(
                    """
                    INSERT INTO customers
                        (customer_name, phone, address, customer_type)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        str(customer_name).strip(),
                        (customer_phone or "").strip() or None,
                        (customer_address or "").strip() or None,
                        customer_type,
                    ),
                )
                customer_id = cursor.lastrowid

        # Lock products/inventory and calculate totals before writing the sale.
        sale_lines = []
        subtotal = Decimal("0.00")

        for product_id, quantity in normalized_items:
            cursor.execute(
                """
                SELECT id, product_name, selling_price
                FROM products
                WHERE id = %s AND is_active = 1
                FOR UPDATE
                """,
                (product_id,),
            )
            product = cursor.fetchone()
            if product is None:
                connection.rollback()
                return False, f"Product ID {product_id} was not found or is inactive.", None

            cursor.execute(
                "SELECT quantity FROM inventory WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            inventory_row = cursor.fetchone()
            stock_before = int(inventory_row["quantity"]) if inventory_row else 0

            if stock_before < quantity:
                connection.rollback()
                return (
                    False,
                    f"Insufficient stock for {product['product_name']}. "
                    f"Available: {stock_before}, requested: {quantity}.",
                    None,
                )

            unit_price = _money(product["selling_price"])
            line_total = _money(unit_price * quantity)
            subtotal += line_total
            sale_lines.append(
                {
                    "product_id": product_id,
                    "product_name": product["product_name"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "total_price": line_total,
                    "stock_before": stock_before,
                }
            )

        subtotal = _money(subtotal)
        if discount > subtotal:
            connection.rollback()
            return False, "Discount cannot exceed the subtotal.", None
        grand_total = _money(subtotal - discount)

        cursor.execute(
            """
            INSERT INTO sales
                (customer_id, sale_date, subtotal, discount, grand_total,
                 payment_method, created_by, payment_status)
            VALUES (%s, CURDATE(), %s, %s, %s, %s, %s, %s)
            """,
            (
                customer_id,
                subtotal,
                discount,
                grand_total,
                payment_method,
                created_by,
                payment_status,
            ),
        )
        sale_id = cursor.lastrowid

        for line in sale_lines:
            cursor.execute(
                """
                INSERT INTO sale_items
                    (sale_id, product_id, quantity, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    sale_id,
                    line["product_id"],
                    line["quantity"],
                    line["unit_price"],
                    line["total_price"],
                ),
            )

            stock_after = line["stock_before"] - line["quantity"]
            if stock_after < 0:
                connection.rollback()
                return False, "Stock changed while processing the sale. Try again.", None

            if stock_after == 0:
                cursor.execute(
                    "SELECT id FROM inventory WHERE product_id = %s",
                    (line["product_id"],),
                )
                existing_inventory = cursor.fetchone()
                if existing_inventory:
                    cursor.execute(
                        """
                        UPDATE inventory
                        SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE product_id = %s
                        """,
                        (stock_after, line["product_id"]),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO inventory (product_id, quantity) VALUES (%s, %s)",
                        (line["product_id"], stock_after),
                    )
            else:
                cursor.execute(
                    """
                    UPDATE inventory
                    SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = %s
                    """,
                    (stock_after, line["product_id"]),
                )

            cursor.execute(
                """
                INSERT INTO stock_history
                    (product_id, movement_type, quantity_change,
                     stock_before, stock_after, sale_id, notes, created_by)
                VALUES (%s, 'Sale', %s, %s, %s, %s, %s, %s)
                """,
                (
                    line["product_id"],
                    -line["quantity"],
                    line["stock_before"],
                    stock_after,
                    sale_id,
                    f"Stock deducted for sale #{sale_id}",
                    created_by,
                ),
            )

        connection.commit()
        return True, f"Sale #{sale_id} created successfully.", sale_id

    except Error as error:
        connection.rollback()
        print("Create sale error:", error)
        return False, "Unable to create sale. Check the terminal.", None
    except Exception as error:
        connection.rollback()
        print("Unexpected create sale error:", error)
        return False, "Unable to create sale. Check the terminal.", None
    finally:
        _close_db(cursor, connection)


def get_sales_history():
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                s.*,
                c.customer_name,
                c.phone AS customer_phone,
                u.username AS created_by_username
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN users u ON u.id = s.created_by
            ORDER BY s.created_at DESC, s.id DESC
            """
        )
        return cursor.fetchall()
    except Error as error:
        print("Get sales history error:", error)
        return []
    finally:
        _close_db(cursor, connection)


def get_sale_details(sale_id):
    connection = get_db_connection()
    if connection is None:
        return None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                s.*,
                c.customer_name,
                c.phone AS customer_phone,
                c.address AS customer_address,
                c.customer_type,
                u.username AS created_by_username
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN users u ON u.id = s.created_by
            WHERE s.id = %s
            LIMIT 1
            """,
            (sale_id,),
        )
        sale = cursor.fetchone()
        if sale is None:
            return None

        cursor.execute(
            """
            SELECT
                si.*,
                p.product_name,
                p.unit,
                p.category
            FROM sale_items si
            LEFT JOIN products p ON p.id = si.product_id
            WHERE si.sale_id = %s
            ORDER BY si.id
            """,
            (sale_id,),
        )
        sale["items"] = cursor.fetchall()
        return sale
    except Error as error:
        print("Get sale details error:", error)
        return None
    finally:
        _close_db(cursor, connection)


def delete_sale(sale_id, created_by=None):
    try:
        sale_id = int(sale_id)
    except (TypeError, ValueError):
        return False, "Invalid sale ID."

    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT id FROM sales WHERE id = %s FOR UPDATE", (sale_id,))
        if cursor.fetchone() is None:
            connection.rollback()
            return False, "Sale not found."

        cursor.execute(
            """
            SELECT product_id, quantity
            FROM sale_items
            WHERE sale_id = %s
            ORDER BY id
            FOR UPDATE
            """,
            (sale_id,),
        )
        sale_items = cursor.fetchall()

        for item in sale_items:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])

            cursor.execute(
                "SELECT quantity FROM inventory WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            inventory_row = cursor.fetchone()
            stock_before = int(inventory_row["quantity"]) if inventory_row else 0
            stock_after = stock_before + quantity

            if inventory_row:
                cursor.execute(
                    """
                    UPDATE inventory
                    SET quantity = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = %s
                    """,
                    (stock_after, product_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO inventory (product_id, quantity) VALUES (%s, %s)",
                    (product_id, stock_after),
                )

            cursor.execute(
                """
                INSERT INTO stock_history
                    (product_id, movement_type, quantity_change,
                     stock_before, stock_after, sale_id, notes, created_by)
                VALUES (%s, 'Sale Reversal', %s, %s, %s, %s, %s, %s)
                """,
                (
                    product_id,
                    quantity,
                    stock_before,
                    stock_after,
                    sale_id,
                    f"Stock restored after deleting sale #{sale_id}",
                    created_by,
                ),
            )

        cursor.execute("DELETE FROM sale_items WHERE sale_id = %s", (sale_id,))
        cursor.execute("DELETE FROM sales WHERE id = %s", (sale_id,))
        connection.commit()
        return True, "Sale deleted and stock restored successfully."
    except Error as error:
        connection.rollback()
        print("Delete sale error:", error)
        return False, "Unable to delete sale. Check the terminal."
    finally:
        _close_db(cursor, connection)


def mark_sale_as_done(sale_id):
    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE sales SET payment_status = 'Done' WHERE id = %s",
            (sale_id,),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            return False, "Sale not found or already marked as done."
        connection.commit()
        return True, "Payment marked as done."
    except Error as error:
        connection.rollback()
        print("Mark sale as done error:", error)
        return False, "Unable to update payment status."
    finally:
        _close_db(cursor, connection)


# =========================================================
# DASHBOARD STATISTICS
# =========================================================

def get_dashboard_stats():
    connection = get_db_connection()
    if connection is None:
        return {
            "total_products": 0,
            "total_stock": 0,
            "low_stock_count": 0,
            "today_sales": Decimal("0.00"),
            "monthly_revenue": Decimal("0.00"),
            "total_sales": 0,
            "today_sale_count": 0,
            "pending_payments": Decimal("0.00"),
        }

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        stats = {}

        cursor.execute("SELECT COUNT(*) AS total_products FROM products WHERE is_active = 1")
        stats["total_products"] = int(cursor.fetchone()["total_products"] or 0)

        cursor.execute("SELECT COALESCE(SUM(i.quantity), 0) AS total_stock FROM inventory i JOIN products p ON p.id = i.product_id WHERE p.is_active = 1")
        stats["total_stock"] = int(cursor.fetchone()["total_stock"] or 0)

        cursor.execute(
            """
            SELECT COUNT(*) AS low_stock_count
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = 1
              AND COALESCE(i.quantity, 0) <= p.minimum_stock
            """
        )
        stats["low_stock_count"] = int(cursor.fetchone()["low_stock_count"] or 0)

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN sale_date = CURDATE() THEN grand_total ELSE 0 END), 0) AS today_sales,
                COALESCE(SUM(CASE WHEN sale_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
                                  AND sale_date <= CURDATE() THEN grand_total ELSE 0 END), 0) AS monthly_revenue,
                COUNT(*) AS total_sales,
                COALESCE(SUM(CASE WHEN sale_date = CURDATE() THEN 1 ELSE 0 END), 0) AS today_sale_count,
                COALESCE(SUM(CASE WHEN payment_status = 'Pending' THEN grand_total ELSE 0 END), 0) AS pending_payments
            FROM sales
            """
        )
        sales_stats = cursor.fetchone() or {}
        stats.update(sales_stats)

        # Common aliases retained for dashboard templates that use alternate names.
        stats["total_revenue"] = stats.get("monthly_revenue", Decimal("0.00"))
        stats["sales_today"] = stats.get("today_sales", Decimal("0.00"))
        stats["stock_items"] = stats.get("total_stock", 0)
        stats["low_stock_products"] = stats.get("low_stock_count", 0)
        return stats
    except Error as error:
        print("Get dashboard stats error:", error)
        return {
            "total_products": 0,
            "total_stock": 0,
            "low_stock_count": 0,
            "today_sales": Decimal("0.00"),
            "monthly_revenue": Decimal("0.00"),
            "total_sales": 0,
            "today_sale_count": 0,
            "pending_payments": Decimal("0.00"),
            "total_revenue": Decimal("0.00"),
            "sales_today": Decimal("0.00"),
            "stock_items": 0,
            "low_stock_products": 0,
        }
    finally:
        _close_db(cursor, connection)


# =========================================================
# PRODUCT MANAGEMENT
# =========================================================


def get_all_products():
    connection = get_db_connection()
    if connection is None:
        return []

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.unit,
                p.selling_price,
                p.minimum_stock,
                p.is_active,
                p.created_at,
                COALESCE(i.quantity, 0) AS quantity,
                COALESCE(i.quantity, 0) AS stock,
                COALESCE(i.quantity, 0) AS current_stock
            FROM products p
            LEFT JOIN inventory i
                ON i.product_id = p.id
            ORDER BY p.id DESC
            """
        )
        return cursor.fetchall()

    except Error as error:
        print("Get all products error:", error)
        return []

    finally:
        _close_db(cursor, connection)


def get_product_by_id(product_id):
    connection = get_db_connection()
    if connection is None:
        return None

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.unit,
                p.selling_price,
                p.minimum_stock,
                p.is_active,
                p.created_at,
                COALESCE(i.quantity, 0) AS quantity,
                COALESCE(i.quantity, 0) AS current_stock
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.id = %s
            LIMIT 1
            """,
            (product_id,),
        )
        return cursor.fetchone()
    except Error as error:
        print("Get product by ID error:", error)
        return None
    finally:
        _close_db(cursor, connection)


def create_product(product_name, category, unit, selling_price, minimum_stock):
    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        selling_price = _money(selling_price)
        minimum_stock = int(minimum_stock)

        if not product_name or not str(product_name).strip():
            return False, "Product name is required."
        if selling_price < 0 or minimum_stock < 0:
            return False, "Price and minimum stock cannot be negative."

        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO products
                (product_name, category, unit, selling_price, minimum_stock, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (
                str(product_name).strip(),
                (category or "").strip() or None,
                (unit or "").strip() or None,
                selling_price,
                minimum_stock,
            ),
        )
        product_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO inventory (product_id, quantity) VALUES (%s, 0)",
            (product_id,),
        )
        connection.commit()
        return True, "Product created successfully."
    except (Error, TypeError, ValueError) as error:
        connection.rollback()
        print("Create product error:", error)
        return False, "Unable to create product. Check the terminal."
    finally:
        _close_db(cursor, connection)


def update_product(
    product_id, product_name, category, unit, selling_price, minimum_stock
):
    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        selling_price = _money(selling_price)
        minimum_stock = int(minimum_stock)

        if not product_name or not str(product_name).strip():
            return False, "Product name is required."
        if selling_price < 0 or minimum_stock < 0:
            return False, "Price and minimum stock cannot be negative."

        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE products
            SET product_name = %s,
                category = %s,
                unit = %s,
                selling_price = %s,
                minimum_stock = %s
            WHERE id = %s
            """,
            (
                str(product_name).strip(),
                (category or "").strip() or None,
                (unit or "").strip() or None,
                selling_price,
                minimum_stock,
                product_id,
            ),
        )

        if cursor.rowcount == 0:
            cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
            if cursor.fetchone() is None:
                connection.rollback()
                return False, "Product not found."

        connection.commit()
        return True, "Product updated successfully."
    except (Error, TypeError, ValueError) as error:
        connection.rollback()
        print("Update product error:", error)
        return False, "Unable to update product. Check the terminal."
    finally:
        _close_db(cursor, connection)


def deactivate_product(product_id):
    connection = get_db_connection()
    if connection is None:
        return False, "Database connection failed."

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE products SET is_active = 0 WHERE id = %s AND is_active = 1",
            (product_id,),
        )

        if cursor.rowcount == 0:
            connection.rollback()
            return False, "Product not found or already inactive."

        connection.commit()
        return True, "Product deactivated successfully."
    except Error as error:
        connection.rollback()
        print("Deactivate product error:", error)
        return False, "Unable to deactivate product. Check the terminal."
    finally:
        _close_db(cursor, connection)

# =========================================================
# SALES ANALYTICS
# =========================================================
def get_sales_analytics(start_date, end_date):
    """Return sales summaries and best-selling products."""

    empty_result = {
        "total_revenue": 0.0,
        "total_bills": 0,
        "average_bill": 0.0,
        "daily_labels": [],
        "daily_revenue": [],
        "best_sellers": [],
    }

    connection = get_db_connection()

    if connection is None:
        return empty_result

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(grand_total), 0) AS total_revenue,
                COUNT(*) AS total_bills,
                COALESCE(AVG(grand_total), 0) AS average_bill
            FROM sales
            WHERE sale_date >= %s AND sale_date <= %s
            """,
            (start_date, end_date),
        )

        summary = cursor.fetchone() or {}

        cursor.execute(
            """
            SELECT
                sale_date,
                COALESCE(SUM(grand_total), 0) AS revenue
            FROM sales
            WHERE sale_date >= %s AND sale_date <= %s
            GROUP BY sale_date
            ORDER BY sale_date
            """,
            (start_date, end_date),
        )

        daily_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                p.product_name,
                COALESCE(SUM(si.quantity), 0) AS quantity_sold,
                COALESCE(SUM(si.total_price), 0) AS sales_value
            FROM sales s
            INNER JOIN sale_items si ON si.sale_id = s.id
            INNER JOIN products p ON p.id = si.product_id
            WHERE s.sale_date >= %s AND s.sale_date <= %s
            GROUP BY p.id, p.product_name
            ORDER BY quantity_sold DESC, sales_value DESC
            LIMIT 10
            """,
            (start_date, end_date),
        )

        best_sellers = cursor.fetchall()

        return {
            "total_revenue": float(
                summary.get("total_revenue") or 0
            ),
            "total_bills": int(
                summary.get("total_bills") or 0
            ),
            "average_bill": float(
                summary.get("average_bill") or 0
            ),
            "daily_labels": [
                row["sale_date"].strftime("%d %b %Y")
                for row in daily_rows
            ],
            "daily_revenue": [
                float(row["revenue"] or 0)
                for row in daily_rows
            ],
            "best_sellers": [
                {
                    "product_name": row["product_name"],
                    "quantity_sold": int(
                        row["quantity_sold"] or 0
                    ),
                    "sales_value": float(
                        row["sales_value"] or 0
                    ),
                }
                for row in best_sellers
            ],
        }

    except Error as error:
        print("Get sales analytics error:", error)
        return empty_result

    finally:
        _close_db(cursor, connection)


# =========================================================
# BUSINESS INSIGHTS
# =========================================================

def get_business_insights():
    """Generate rule-based insights from existing sales and inventory data."""
    from datetime import date, timedelta

    today = date.today()

    # Compare the latest 7 days with the preceding 7 days.
    current_start = today - timedelta(days=6)
    previous_start = today - timedelta(days=13)
    previous_end = today - timedelta(days=7)

    current_sales = get_sales_analytics(current_start, today)
    previous_sales = get_sales_analytics(previous_start, previous_end)
    low_stock_products = get_low_stock_products()

    current_revenue = float(current_sales.get("total_revenue", 0) or 0)
    previous_revenue = float(previous_sales.get("total_revenue", 0) or 0)

    insights = []

    # Inventory recommendations.
    if low_stock_products:
        product_names = [
            str(product.get("product_name", "Unknown product"))
            for product in low_stock_products[:5]
        ]

        names = ", ".join(product_names)

        if len(low_stock_products) > 5:
            names += f" and {len(low_stock_products) - 5} more"

        insights.append({
            "type": "warning",
            "title": "Low Stock Alert",
            "message": (
                f"{len(low_stock_products)} product(s) need attention: "
                f"{names}. Review stock before replenishing."
            ),
        })
    else:
        insights.append({
            "type": "success",
            "title": "Inventory Status",
            "message": "No active products are currently below their minimum stock level.",
        })

    # Revenue trend recommendations.
    if previous_revenue > 0:
        change = (
            (current_revenue - previous_revenue)
            / previous_revenue
        ) * 100

        if change > 0.01:
            insights.append({
                "type": "success",
                "title": "Revenue Is Growing",
                "message": (
                    f"Revenue over the last 7 days increased by "
                    f"{change:.1f}% compared with the previous 7 days."
                ),
            })
        elif change < -0.01:
            insights.append({
                "type": "warning",
                "title": "Revenue Has Decreased",
                "message": (
                    f"Revenue over the last 7 days decreased by "
                    f"{abs(change):.1f}% compared with the previous 7 days. "
                    "Review recent sales activity."
                ),
            })
        else:
            insights.append({
                "type": "info",
                "title": "Revenue Is Stable",
                "message": "Revenue is approximately unchanged compared with the previous 7 days.",
            })
    elif current_revenue > 0:
        insights.append({
            "type": "success",
            "title": "Sales Activity",
            "message": (
                "Revenue was recorded in the last 7 days, "
                "but there was no revenue in the comparison period."
            ),
        })
    else:
        insights.append({
            "type": "info",
            "title": "No Recent Revenue",
            "message": (
                "No revenue was recorded in either 7-day period. "
                "Check your sales records if this is unexpected."
            ),
        })

    # Best-selling product insight.
    best_sellers = current_sales.get("best_sellers", [])

    if best_sellers:
        best = best_sellers[0]
        insights.append({
            "type": "info",
            "title": "Top-Selling Product",
            "message": (
                f"{best['product_name']} sold "
                f"{best['quantity_sold']} unit(s) in the last 7 days."
            ),
        })

    return {
        "insights": insights,
        "low_stock_count": len(low_stock_products),
        "current_revenue": current_revenue,
        "previous_revenue": previous_revenue,
        "period_start": current_start.isoformat(),
        "period_end": today.isoformat(),
    }

