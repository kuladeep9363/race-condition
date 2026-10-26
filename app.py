import os
import secrets
import sqlite3
import time
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for, g

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "hackmart.db"
FLAG_PATH = BASE_DIR / "FLAG.txt"

app = Flask(__name__)
app.secret_key = os.environ.get("HACKMART_SECRET", "local-ctf-secret-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


PRODUCTS = [
    {"id": "keyboard", "name": "Mechanical Keyboard", "price": 120, "category": "Accessories", "description": "A compact mechanical keyboard for everyday work.", "image": "keyboard.svg"},
    {"id": "mouse", "name": "Wireless Mouse", "price": 80, "category": "Accessories", "description": "A reliable wireless mouse with a comfortable grip.", "image": "mouse.svg"},
    {"id": "usb", "name": "USB Drive", "price": 90, "category": "Storage", "description": "Portable storage for files and backups.", "image": "usb.svg"},
    {"id": "monitor", "name": "HD Monitor", "price": 450, "category": "Displays", "description": "A crisp display for work, study, and entertainment.", "image": "monitor.svg"},
    {"id": "headphones", "name": "Studio Headphones", "price": 300, "category": "Audio", "description": "Comfortable over-ear headphones for focused listening.", "image": "headphones.svg"},
    {"id": "webcam", "name": "HD Webcam", "price": 250, "category": "Accessories", "description": "A simple webcam for meetings and streaming.", "image": "webcam.svg"},
    {"id": "ssd", "name": "Portable SSD", "price": 600, "category": "Storage", "description": "Fast external storage in a compact form.", "image": "ssd.svg"},
    {"id": "stand", "name": "Laptop Stand", "price": 150, "category": "Workspace", "description": "A sturdy stand to improve your desk setup.", "image": "stand.svg"},
    {"id": "powerbank", "name": "Power Bank", "price": 500, "category": "Power", "description": "Extra power when you are away from a socket.", "image": "powerbank.svg"},
    {"id": "router", "name": "Wi-Fi Router", "price": 700, "category": "Networking", "description": "A dependable router for a connected home.", "image": "router.svg"},
    {"id": "flag", "name": "FLAG.txt", "price": 1000, "category": "Challenge item", "description": "A restricted digital item. Purchase it to complete the challenge.", "image": None},
]
PRODUCT_BY_ID = {p["id"]: p for p in PRODUCTS}


def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with connect_db() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            wallet INTEGER NOT NULL DEFAULT 200,
            coupon_claimed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, product_id)
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_id TEXT NOT NULL,
            price INTEGER NOT NULL,
            purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        db.commit()


def current_user():
    if hasattr(g, "current_user"):
        return g.current_user
    sid = request.cookies.get("hackmart_session")
    
    if not sid:
        g.current_user = None
        return None
    with connect_db() as db:
        row = db.execute(
            "SELECT users.id, users.username, users.wallet, users.coupon_claimed "
            "FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.session_id = ?",
            (sid,),
        ).fetchone()
    g.current_user = dict(row) if row else None
    return g.current_user


@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "products_count": len(PRODUCTS)}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Sign in to continue.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def create_session(user_id):
    sid = secrets.token_urlsafe(32)
    with connect_db() as db:
        db.execute("INSERT INTO sessions (session_id, user_id) VALUES (?, ?)", (sid, user_id))
        db.commit()
    return sid


@app.get("/")
def index():
    return redirect(url_for("marketplace"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 32 or not username.replace("_", "").isalnum():
            flash("Username must be 3–32 characters and contain only letters, numbers, or underscores.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template("register.html")
        # Werkzeug's password hashing keeps stored passwords out of plaintext.
        from werkzeug.security import generate_password_hash
        try:
            with connect_db() as db:
                cur = db.execute(
                    "INSERT INTO users (username, password_hash, wallet) VALUES (?, ?, 200)",
                    (username, generate_password_hash(password)),
                )
                user_id = cur.lastrowid
                db.commit()
            sid = create_session(user_id)
            response = redirect(url_for("marketplace"))
            response.set_cookie("hackmart_session", sid, httponly=True, samesite="Lax", secure=request.is_secure, path="/")
            flash("Account created. ₹200 welcome credit added to your wallet.", "success")
            return response
        except sqlite3.IntegrityError:
            flash("That username is already taken.", "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        from werkzeug.security import check_password_hash
        with connect_db() as db:
            user = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            sid = create_session(user["id"])
            response = redirect(url_for("marketplace"))
            response.set_cookie("hackmart_session", sid, httponly=True, samesite="Lax", secure=request.is_secure, path="/")
            return response
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    sid = request.cookies.get("hackmart_session")
    if sid:
        with connect_db() as db:
            db.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            db.commit()
    response = redirect(url_for("login"))
    response.delete_cookie("hackmart_session", path="/")
    return response


@app.get("/market")
def marketplace():
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 4
    start = (page - 1) * per_page
    visible_products = PRODUCTS[start:start + per_page]
    max_page = (len(PRODUCTS) + per_page - 1) // per_page
    if page > max_page:
        page = max_page
        start = (page - 1) * per_page
        visible_products = PRODUCTS[start:start + per_page]
    return render_template("market.html", products=visible_products, page=page, max_page=max_page)


@app.get("/product/<product_id>")
def product_detail(product_id):
    product = PRODUCT_BY_ID.get(product_id)
    if not product:
        abort(404)
    return render_template("product.html", product=product)


@app.get("/wallet")
@login_required
def wallet():
    user = current_user()
    with connect_db() as db:
        purchases = db.execute(
            "SELECT purchases.product_id, purchases.price, purchases.purchased_at "
            "FROM purchases WHERE user_id = ? ORDER BY purchases.id DESC", (user["id"],)
        ).fetchall()
        owned_rows = db.execute(
            "SELECT product_id, quantity FROM inventory WHERE user_id = ?", (user["id"],)
        ).fetchall()
    owned = [{**PRODUCT_BY_ID[r["product_id"]], "quantity": r["quantity"]} for r in owned_rows if r["product_id"] in PRODUCT_BY_ID]
    history = [{**PRODUCT_BY_ID[r["product_id"]], "price_paid": r["price"], "purchased_at": r["purchased_at"]}
               for r in purchases if r["product_id"] in PRODUCT_BY_ID]
    return render_template("wallet.html", owned=owned, history=history)


@app.get("/coupon")
@login_required
def coupon():
    return render_template("coupon.html")


@app.post("/claim")
@login_required
def claim_coupon():
    user_id = current_user()["id"]

    # INTENTIONALLY VULNERABLE CTF LOGIC:
    # The eligibility check and the wallet/claim update are separate operations.
    # Concurrent requests can all read coupon_claimed=0 before any request marks it claimed.
    with connect_db() as db:
        row = db.execute("SELECT coupon_claimed FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["coupon_claimed"]:
        flash("Coupon already claimed. Each account can claim it once.", "error")
        return redirect(url_for("coupon"))

    # Makes the race window reliable for a local training challenge.
    time.sleep(0.35)

    with connect_db() as db:
        db.execute("UPDATE users SET wallet = wallet + 100, coupon_claimed = 1 WHERE id = ?", (user_id,))
        db.commit()

    flash("Coupon redeemed: ₹100 added to your wallet.", "success")
    return redirect(url_for("coupon"))


@app.post("/buy/<product_id>")
@login_required
def buy_product(product_id):
    product = PRODUCT_BY_ID.get(product_id)
    if not product:
        abort(404)
    user_id = current_user()["id"]

    # Purchases are deliberately handled atomically; only the coupon route is vulnerable.
    db = connect_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT wallet FROM users WHERE id = ?", (user_id,)).fetchone()
        already_owned = db.execute(
            "SELECT quantity FROM inventory WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        ).fetchone()
        if not user:
            db.rollback()
            abort(401)
        if user["wallet"] < product["price"]:
            db.rollback()
            flash("Insufficient funds. Earn more credits before buying this item.", "error")
            return redirect(url_for("marketplace", page=3 if product_id == "flag" else 1))
        db.execute("UPDATE users SET wallet = wallet - ? WHERE id = ?", (product["price"], user_id))
        db.execute(
            "INSERT INTO inventory (user_id, product_id, quantity) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = quantity + 1",
            (user_id, product_id),
        )
        db.execute(
            "INSERT INTO purchases (user_id, product_id, price) VALUES (?, ?, ?)",
            (user_id, product_id, product["price"]),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    
    if product_id == "flag":
    	return redirect(url_for("download_flag"))

    # Download the purchased product's SVG illustration.
    image_path = BASE_DIR / "static" / "images" / product["image"]

    return send_file(image_path, as_attachment=True, download_name=product["image"], mimetype="image/svg+xml")


@app.get("/download/flag")
@login_required
def download_flag():
    user_id = current_user()["id"]
    with connect_db() as db:
        owned = db.execute(
            "SELECT 1 FROM inventory WHERE user_id = ? AND product_id = 'flag' AND quantity > 0",
            (user_id,),
        ).fetchone()
    if not owned:
        flash("Purchase FLAG.txt before downloading it.", "error")
        return redirect(url_for("marketplace", page=3))
    if not FLAG_PATH.exists():
        FLAG_PATH.write_text("flag{hackmart_coupon_race_condition}\n", encoding="utf-8")
    return send_file(FLAG_PATH, as_attachment=True, download_name="FLAG.txt", mimetype="text/plain")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="That page or product could not be found."), 404


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
