
import os
from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)



from database import (
    create_user,
    get_user_by_username,
    get_dashboard_stats,
    get_inventory,
    add_stock,
    get_active_products,
    get_customers,
    create_sale,
    get_sales_history,
    get_sale_details,
    delete_sale,
    mark_sale_as_done,
    get_low_stock_products,
    get_all_products,
    get_product_by_id,
    create_product,
    update_product,
    deactivate_product
)



load_dotenv()

app = Flask(__name__)

# Load the secret key from .env
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing from your .env file."
    )


# =========================================================
# LOGIN
# =========================================================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template(
                "login.html",
                error="Please enter username and password."
            )

        user = get_user_by_username(username)

        if user is None:
            return render_template(
                "login.html",
                error="Invalid username or password."
            )

        if not user.get("is_active", True):
            return render_template(
                "login.html",
                error="Your account is inactive."
            )

        password_hash = user.get("password_hash")

        if not password_hash or not check_password_hash(
            password_hash, password
        ):
            return render_template(
                "login.html",
                error="Invalid username or password."
            )

        session.clear()
        session["logged_in"] = True
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["full_name"] = (
            user.get("full_name") or user["username"]
        )
        session["role"] = user.get("role") or "Staff"

        return redirect(url_for("dashboard"))

    return render_template("login.html")


# =========================================================
# SIGN UP
# =========================================================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not username or not password or not confirm_password:
            return render_template(
                "signup.html",
                error="Please fill all required fields."
            )

        if password != confirm_password:
            return render_template(
                "signup.html",
                error="Passwords do not match."
            )

        if len(password) < 6:
            return render_template(
                "signup.html",
                error="Password must contain at least 6 characters."
            )

        password_hash = generate_password_hash(password)

        success, message = create_user(
            username,
            password_hash
        )

        if not success:
            return render_template(
                "signup.html",
                error=message
            )

        return render_template(
            "signup.html",
            success="Account created successfully! You can now log in."
        )

    return render_template("signup.html")


# =========================================================
# DASHBOARD
# =========================================================



@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))

    stats = get_dashboard_stats()

    if stats is None:
        stats = {
            "today_revenue": 0,
            "today_sales": 0,
            "total_sales": 0,
            "pending_amount": 0,
            "pending_count": 0,
            "chart_labels": [],
            "chart_revenue": [],
            "payment_counts": {
                "Pending": 0,
                "Done": 0
            }
        }

    low_stock_products = get_low_stock_products()

    if low_stock_products is None:
        low_stock_products = []

    return render_template(
        "dashboard.html",
        username=session.get("username"),
        full_name=session.get("full_name"),
        role=session.get("role"),
        stats=stats,
        low_stock_products=low_stock_products
    )



# =========================================================
# INVENTORY
# =========================================================

@app.route("/inventory")
def inventory():

    if "username" not in session:
        return redirect(url_for("login"))

    products = get_inventory()

    if products is None:
        return render_template(
            "inventory.html",
            products=[],
            error=(
                "Unable to retrieve inventory. "
                "Check your MySQL connection and terminal."
            ),
            total_products=0,
            total_packets=0,
            low_stock_count=0,
            out_of_stock_count=0
        )

    total_products = len(products)

    total_packets = sum(
        int(product["current_stock"] or 0)
        for product in products
    )

    low_stock_count = sum(
        1 for product in products
        if 0 < int(product["current_stock"] or 0)
        <= int(product["minimum_stock"] or 0)
    )

    out_of_stock_count = sum(
        1 for product in products
        if int(product["current_stock"] or 0) == 0
    )

    return render_template(
        "inventory.html",
        products=products,
        total_products=total_products,
        total_packets=total_packets,
        low_stock_count=low_stock_count,
        out_of_stock_count=out_of_stock_count
    )


# =========================================================
# ADD / UPDATE STOCK
# =========================================================

@app.route("/add-stock", methods=["GET", "POST"])
def add_stock_page():

    if "username" not in session:
        return redirect(url_for("login"))

    message = None
    message_type = None

    if request.method == "POST":

        product_id_text = request.form.get(
            "product_id", ""
        ).strip()

        quantity_text = request.form.get(
            "quantity", ""
        ).strip()

        try:
            if not product_id_text or not quantity_text:
                raise ValueError(
                    "Please select a product and enter a quantity."
                )

            product_id = int(product_id_text)
            quantity = int(quantity_text)

            if product_id <= 0:
                raise ValueError("Please select a valid product.")

            if quantity <= 0:
                raise ValueError(
                    "Quantity must be greater than zero."
                )

            success, result_message = add_stock(
                product_id, quantity
            )

            message = result_message
            message_type = "success" if success else "error"

        except ValueError as error:
            message = str(error)
            message_type = "error"

    products = get_inventory()

    if products is None:
        products = []
        message = message or (
            "Unable to load products. Check the database connection."
        )
        message_type = "error"

    return render_template(
        "add_stock.html",
        products=products,
        message=message,
        message_type=message_type
    )


# =========================================================
# SALES HISTORY
# =========================================================

@app.route("/sales")
def sales():

    if "username" not in session:
        return redirect(url_for("login"))

    sales_list = get_sales_history()

    if sales_list is None:
        return render_template(
            "sales.html",
            sales_list=[],
            error="Unable to load sales. Check the database connection."
        )

    return render_template(
        "sales.html",
        sales_list=sales_list,
        error=None
    )


# =========================================================
# CREATE NEW SALE
# =========================================================

@app.route("/sales/new", methods=["GET", "POST"])
def new_sale():

    if "username" not in session:
        return redirect(url_for("login"))

    message = None
    message_type = None

    if request.method == "POST":

        customer_text = request.form.get(
            "customer_id", ""
        ).strip()

        customer_name = request.form.get(
            "customer_name", ""
        ).strip()

        customer_type = request.form.get(
            "customer_type", "New"
        ).strip()

        customer_phone = request.form.get(
            "customer_phone", ""
        ).strip()

        customer_address = request.form.get(
            "customer_address", ""
        ).strip()

        payment_method = request.form.get(
            "payment_method", ""
        ).strip()

        payment_status = request.form.get(
            "payment_status", "Pending"
        ).strip()

        discount_text = request.form.get(
            "discount", "0"
        ).strip()

        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("quantity")

        try:
            # Customer selection:
            # "new" = create a new customer
            # number = existing customer
            # blank = walk-in customer

            if customer_text == "new":

                customer_id = None

                if not customer_name:
                    raise ValueError(
                        "Please enter the customer's name."
                    )

            elif customer_text:

                customer_id = int(customer_text)

                if customer_id <= 0:
                    raise ValueError(
                        "Please select a valid customer."
                    )

            else:
                customer_id = None

            # Validate product rows.
            if len(product_ids) != len(quantities):
                raise ValueError("Invalid product rows.")

            items = []

            for product_text, quantity_text in zip(
                product_ids, quantities
            ):

                if not product_text and not quantity_text:
                    continue

                if not product_text or not quantity_text:
                    raise ValueError(
                        "Select a product and enter its quantity."
                    )

                items.append({
                    "product_id": int(product_text),
                    "quantity": int(quantity_text)
                })

            # Save customer details, sale, payment status,
            # bill items, and stock changes.
            success, result_message, sale_id = create_sale(
                customer_id=customer_id,
                payment_method=payment_method,
                discount=discount_text,
                items=items,
                created_by=session.get("user_id"),
                customer_name=(
                    customer_name
                    if customer_text == "new"
                    else None
                ),
                customer_type=customer_type,
                customer_phone=customer_phone,
                customer_address=customer_address,
                payment_status=payment_status
            )

            if success:
                return redirect(
                    url_for("sale_bill", sale_id=sale_id)
                )

            message = result_message
            message_type = "error"

        except (ValueError, TypeError) as error:

            message = str(error) or (
                "Please check the customer, products, quantities, "
                "payment details, and discount."
            )

            message_type = "error"

    products = get_active_products()
    customers = get_customers()

    if products is None or customers is None:

        products = products or []
        customers = customers or []

        message = message or (
            "Unable to load products or customers. "
            "Check your MySQL connection."
        )

        message_type = "error"

    return render_template(
        "new_sale.html",
        products=products,
        customers=customers,
        message=message,
        message_type=message_type
    )


# =========================================================
# VIEW / PRINT BILL
# =========================================================

@app.route("/sales/<int:sale_id>")
def sale_bill(sale_id):

    if "username" not in session:
        return redirect(url_for("login"))

    sale, items = get_sale_details(sale_id)

    if sale is None:
        return render_template(
            "bill.html",
            sale=None,
            items=[]
        ), 404

    return render_template(
        "bill.html",
        sale=sale,
        items=items
    )


# =========================================================
# MARK PAYMENT AS DONE
# =========================================================

@app.route(
    "/sales/<int:sale_id>/mark-done",
    methods=["POST"]
)
def mark_payment_done(sale_id):

    if "username" not in session:
        return redirect(url_for("login"))

    success, message = mark_sale_as_done(sale_id)

    flash(
        message,
        "success" if success else "error"
    )

    return redirect(url_for("sales"))


# =========================================================
# DELETE SALE
# Only Owner can delete a sale.
# Existing database function restores stock.
# =========================================================

@app.route("/sales/<int:sale_id>/delete", methods=["POST"])
def delete_sale_route(sale_id):

    if "username" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "Owner":
        flash(
            "Only the Owner can delete sales.",
            "error"
        )
        return redirect(url_for("sales"))

    success, message = delete_sale(sale_id)

    flash(
        message,
        "success" if success else "error"
    )

    return redirect(url_for("sales"))


@app.route("/products")
def products():
    if "username" not in session:
        return redirect(url_for("login"))

    product_list = get_all_products()

    if product_list is None:
        flash("Unable to load products. Please check the database.", "error")
        product_list = []

    return render_template(
        "products.html",
        products=product_list,
        username=session.get("username"),
        full_name=session.get("full_name"),
        role=session.get("role")
    )


@app.route("/products/new", methods=["GET", "POST"])
def new_product():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip()
        category = request.form.get("category", "").strip()
        unit = request.form.get("unit", "").strip()

        try:
            selling_price = float(request.form.get("selling_price", ""))
            minimum_stock = int(request.form.get("minimum_stock", ""))

            if not product_name or not category or not unit:
                raise ValueError

            if selling_price < 0 or minimum_stock < 0:
                raise ValueError

            if not __import__("math").isfinite(selling_price):
                raise ValueError

        except (ValueError, TypeError):
            flash(
                "Enter valid product details, price, and minimum stock.",
                "error"
            )
            return render_template("product_form.html", product=None)

        success, message = create_product(
            product_name,
            category,
            unit,
            selling_price,
            minimum_stock
        )

        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("products"))

    return render_template("product_form.html", product=None)


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    if "username" not in session:
        return redirect(url_for("login"))

    product = get_product_by_id(product_id)

    if product is None:
        flash("Product not found or could not be loaded.", "error")
        return redirect(url_for("products"))

    if not product["is_active"]:
        flash("Inactive products cannot be edited.", "error")
        return redirect(url_for("products"))

    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip()
        category = request.form.get("category", "").strip()
        unit = request.form.get("unit", "").strip()

        try:
            selling_price = float(request.form.get("selling_price", ""))
            minimum_stock = int(request.form.get("minimum_stock", ""))

            if not product_name or not category or not unit:
                raise ValueError

            if selling_price < 0 or minimum_stock < 0:
                raise ValueError

            if not __import__("math").isfinite(selling_price):
                raise ValueError

        except (ValueError, TypeError):
            flash(
                "Enter valid product details, price, and minimum stock.",
                "error"
            )
            return render_template("product_form.html", product=product)

        success, message = update_product(
            product_id,
            product_name,
            category,
            unit,
            selling_price,
            minimum_stock
        )

        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("products"))

    return render_template("product_form.html", product=product)


@app.route("/products/<int:product_id>/deactivate", methods=["POST"])
def deactivate_product_route(product_id):
    if "username" not in session:
        return redirect(url_for("login"))

    success, message = deactivate_product(product_id)

    flash(message, "success" if success else "error")
    return redirect(url_for("products"))

# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)
