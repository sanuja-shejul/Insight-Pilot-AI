
import os
from decimal import Decimal, ROUND_HALF_UP

import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "indira_foods")
}


# =========================================================
# DATABASE CONNECTION
# =========================================================

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


# =========================================================
# USERS
# =========================================================

def create_user(username, password_hash):
    connection = get_db_connection()

    if connection is None:
        return False, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
        """, (username, password_hash))

        connection.commit()
        return True, "User created successfully."

    except mysql.connector.IntegrityError:
        connection.rollback()
        return False, "Username already exists."

    except Error as error:
        connection.rollback()
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

        cursor.execute("""
            SELECT *
            FROM users
            WHERE username = %s
            LIMIT 1
        """, (username,))

        return cursor.fetchone()

    except Error as error:
        print("Find user error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


# =========================================================
# INVENTORY
# =========================================================

def get_inventory():
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
                p.minimum_stock,
                COALESCE(i.quantity, 0) AS current_stock
            FROM products AS p
            LEFT JOIN inventory AS i
                ON p.id = i.product_id
            ORDER BY p.id
        """)

        return cursor.fetchall()

    except Error as error:
        print("Get inventory error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def add_stock(product_id, quantity_to_add):
    """Add stock to an existing product or create its inventory row."""

    connection = get_db_connection()

    if connection is None:
        return False, "Unable to connect to the database."

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO inventory (product_id, quantity)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                quantity = quantity + %s
        """, (
            product_id,
            quantity_to_add,
            quantity_to_add
        ))

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


def get_active_products():
    """Return active products, prices, and available stock."""

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
            LEFT JOIN inventory AS i
                ON i.product_id = p.id
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


# =========================================================
# CUSTOMERS
# =========================================================

def get_customers():
    """Return customer details for the sales form."""

    connection = get_db_connection()

    if connection is None:
        return None

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id,
                customer_name,
                phone,
                address,
                customer_type
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


# =========================================================
# CREATE SALE
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
    payment_status="Pending"
):
    """
    Create a sale and optionally create a new customer.

    Automatically:
    - Validates the customer and products.
    - Calculates prices and discount.
    - Saves payment method and payment status.
    - Saves sale items.
    - Deducts inventory.
    - Rolls back database changes if the sale fails.

    Returns:
        (success, message, sale_id)
    """

    allowed_payments = {
        "Cash", "UPI", "Bank Transfer", "Other"
    }

    allowed_statuses = {"Pending", "Done"}

    allowed_customer_types = {
        "New", "Regular", "Wholesale"
    }

    if payment_method not in allowed_payments:
        return False, "Please select a valid payment method.", None

    if payment_status not in allowed_statuses:
        return False, "Select Pending or Done for payment status.", None

    if customer_type not in allowed_customer_types:
        return False, "Please select a valid customer type.", None

    customer_name = (customer_name or "").strip()
    customer_phone = (customer_phone or "").strip() or None
    customer_address = (customer_address or "").strip() or None

    try:
        discount = Decimal(str(discount)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

    except Exception:
        return False, "Enter a valid discount.", None

    if not discount.is_finite() or discount < 0:
        return False, "Discount cannot be negative.", None

    if not items:
        return False, "Add at least one product to the bill.", None

    # Combine duplicate product rows.
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

        # -------------------------------------------------
        # EXISTING CUSTOMER OR NEW CUSTOMER
        # -------------------------------------------------

        if customer_id not in (None, ""):

            try:
                customer_id = int(customer_id)

            except (ValueError, TypeError):
                raise ValueError("Please select a valid customer.")

            cursor.execute("""
                SELECT id
                FROM customers
                WHERE id = %s
                FOR UPDATE
            """, (customer_id,))

            if cursor.fetchone() is None:
                raise ValueError(
                    "The selected customer does not exist."
                )

        elif customer_name:

            cursor.execute("""
                INSERT INTO customers (
                    customer_name,
                    phone,
                    address,
                    customer_type
                )
                VALUES (%s, %s, %s, %s)
            """, (
                customer_name,
                customer_phone,
                customer_address,
                customer_type
            ))

            customer_id = cursor.lastrowid

        else:
            customer_id = None

        # -------------------------------------------------
        # VALIDATE PRODUCTS AND CALCULATE TOTALS
        # -------------------------------------------------

        sale_lines = []
        subtotal = Decimal("0.00")

        for product_id, quantity in sorted(combined_items.items()):

            cursor.execute("""
                SELECT
                    id,
                    product_name,
                    selling_price,
                    is_active
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
                    f"Insufficient stock for "
                    f"{product['product_name']}. "
                    f"Available: {available}, requested: {quantity}."
                )

            unit_price = Decimal(
                str(product["selling_price"])
            ).quantize(Decimal("0.01"))

            line_total = (unit_price * quantity).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            subtotal += line_total

            sale_lines.append({
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": line_total
            })

        subtotal = subtotal.quantize(Decimal("0.01"))

        if discount > subtotal:
            raise ValueError("Discount cannot exceed the subtotal.")

        grand_total = (subtotal - discount).quantize(
            Decimal("0.01")
        )

        # -------------------------------------------------
        # SAVE SALE HEADER INCLUDING PAYMENT STATUS
        # -------------------------------------------------

        cursor.execute("""
            INSERT INTO sales (
                customer_id,
                sale_date,
                subtotal,
                discount,
                grand_total,
                payment_method,
                payment_status,
                created_by
            )
            VALUES (%s, CURDATE(), %s, %s, %s, %s, %s, %s)
        """, (
            customer_id,
            subtotal,
            discount,
            grand_total,
            payment_method,
            payment_status,
            created_by
        ))

        sale_id = cursor.lastrowid

        # -------------------------------------------------
        # SAVE ITEMS AND DEDUCT STOCK
        # -------------------------------------------------

        for line in sale_lines:

            cursor.execute("""
                INSERT INTO sale_items (
                    sale_id,
                    product_id,
                    quantity,
                    unit_price,
                    total_price
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                sale_id,
                line["product_id"],
                line["quantity"],
                line["unit_price"],
                line["total_price"]
            ))

            cursor.execute("""
                UPDATE inventory
                SET quantity = quantity - %s
                WHERE product_id = %s
                  AND quantity >= %s
            """, (
                line["quantity"],
                line["product_id"],
                line["quantity"]
            ))

            if cursor.rowcount != 1:
                raise ValueError(
                    "Stock changed while processing the sale. "
                    "Please try again."
                )

        connection.commit()

        return (
            True,
            "Sale saved and stock updated successfully.",
            sale_id
        )

    except (ValueError, TypeError) as error:
        connection.rollback()
        return False, str(error), None

    except Error as error:
        connection.rollback()
        print("Create sale error:", error)

        return (
            False,
            "Sale could not be saved. Check the terminal.",
            None
        )

    finally:
        if cursor:
            cursor.close()
        connection.close()


# =========================================================
# SALES HISTORY
# =========================================================

def get_sales_history():
    """Return recent sales including customer and payment status."""

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
                s.payment_status,
                c.customer_name,
                c.customer_type
            FROM sales AS s
            LEFT JOIN customers AS c
                ON s.customer_id = c.id
            ORDER BY s.id DESC
            LIMIT 200
        """)

        return cursor.fetchall()

    except Error as error:
        print("Get sales history error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


# =========================================================
# BILL DETAILS
# =========================================================

def get_sale_details(sale_id):
    """Return bill details and product lines."""

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
                s.payment_status,
                c.customer_name,
                c.customer_type,
                c.phone,
                c.address,
                u.username AS created_by_username
            FROM sales AS s
            LEFT JOIN customers AS c
                ON c.id = s.customer_id
            LEFT JOIN users AS u
                ON u.id = s.created_by
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
            JOIN products AS p
                ON p.id = si.product_id
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


# =========================================================
# DELETE SALE AND RESTORE STOCK
# =========================================================

def delete_sale(sale_id):
    """Delete a sale and restore the sold quantities."""

    connection = get_db_connection()

    if connection is None:
        return False, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()

        cursor.execute("""
            SELECT id
            FROM sales
            WHERE id = %s
            FOR UPDATE
        """, (sale_id,))

        sale = cursor.fetchone()

        if not sale:
            connection.rollback()
            return False, "Sale record not found."

        cursor.execute("""
            SELECT product_id, quantity
            FROM sale_items
            WHERE sale_id = %s
            ORDER BY product_id
            FOR UPDATE
        """, (sale_id,))

        items = cursor.fetchall()

        # Restore inventory quantities.
        for item in items:
            cursor.execute("""
                INSERT INTO inventory (product_id, quantity)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    quantity = quantity + VALUES(quantity)
            """, (
                item["product_id"],
                item["quantity"]
            ))

        # Delete bill lines before deleting the sale.
        cursor.execute("""
            DELETE FROM sale_items
            WHERE sale_id = %s
        """, (sale_id,))

        cursor.execute("""
            DELETE FROM sales
            WHERE id = %s
        """, (sale_id,))

        connection.commit()

        return (
            True,
            "Sale deleted and stock restored successfully."
        )

    except Exception as error:
        connection.rollback()
        print("Delete sale error:", error)

        return (
            False,
            "Could not delete sale. No changes were saved."
        )

    finally:
        if cursor:
            cursor.close()
        connection.close()
# =========================================================
# MARK SALE PAYMENT AS DONE
# =========================================================

def mark_sale_as_done(sale_id):
    """Change a sale's payment status from Pending to Done."""

    connection = get_db_connection()

    if connection is None:
        return False, "Database connection failed."

    cursor = None

    try:
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE sales
            SET payment_status = 'Done'
            WHERE id = %s
              AND payment_status = 'Pending'
        """, (sale_id,))

        if cursor.rowcount == 1:
            connection.commit()
            return True, "Payment marked as Done successfully."

        # Find out why no row was updated.
        cursor.execute("""
            SELECT payment_status
            FROM sales
            WHERE id = %s
        """, (sale_id,))

        sale = cursor.fetchone()
        connection.rollback()

        if sale is None:
            return False, "Sale record not found."

        return False, "This payment is already marked as Done."

    except Error as error:
        connection.rollback()
        print("Update payment status error:", error)
        return False, "Unable to update payment status."

    finally:
        if cursor:
            cursor.close()
        connection.close()

# =========================================================
# DASHBOARD ANALYTICS
# =========================================================

def get_dashboard_stats():
    """Return real sales KPIs and the last seven days of sales."""

    connection = get_db_connection()

    if connection is None:
        return None

    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)

        # Today's revenue and number of bills created today.
        cursor.execute("""
            SELECT
                COALESCE(SUM(grand_total), 0) AS today_revenue,
                COUNT(*) AS today_sales
            FROM sales
            WHERE sale_date >= CURDATE()
              AND sale_date < CURDATE() + INTERVAL 1 DAY
        """)

        today = cursor.fetchone()

        # All-time sales and pending payment totals.
        cursor.execute("""
            SELECT
                COUNT(*) AS total_sales,
                COALESCE(SUM(
                    CASE
                        WHEN payment_status = 'Pending'
                        THEN grand_total
                        ELSE 0
                    END
                ), 0) AS pending_amount,
                COALESCE(SUM(
                    CASE
                        WHEN payment_status = 'Pending'
                        THEN 1
                        ELSE 0
                    END
                ), 0) AS pending_count
            FROM sales
        """)

        totals = cursor.fetchone()

        # Daily sales revenue for the last seven days,
        # including days with no sales.
        cursor.execute("""
            SELECT
                DATE(sale_date) AS sale_day,
                COALESCE(SUM(grand_total), 0) AS revenue
            FROM sales
            WHERE sale_date >= CURDATE() - INTERVAL 6 DAY
              AND sale_date < CURDATE() + INTERVAL 1 DAY
            GROUP BY DATE(sale_date)
            ORDER BY DATE(sale_date)
        """)

        daily_rows = cursor.fetchall()

        # Payment status breakdown.
        cursor.execute("""
            SELECT
                payment_status,
                COUNT(*) AS bill_count
            FROM sales
            GROUP BY payment_status
        """)

        payment_rows = cursor.fetchall()

        # Fill in dates with zero revenue.
        daily_lookup = {
            row["sale_day"].isoformat(): float(row["revenue"] or 0)
            for row in daily_rows
        }

        chart_labels = []
        chart_revenue = []

        for offset in range(6, -1, -1):
            cursor.execute(
                "SELECT DATE(CURDATE() - INTERVAL %s DAY) AS chart_day",
                (offset,)
            )
            day_row = cursor.fetchone()
            day = day_row["chart_day"]
            day_key = day.isoformat()

            chart_labels.append(day.strftime("%d %b"))
            chart_revenue.append(daily_lookup.get(day_key, 0))

        payment_counts = {
            "Pending": 0,
            "Done": 0
        }

        for row in payment_rows:
            status = row["payment_status"]
            if status in payment_counts:
                payment_counts[status] = int(row["bill_count"])

        return {
            "today_revenue": float(today["today_revenue"] or 0),
            "today_sales": int(today["today_sales"] or 0),
            "total_sales": int(totals["total_sales"] or 0),
            "pending_amount": float(totals["pending_amount"] or 0),
            "pending_count": int(totals["pending_count"] or 0),
            "chart_labels": chart_labels,
            "chart_revenue": chart_revenue,
            "payment_counts": payment_counts
        }

    except Error as error:
        print("Dashboard analytics error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        connection.close()


def get_low_stock_products():
    """Return active products that have reached their minimum stock level."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.unit,
                COALESCE(i.quantity, 0) AS current_stock,
                p.minimum_stock
            FROM products AS p
            LEFT JOIN inventory AS i
                ON i.product_id = p.id
            WHERE p.is_active = 1
              AND COALESCE(i.quantity, 0) <= p.minimum_stock
            ORDER BY
                CASE
                    WHEN COALESCE(i.quantity, 0) = 0 THEN 0
                    ELSE 1
                END,
                p.product_name ASC
        """

        cursor.execute(query)
        return cursor.fetchall()

    except Error as e:
        print("Error fetching low-stock products:", e)
        return None

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

def get_all_products():
    """Return all products, including inactive products."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                p.id,
                p.product_name,
                p.category,
                p.unit,
                p.selling_price,
                p.minimum_stock,
                p.is_active,
                COALESCE(i.quantity, 0) AS current_stock
            FROM products AS p
            LEFT JOIN inventory AS i
                ON i.product_id = p.id
            ORDER BY p.product_name ASC
        """

        cursor.execute(query)
        return cursor.fetchall()

    except Error as e:
        print("Error fetching products:", e)
        return None

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def get_product_by_id(product_id):
    """Return one product by its ID."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                id,
                product_name,
                category,
                unit,
                selling_price,
                minimum_stock,
                is_active
            FROM products
            WHERE id = %s
        """

        cursor.execute(query, (product_id,))
        return cursor.fetchone()

    except Error as e:
        print("Error fetching product:", e)
        return None

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def create_product(product_name, category, unit,
                   selling_price, minimum_stock):
    """Create a product and its initial zero-stock inventory record."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        connection.start_transaction()

        query = """
            INSERT INTO products
                (product_name, category, unit,
                 selling_price, minimum_stock, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
        """

        cursor.execute(
            query,
            (
                product_name,
                category,
                unit,
                selling_price,
                minimum_stock
            )
        )

        product_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO inventory (product_id, quantity)
            VALUES (%s, 0)
            """,
            (product_id,)
        )

        connection.commit()
        return True, "Product added successfully."

    except Error as e:
        if connection is not None:
            connection.rollback()

        print("Error creating product:", e)
        return False, "Could not add the product. Check the details and database."

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def update_product(product_id, product_name, category, unit,
                   selling_price, minimum_stock):
    """Update product details without changing its current stock."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        query = """
            UPDATE products
            SET product_name = %s,
                category = %s,
                unit = %s,
                selling_price = %s,
                minimum_stock = %s
            WHERE id = %s
              AND is_active = 1
        """

        cursor.execute(
            query,
            (
                product_name,
                category,
                unit,
                selling_price,
                minimum_stock,
                product_id
            )
        )

        if cursor.rowcount == 0:
            connection.rollback()
            return False, "Product not found or already inactive."

        connection.commit()
        return True, "Product updated successfully."

    except Error as e:
        if connection is not None:
            connection.rollback()

        print("Error updating product:", e)
        return False, "Could not update the product."

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def deactivate_product(product_id):
    """Deactivate a product without deleting its sales history."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE products
            SET is_active = 0
            WHERE id = %s
              AND is_active = 1
            """,
            (product_id,)
        )

        if cursor.rowcount == 0:
            connection.rollback()
            return False, "Product not found or already inactive."

        connection.commit()
        return True, "Product deactivated successfully."

    except Error as e:
        if connection is not None:
            connection.rollback()

        print("Error deactivating product:", e)
        return False, "Could not deactivate the product."

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
