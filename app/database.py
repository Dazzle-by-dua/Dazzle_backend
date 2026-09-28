import json
import sqlite3
import datetime
from pathlib import Path
from contextlib import contextmanager
from app.config import DB_PATH, DATA_DIR, UPLOAD_DIR
from app.seed_data import (
    DEFAULT_ADMINS,
    DEFAULT_PRODUCTS,
    DEFAULT_CATEGORIES,
    DEFAULT_REVIEWS,
    DEFAULT_OFFERS,
    DEFAULT_HOMEPAGE,
    DEFAULT_ORDERS,
    DEFAULT_SETTINGS,
    DEFAULT_NAVIGATION,
    DEFAULT_PAGES
)
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def get_db_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(seed_if_empty: bool = True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Admins
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        # 2. Products
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                oldPrice REAL,
                category TEXT NOT NULL,
                rating REAL DEFAULT 5.0,
                reviews INTEGER DEFAULT 0,
                img TEXT,
                badges TEXT DEFAULT '[]',
                inStock INTEGER DEFAULT 1,
                sku TEXT,
                material TEXT,
                dimensions TEXT,
                description TEXT,
                variants TEXT DEFAULT '[]',
                images TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 3. Categories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                img TEXT,
                desc TEXT
            );
        """)

        # 4. Reviews
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rating INTEGER DEFAULT 5,
                text TEXT NOT NULL,
                date TEXT NOT NULL,
                verified INTEGER DEFAULT 1,
                approved INTEGER DEFAULT 1,
                product TEXT DEFAULT 'General',
                created_at TEXT NOT NULL
            );
        """)

        # 5. Coupons
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                id TEXT PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                discount REAL NOT NULL,
                type TEXT NOT NULL DEFAULT 'percent',
                minOrder REAL DEFAULT 0,
                expiry TEXT NOT NULL,
                desc TEXT,
                badge TEXT,
                active INTEGER DEFAULT 1
            );
        """)

        # 6. Combos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS combos (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                discount TEXT NOT NULL,
                price REAL NOT NULL,
                oldPrice REAL NOT NULL,
                items TEXT DEFAULT '[]',
                images TEXT DEFAULT '[]'
            );
        """)

        # 7. Orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                date TEXT NOT NULL,
                total REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'Processing',
                paymentMethod TEXT DEFAULT 'Cash on Delivery',
                address TEXT,
                items TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 8. Homepage
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS homepage (
                section_key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
        """)

        # 9. Settings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
        """)

        # 10. Navigation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS navigation (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
        """)

        # 11. Pages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
        """)

        # 12. Media
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                mime_type TEXT,
                created_at TEXT NOT NULL
            );
        """)

        if seed_if_empty:
            _seed_defaults_if_needed(cursor)

    sync_category_counts()

def _seed_defaults_if_needed(cursor: sqlite3.Cursor):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Seed Admins
    cursor.execute("SELECT COUNT(*) FROM admins;")
    if cursor.fetchone()[0] == 0:
        for a in DEFAULT_ADMINS:
            cursor.execute(
                """INSERT INTO admins (username, email, password_hash, name, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (a["username"], a["email"], hash_password(a["password"]), a["name"], a["role"], now_iso)
            )

    # Seed Products
    cursor.execute("SELECT COUNT(*) FROM products;")
    if cursor.fetchone()[0] == 0:
        for p in DEFAULT_PRODUCTS:
            cursor.execute(
                """INSERT INTO products (id, name, price, oldPrice, category, rating, reviews, img, badges, inStock, sku, material, dimensions, description, variants, images, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["id"],
                    p["name"],
                    p["price"],
                    p.get("oldPrice"),
                    p["category"],
                    p.get("rating", 5.0),
                    p.get("reviews", 0),
                    p.get("img"),
                    json.dumps(p.get("badges", [])),
                    1 if p.get("inStock", True) else 0,
                    p.get("sku"),
                    p.get("material"),
                    p.get("dimensions"),
                    p.get("description"),
                    json.dumps(p.get("variants", [])),
                    json.dumps(p.get("images", [])),
                    now_iso,
                    now_iso
                )
            )

    # Seed Categories
    cursor.execute("SELECT COUNT(*) FROM categories;")
    if cursor.fetchone()[0] == 0:
        for c in DEFAULT_CATEGORIES:
            cursor.execute(
                """INSERT INTO categories (id, name, count, img, desc)
                   VALUES (?, ?, ?, ?, ?)""",
                (c["id"], c["name"], c.get("count", 0), c.get("img"), c.get("desc"))
            )

    # Seed Reviews
    cursor.execute("SELECT COUNT(*) FROM reviews;")
    if cursor.fetchone()[0] == 0:
        for r in DEFAULT_REVIEWS:
            cursor.execute(
                """INSERT INTO reviews (id, name, rating, text, date, verified, approved, product, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r["id"],
                    r["name"],
                    r.get("rating", 5),
                    r.get("text", ""),
                    r.get("date", ""),
                    1 if r.get("verified", True) else 0,
                    1 if r.get("approved", True) else 0,
                    r.get("product", "General"),
                    now_iso
                )
            )

    # Seed Coupons & Combos
    cursor.execute("SELECT COUNT(*) FROM coupons;")
    if cursor.fetchone()[0] == 0:
        for cp in DEFAULT_OFFERS.get("coupons", []):
            cursor.execute(
                """INSERT INTO coupons (id, code, title, discount, type, minOrder, expiry, desc, badge, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cp["id"],
                    cp["code"],
                    cp["title"],
                    cp["discount"],
                    cp.get("type", "percent"),
                    cp.get("minOrder", 0),
                    cp.get("expiry", "2026-12-31"),
                    cp.get("desc"),
                    cp.get("badge"),
                    1 if cp.get("active", True) else 0
                )
            )

    cursor.execute("SELECT COUNT(*) FROM combos;")
    if cursor.fetchone()[0] == 0:
        for cb in DEFAULT_OFFERS.get("combos", []):
            cursor.execute(
                """INSERT INTO combos (id, name, discount, price, oldPrice, items, images)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    cb["id"],
                    cb["name"],
                    cb["discount"],
                    cb["price"],
                    cb["oldPrice"],
                    json.dumps(cb.get("items", [])),
                    json.dumps(cb.get("images", []))
                )
            )

    # Seed Orders
    cursor.execute("SELECT COUNT(*) FROM orders;")
    if cursor.fetchone()[0] == 0:
        for o in DEFAULT_ORDERS:
            cursor.execute(
                """INSERT INTO orders (id, customer, email, phone, date, total, status, paymentMethod, address, items, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    o["id"],
                    o["customer"],
                    o["email"],
                    o.get("phone"),
                    o.get("date"),
                    o["total"],
                    o.get("status", "Processing"),
                    o.get("paymentMethod", "Cash on Delivery"),
                    o.get("address"),
                    json.dumps(o.get("items", [])),
                    now_iso,
                    now_iso
                )
            )

    # Seed Homepage Sections
    cursor.execute("SELECT COUNT(*) FROM homepage;")
    if cursor.fetchone()[0] == 0:
        for sec_k, sec_v in DEFAULT_HOMEPAGE.items():
            cursor.execute(
                """INSERT INTO homepage (section_key, data) VALUES (?, ?)""",
                (sec_k, json.dumps(sec_v))
            )

    # Seed Settings
    cursor.execute("SELECT COUNT(*) FROM settings;")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """INSERT INTO settings (key, data) VALUES ('main', ?)""",
            (json.dumps(DEFAULT_SETTINGS),)
        )

    # Seed Navigation
    cursor.execute("SELECT COUNT(*) FROM navigation;")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """INSERT INTO navigation (key, data) VALUES ('main', ?)""",
            (json.dumps(DEFAULT_NAVIGATION),)
        )

    # Seed Pages
    cursor.execute("SELECT COUNT(*) FROM pages;")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            """INSERT INTO pages (key, data) VALUES ('main', ?)""",
            (json.dumps(DEFAULT_PAGES),)
        )

    # Seed Media Gallery
    cursor.execute("SELECT COUNT(*) FROM media;")
    if cursor.fetchone()[0] == 0:
        initial_media = [
            {"filename": "product_flower_necklace.jpg", "title": "Flower Pendant Necklace", "type": "Product Hero"},
            {"filename": "product_pearl_earrings.jpg", "title": "Pearl Drop Earrings", "type": "Product"},
            {"filename": "product_bracelet.jpg", "title": "Delicate Chain Bracelet", "type": "Product"},
            {"filename": "product_ring.jpg", "title": "Minimal Diamond Ring", "type": "Product"},
            {"filename": "hero_necklace.jpg", "title": "Luxury Model Hero", "type": "Hero Banner"},
            {"filename": "featured_collection.jpg", "title": "Grace Collection Banner", "type": "Collection Banner"},
            {"filename": "marble_bg.jpg", "title": "Luxury Marble Texture", "type": "Background"}
        ]
        for m in initial_media:
            fpath = UPLOAD_DIR / m["filename"]
            fsize = fpath.stat().st_size if fpath.exists() else 0
            cursor.execute(
                """INSERT INTO media (filename, title, type, url, size, mime_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    m["filename"],
                    m["title"],
                    m["type"],
                    f"/uploads/{m['filename']}",
                    fsize,
                    "image/jpeg",
                    now_iso
                )
            )

def sync_category_counts():
    """Recalculates product counts for each category to keep store accurate"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT category, COUNT(*) as cnt
            FROM products
            GROUP BY category;
        """)
        counts = {row["category"].lower(): row["cnt"] for row in cursor.fetchall()}

        cursor.execute("SELECT id FROM categories;")
        cats = [row["id"] for row in cursor.fetchall()]

        for c_id in cats:
            cnt = counts.get(c_id.lower(), 0)
            cursor.execute("UPDATE categories SET count = ? WHERE id = ?;", (cnt, c_id))

def export_all_data() -> dict:
    """Exact mirror of DazzleStore.exportAll()"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Products
        cursor.execute("SELECT * FROM products ORDER BY id DESC;")
        prods = []
        for r in cursor.fetchall():
            prods.append({
                "id": r["id"],
                "name": r["name"],
                "price": r["price"],
                "oldPrice": r["oldPrice"],
                "category": r["category"],
                "rating": r["rating"],
                "reviews": r["reviews"],
                "img": r["img"],
                "badges": json.loads(r["badges"]) if r["badges"] else [],
                "inStock": bool(r["inStock"]),
                "sku": r["sku"],
                "material": r["material"],
                "dimensions": r["dimensions"],
                "description": r["description"],
                "variants": json.loads(r["variants"]) if r["variants"] else [],
                "images": json.loads(r["images"]) if r["images"] else []
            })

        # Categories
        cursor.execute("SELECT * FROM categories;")
        cats = [{"id": r["id"], "name": r["name"], "count": r["count"], "img": r["img"], "desc": r["desc"]} for r in cursor.fetchall()]

        # Reviews
        cursor.execute("SELECT * FROM reviews ORDER BY id DESC;")
        revs = []
        for r in cursor.fetchall():
            revs.append({
                "id": r["id"],
                "name": r["name"],
                "rating": r["rating"],
                "text": r["text"],
                "date": r["date"],
                "verified": bool(r["verified"]),
                "approved": bool(r["approved"]),
                "product": r["product"]
            })

        # Offers
        cursor.execute("SELECT * FROM coupons;")
        cps = []
        for r in cursor.fetchall():
            cps.append({
                "id": r["id"],
                "code": r["code"],
                "title": r["title"],
                "discount": r["discount"],
                "type": r["type"],
                "minOrder": r["minOrder"],
                "expiry": r["expiry"],
                "desc": r["desc"],
                "badge": r["badge"],
                "active": bool(r["active"])
            })

        cursor.execute("SELECT * FROM combos;")
        cbs = []
        for r in cursor.fetchall():
            cbs.append({
                "id": r["id"],
                "name": r["name"],
                "discount": r["discount"],
                "price": r["price"],
                "oldPrice": r["oldPrice"],
                "items": json.loads(r["items"]) if r["items"] else [],
                "images": json.loads(r["images"]) if r["images"] else []
            })

        offers = {"coupons": cps, "combos": cbs}

        # Homepage
        cursor.execute("SELECT section_key, data FROM homepage;")
        homepage = {}
        for r in cursor.fetchall():
            homepage[r["section_key"]] = json.loads(r["data"])

        # Orders
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC;")
        orders = []
        for r in cursor.fetchall():
            orders.append({
                "id": r["id"],
                "customer": r["customer"],
                "email": r["email"],
                "phone": r["phone"],
                "date": r["date"],
                "total": r["total"],
                "status": r["status"],
                "paymentMethod": r["paymentMethod"],
                "address": r["address"],
                "items": json.loads(r["items"]) if r["items"] else []
            })

        # Settings
        cursor.execute("SELECT data FROM settings WHERE key = 'main';")
        set_row = cursor.fetchone()
        settings = json.loads(set_row["data"]) if set_row else DEFAULT_SETTINGS

        # Navigation
        cursor.execute("SELECT data FROM navigation WHERE key = 'main';")
        nav_row = cursor.fetchone()
        navigation = json.loads(nav_row["data"]) if nav_row else DEFAULT_NAVIGATION

        return {
            "products": prods,
            "categories": cats,
            "reviews": revs,
            "offers": offers,
            "homepage": homepage,
            "orders": orders,
            "settings": settings,
            "navigation": navigation
        }

def import_all_data(data: dict) -> bool:
    """Exact mirror of DazzleStore.importAll()"""
    try:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.cursor()

            if "products" in data and isinstance(data["products"], list):
                cursor.execute("DELETE FROM products;")
                for p in data["products"]:
                    cursor.execute(
                        """INSERT INTO products (id, name, price, oldPrice, category, rating, reviews, img, badges, inStock, sku, material, dimensions, description, variants, images, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            p["id"],
                            p["name"],
                            p["price"],
                            p.get("oldPrice"),
                            p.get("category", "all"),
                            p.get("rating", 5.0),
                            p.get("reviews", 0),
                            p.get("img"),
                            json.dumps(p.get("badges", [])),
                            1 if p.get("inStock", True) else 0,
                            p.get("sku"),
                            p.get("material"),
                            p.get("dimensions"),
                            p.get("description"),
                            json.dumps(p.get("variants", [])),
                            json.dumps(p.get("images", [])),
                            now_iso,
                            now_iso
                        )
                    )

            if "categories" in data and isinstance(data["categories"], list):
                cursor.execute("DELETE FROM categories;")
                for c in data["categories"]:
                    cursor.execute(
                        """INSERT INTO categories (id, name, count, img, desc)
                           VALUES (?, ?, ?, ?, ?)""",
                        (c["id"], c["name"], c.get("count", 0), c.get("img"), c.get("desc"))
                    )

            if "reviews" in data and isinstance(data["reviews"], list):
                cursor.execute("DELETE FROM reviews;")
                for r in data["reviews"]:
                    cursor.execute(
                        """INSERT INTO reviews (id, name, rating, text, date, verified, approved, product, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            r["id"],
                            r["name"],
                            r.get("rating", 5),
                            r.get("text", ""),
                            r.get("date", ""),
                            1 if r.get("verified", True) else 0,
                            1 if r.get("approved", True) else 0,
                            r.get("product", "General"),
                            now_iso
                        )
                    )

            if "offers" in data and isinstance(data["offers"], dict):
                if "coupons" in data["offers"]:
                    cursor.execute("DELETE FROM coupons;")
                    for cp in data["offers"]["coupons"]:
                        cursor.execute(
                            """INSERT INTO coupons (id, code, title, discount, type, minOrder, expiry, desc, badge, active)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                cp["id"],
                                cp["code"],
                                cp["title"],
                                cp["discount"],
                                cp.get("type", "percent"),
                                cp.get("minOrder", 0),
                                cp.get("expiry", "2026-12-31"),
                                cp.get("desc"),
                                cp.get("badge"),
                                1 if cp.get("active", True) else 0
                            )
                        )
                if "combos" in data["offers"]:
                    cursor.execute("DELETE FROM combos;")
                    for cb in data["offers"]["combos"]:
                        cursor.execute(
                            """INSERT INTO combos (id, name, discount, price, oldPrice, items, images)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                cb["id"],
                                cb["name"],
                                cb["discount"],
                                cb["price"],
                                cb["oldPrice"],
                                json.dumps(cb.get("items", [])),
                                json.dumps(cb.get("images", []))
                            )
                        )

            if "homepage" in data and isinstance(data["homepage"], dict):
                cursor.execute("DELETE FROM homepage;")
                for k, v in data["homepage"].items():
                    cursor.execute(
                        """INSERT INTO homepage (section_key, data) VALUES (?, ?)""",
                        (k, json.dumps(v))
                    )

            if "orders" in data and isinstance(data["orders"], list):
                cursor.execute("DELETE FROM orders;")
                for o in data["orders"]:
                    cursor.execute(
                        """INSERT INTO orders (id, customer, email, phone, date, total, status, paymentMethod, address, items, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            o["id"],
                            o["customer"],
                            o["email"],
                            o.get("phone"),
                            o.get("date"),
                            o["total"],
                            o.get("status", "Processing"),
                            o.get("paymentMethod", "Cash on Delivery"),
                            o.get("address"),
                            json.dumps(o.get("items", [])),
                            now_iso,
                            now_iso
                        )
                    )

            if "settings" in data and isinstance(data["settings"], dict):
                cursor.execute(
                    """INSERT OR REPLACE INTO settings (key, data) VALUES ('main', ?)""",
                    (json.dumps(data["settings"]),)
                )

            if "navigation" in data and isinstance(data["navigation"], dict):
                cursor.execute(
                    """INSERT OR REPLACE INTO navigation (key, data) VALUES ('main', ?)""",
                    (json.dumps(data["navigation"]),)
                )

        sync_category_counts()
        return True
    except Exception as e:
        print("Import error:", e)
        return False

def reset_all_data():
    """Exact mirror of DazzleStore.resetAll()"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM products;")
        cursor.execute("DELETE FROM categories;")
        cursor.execute("DELETE FROM reviews;")
        cursor.execute("DELETE FROM coupons;")
        cursor.execute("DELETE FROM combos;")
        cursor.execute("DELETE FROM orders;")
        cursor.execute("DELETE FROM homepage;")
        cursor.execute("DELETE FROM settings;")
        cursor.execute("DELETE FROM navigation;")
        cursor.execute("DELETE FROM pages;")
        cursor.execute("DELETE FROM media;")
        _seed_defaults_if_needed(cursor)

    sync_category_counts()
