import os
from dotenv import load_dotenv

load_dotenv()
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


from database import (
    create_user,
    get_user_by_username,
    get_inventory,
    add_stock,
    get_active_products,
    get_customers,
    create_sale,
    get_sales_history,
    get_sale_details
)


app = Flask(__name__)

# Change this to a private, random secret before deployment.
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is missing from .env")


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
        session["full_name"] = user.get("full_name") or user["username"]
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

    return render_template(
        "dashboard.html",
        username=session.get("username"),
        full_name=session.get("full_name"),
        role=session.get("role")
    )


# =========================================================
# INVENTORY
# =========================================================

@app.route("/inventory")
def inventory():

    if "username" not in session:
        return redirect(url_for("login"))

    products = get_inventory()
    print("Inventory data:", products)
    print("Number of products:", len(products) if products else 0)

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
        product_id = request.form.get("product_id", "").strip()
        quantity_text = request.form.get("quantity", "").strip()

        try:
            if not product_id or not quantity_text:
                raise ValueError("Please select a product and enter a quantity.")

            product_id = int(product_id)
            quantity = int(quantity_text)

            if product_id <= 0:
                raise ValueError("Please select a valid product.")

            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")

            success, result_message = add_stock(product_id, quantity)

            message = result_message
            message_type = "success" if success else "error"

        except ValueError as error:
            message = str(error)
            message_type = "error"

    products = get_inventory()

    if products is None:
        products = []
        message = message or "Unable to load products. Check the database connection."
        message_type = "error"

    return render_template(
        "add_stock.html",
        products=products,
        message=message,
        message_type=message_type
    )

# =========================================================
# SALES & BILLING
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


@app.route("/sales/new", methods=["GET", "POST"])
def new_sale():
    if "username" not in session:
        return redirect(url_for("login"))

    message = None
    message_type = None

    if request.method == "POST":
        customer_text = request.form.get("customer_id", "").strip()
        payment_method = request.form.get("payment_method", "").strip()
        discount_text = request.form.get("discount", "0").strip()

        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("quantity")

        try:
            customer_id = int(customer_text) if customer_text else None

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

            success, result_message, sale_id = create_sale(
                customer_id=customer_id,
                payment_method=payment_method,
                discount=discount_text,
                items=items,
                created_by=session.get("user_id")
            )

            if success:
                return redirect(url_for("sale_bill", sale_id=sale_id))

            message = result_message
            message_type = "error"

        except (ValueError, TypeError):
            message = (
                "Please check the selected customer, products, "
                "quantities, and discount."
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