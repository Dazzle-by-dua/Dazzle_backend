import os
import re
import datetime
import logging
from typing import Optional, Dict, Any, List
import bcrypt
from app.config import MONGODB_URI, MONGODB_DB, UPLOAD_DIR
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

logger = logging.getLogger("dazzle.database")

def _sanitize_error(msg: Any) -> str:
    """Mask any MongoDB credentials or sensitive URI patterns from messages."""
    return re.sub(r'mongodb(?:\+srv)?://[^@\s]+@', 'mongodb+srv://***:***@', str(msg))

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def clean_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    d = dict(doc)
    d.pop("_id", None)
    return d

def clean_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [clean_doc(d) for d in docs if d is not None]

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.is_connected = False
        self.is_mock = False
        self.connection_error = None

    async def connect(self):
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        if MONGODB_URI:
            print("MongoDB configuration detected")
            logger.info("MongoDB configuration detected")
            print(f"MongoDB database: {MONGODB_DB}")
            logger.info(f"MongoDB database: {MONGODB_DB}")
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                self.client = AsyncIOMotorClient(
                    MONGODB_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=10000,
                    maxPoolSize=50,
                    minPoolSize=5
                )
                self.db = self.client[MONGODB_DB]
                await self.client.admin.command("ping")
                self.is_connected = True
                self.is_mock = False
                self.connection_error = None
                print("MongoDB connection successful")
                logger.info("MongoDB connection successful")
            except Exception as e:
                self.is_connected = False
                safe_err = _sanitize_error(e)
                self.connection_error = safe_err
                print(f"MongoDB connection failed: {safe_err}")
                logger.error(f"MongoDB connection failed: {safe_err}")
        else:
            print("MongoDB configuration detected: None (URI not provided)")
            logger.warning("MongoDB configuration detected: None (URI not provided)")
            print(f"MongoDB database: {MONGODB_DB}")
            logger.info(f"MongoDB database: {MONGODB_DB}")
            from mongomock_motor import AsyncMongoMockClient
            self.client = AsyncMongoMockClient()
            self.db = self.client[MONGODB_DB]
            self.is_connected = False
            self.is_mock = True
            self.connection_error = "MONGODB_URI not provided"
            print("MongoDB connection failed: MONGODB_URI not provided")
            logger.warning("MongoDB connection failed: MONGODB_URI not provided")

        if self.is_connected or self.is_mock:
            try:
                await self._create_indexes()
                await self._seed_defaults_if_needed()
                await self.sync_category_counts()
            except Exception as e:
                logger.warning(f"Initial index/seed skipped: {_sanitize_error(e)}")

    async def close(self):
        if self.client:
            self.client.close()
            self.is_connected = False
            logger.info("MongoDB client connection pool closed.")

    async def check_health(self) -> Dict[str, Any]:
        if not self.client and MONGODB_URI:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                self.client = AsyncIOMotorClient(
                    MONGODB_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=10000,
                    maxPoolSize=50,
                    minPoolSize=5
                )
                self.db = self.client[MONGODB_DB]
            except Exception as e:
                self.is_connected = False
                return {
                    "status": "disconnected",
                    "connected": False,
                    "database": MONGODB_DB,
                    "error": _sanitize_error(e)
                }

        if not self.client or self.is_mock:
            return {
                "status": "disconnected",
                "connected": False,
                "database": MONGODB_DB,
                "error": self.connection_error or "MongoDB not configured"
            }

        try:
            await self.client.admin.command("ping")
            self.is_connected = True
            return {
                "status": "connected",
                "connected": True,
                "database": MONGODB_DB
            }
        except Exception as e:
            self.is_connected = False
            return {
                "status": "disconnected",
                "connected": False,
                "database": MONGODB_DB,
                "error": _sanitize_error(e)
            }

    def get_db(self):
        if self.db is None:
            if MONGODB_URI:
                from motor.motor_asyncio import AsyncIOMotorClient
                self.client = AsyncIOMotorClient(
                    MONGODB_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=10000,
                    maxPoolSize=50,
                    minPoolSize=5
                )
                self.db = self.client[MONGODB_DB]
            else:
                from mongomock_motor import AsyncMongoMockClient
                self.client = AsyncMongoMockClient()
                self.db = self.client[MONGODB_DB]
                self.is_connected = True
                self.is_mock = True
        return self.db

    async def _create_indexes(self):
        try:
            await self.db.admins.create_index("username", unique=True)
            await self.db.admins.create_index("email", unique=True)
            await self.db.products.create_index("id", unique=True)
            await self.db.products.create_index("category")
            await self.db.categories.create_index("id", unique=True)
            await self.db.orders.create_index("id", unique=True)
            await self.db.reviews.create_index("id", unique=True)
            await self.db.coupons.create_index("code", unique=True)
            await self.db.combos.create_index("id", unique=True)
            await self.db.media.create_index("filename", unique=True)
        except Exception as e:
            logger.warning(f"Index creation notice: {e}")

    async def _seed_defaults_if_needed(self):
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Admins
        if await self.db.admins.count_documents({}) == 0:
            for a in DEFAULT_ADMINS:
                await self.db.admins.insert_one({
                    "username": a["username"],
                    "email": a["email"],
                    "password_hash": hash_password(a["password"]),
                    "name": a["name"],
                    "role": a["role"],
                    "created_at": now_iso
                })

        # 2. Products
        if await self.db.products.count_documents({}) == 0:
            for p in DEFAULT_PRODUCTS:
                doc = {
                    "id": p["id"],
                    "name": p["name"],
                    "price": float(p["price"]),
                    "oldPrice": float(p["oldPrice"]) if p.get("oldPrice") is not None else None,
                    "category": p["category"],
                    "rating": float(p.get("rating", 5.0)),
                    "reviews": int(p.get("reviews", 0)),
                    "img": p.get("img"),
                    "badges": list(p.get("badges", [])),
                    "inStock": bool(p.get("inStock", True)),
                    "sku": p.get("sku"),
                    "material": p.get("material"),
                    "dimensions": p.get("dimensions"),
                    "description": p.get("description"),
                    "variants": list(p.get("variants", [])),
                    "images": list(p.get("images", [])),
                    "created_at": now_iso,
                    "updated_at": now_iso
                }
                await self.db.products.insert_one(doc)

        # 3. Categories
        if await self.db.categories.count_documents({}) == 0:
            for c in DEFAULT_CATEGORIES:
                await self.db.categories.insert_one({
                    "id": c["id"],
                    "name": c["name"],
                    "count": int(c.get("count", 0)),
                    "img": c.get("img"),
                    "desc": c.get("desc")
                })

        # 4. Reviews
        if await self.db.reviews.count_documents({}) == 0:
            for r in DEFAULT_REVIEWS:
                await self.db.reviews.insert_one({
                    "id": int(r["id"]),
                    "name": r["name"],
                    "rating": int(r.get("rating", 5)),
                    "text": r.get("text", ""),
                    "date": r.get("date", ""),
                    "verified": bool(r.get("verified", True)),
                    "approved": bool(r.get("approved", True)),
                    "product": r.get("product", "General"),
                    "created_at": now_iso
                })

        # 5. Offers (Coupons & Combos)
        if await self.db.coupons.count_documents({}) == 0:
            for cp in DEFAULT_OFFERS.get("coupons", []):
                await self.db.coupons.insert_one({
                    "id": cp["id"],
                    "code": cp["code"].upper(),
                    "title": cp["title"],
                    "discount": float(cp["discount"]),
                    "type": cp.get("type", "percent"),
                    "minOrder": float(cp.get("minOrder", 0)),
                    "expiry": cp.get("expiry", "2026-12-31"),
                    "desc": cp.get("desc"),
                    "badge": cp.get("badge"),
                    "active": bool(cp.get("active", True))
                })

        if await self.db.combos.count_documents({}) == 0:
            for cb in DEFAULT_OFFERS.get("combos", []):
                await self.db.combos.insert_one({
                    "id": cb["id"],
                    "name": cb["name"],
                    "discount": cb["discount"],
                    "price": float(cb["price"]),
                    "oldPrice": float(cb["oldPrice"]),
                    "items": list(cb.get("items", [])),
                    "images": list(cb.get("images", []))
                })

        # 6. Orders
        if await self.db.orders.count_documents({}) == 0:
            for o in DEFAULT_ORDERS:
                await self.db.orders.insert_one({
                    "id": o["id"],
                    "customer": o["customer"],
                    "email": o["email"],
                    "phone": o.get("phone", ""),
                    "date": o.get("date", ""),
                    "total": float(o["total"]),
                    "status": o.get("status", "Processing"),
                    "paymentMethod": o.get("paymentMethod", "Cash on Delivery"),
                    "address": o.get("address", ""),
                    "items": list(o.get("items", [])),
                    "created_at": now_iso,
                    "updated_at": now_iso
                })

        # 7. Homepage Sections
        if await self.db.homepage.count_documents({}) == 0:
            for sec_k, sec_v in DEFAULT_HOMEPAGE.items():
                await self.db.homepage.update_one(
                    {"section_key": sec_k},
                    {"$set": {"section_key": sec_k, "data": sec_v}},
                    upsert=True
                )

        # 8. Settings
        if await self.db.settings.count_documents({"key": "main"}) == 0:
            await self.db.settings.update_one(
                {"key": "main"},
                {"$set": {"key": "main", "data": DEFAULT_SETTINGS}},
                upsert=True
            )

        # 9. Navigation
        if await self.db.navigation.count_documents({"key": "main"}) == 0:
            await self.db.navigation.update_one(
                {"key": "main"},
                {"$set": {"key": "main", "data": DEFAULT_NAVIGATION}},
                upsert=True
            )

        # 10. Pages
        if await self.db.pages.count_documents({"key": "main"}) == 0:
            await self.db.pages.update_one(
                {"key": "main"},
                {"$set": {"key": "main", "data": DEFAULT_PAGES}},
                upsert=True
            )

        # 11. Media
        if await self.db.media.count_documents({}) == 0:
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
                await self.db.media.insert_one({
                    "filename": m["filename"],
                    "title": m["title"],
                    "type": m["type"],
                    "url": f"/uploads/{m['filename']}",
                    "size": fsize,
                    "mime_type": "image/jpeg",
                    "created_at": now_iso
                })

    async def sync_category_counts(self):
        """Recalculates product count for each category"""
        cats = await self.db.categories.find({}).to_list(length=100)
        for c in cats:
            cat_id = c["id"]
            cnt = await self.db.products.count_documents({"category": {"$regex": f"^{cat_id}$", "$options": "i"}})
            await self.db.categories.update_one({"id": cat_id}, {"$set": {"count": cnt}})

# Singleton manager
db_manager = DatabaseManager()

def get_database():
    return db_manager.get_db()

async def init_db():
    await db_manager.connect()

async def close_db():
    await db_manager.close()

async def check_db_health():
    return await db_manager.check_health()

async def sync_category_counts():
    await db_manager.sync_category_counts()

# ========================================================
# Backup / Restore / Reset operations on MongoDB
# ========================================================
async def export_all_data() -> Dict[str, Any]:
    db = get_database()
    prods = clean_docs(await db.products.find({}).sort("id", -1).to_list(length=1000))
    cats = clean_docs(await db.categories.find({}).to_list(length=100))
    revs = clean_docs(await db.reviews.find({}).sort("id", -1).to_list(length=1000))
    coupons = clean_docs(await db.coupons.find({}).to_list(length=100))
    combos = clean_docs(await db.combos.find({}).to_list(length=100))
    orders = clean_docs(await db.orders.find({}).sort("created_at", -1).to_list(length=1000))

    hp_docs = await db.homepage.find({}).to_list(length=100)
    homepage = {doc["section_key"]: doc["data"] for doc in hp_docs if "section_key" in doc and "data" in doc}

    set_doc = await db.settings.find_one({"key": "main"})
    settings = set_doc["data"] if set_doc and "data" in set_doc else DEFAULT_SETTINGS

    nav_doc = await db.navigation.find_one({"key": "main"})
    navigation = nav_doc["data"] if nav_doc and "data" in nav_doc else DEFAULT_NAVIGATION

    return {
        "products": prods,
        "categories": cats,
        "reviews": revs,
        "offers": {"coupons": coupons, "combos": combos},
        "homepage": homepage,
        "orders": orders,
        "settings": settings,
        "navigation": navigation
    }

async def import_all_data(data: Dict[str, Any]) -> bool:
    try:
        db = get_database()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if "products" in data and isinstance(data["products"], list):
            await db.products.delete_many({})
            for p in data["products"]:
                doc = {
                    "id": p["id"],
                    "name": p["name"],
                    "price": float(p["price"]),
                    "oldPrice": float(p["oldPrice"]) if p.get("oldPrice") is not None else None,
                    "category": p.get("category", "all"),
                    "rating": float(p.get("rating", 5.0)),
                    "reviews": int(p.get("reviews", 0)),
                    "img": p.get("img"),
                    "badges": list(p.get("badges", [])),
                    "inStock": bool(p.get("inStock", True)),
                    "sku": p.get("sku"),
                    "material": p.get("material"),
                    "dimensions": p.get("dimensions"),
                    "description": p.get("description"),
                    "variants": list(p.get("variants", [])),
                    "images": list(p.get("images", [])),
                    "created_at": now_iso,
                    "updated_at": now_iso
                }
                await db.products.insert_one(doc)

        if "categories" in data and isinstance(data["categories"], list):
            await db.categories.delete_many({})
            for c in data["categories"]:
                await db.categories.insert_one({
                    "id": c["id"],
                    "name": c["name"],
                    "count": int(c.get("count", 0)),
                    "img": c.get("img"),
                    "desc": c.get("desc")
                })

        if "reviews" in data and isinstance(data["reviews"], list):
            await db.reviews.delete_many({})
            for r in data["reviews"]:
                await db.reviews.insert_one({
                    "id": int(r["id"]),
                    "name": r["name"],
                    "rating": int(r.get("rating", 5)),
                    "text": r.get("text", ""),
                    "date": r.get("date", ""),
                    "verified": bool(r.get("verified", True)),
                    "approved": bool(r.get("approved", True)),
                    "product": r.get("product", "General"),
                    "created_at": now_iso
                })

        if "offers" in data and isinstance(data["offers"], dict):
            if "coupons" in data["offers"]:
                await db.coupons.delete_many({})
                for cp in data["offers"]["coupons"]:
                    await db.coupons.insert_one({
                        "id": cp["id"],
                        "code": cp["code"].upper(),
                        "title": cp["title"],
                        "discount": float(cp["discount"]),
                        "type": cp.get("type", "percent"),
                        "minOrder": float(cp.get("minOrder", 0)),
                        "expiry": cp.get("expiry", "2026-12-31"),
                        "desc": cp.get("desc"),
                        "badge": cp.get("badge"),
                        "active": bool(cp.get("active", True))
                    })
            if "combos" in data["offers"]:
                await db.combos.delete_many({})
                for cb in data["offers"]["combos"]:
                    await db.combos.insert_one({
                        "id": cb["id"],
                        "name": cb["name"],
                        "discount": cb["discount"],
                        "price": float(cb["price"]),
                        "oldPrice": float(cb["oldPrice"]),
                        "items": list(cb.get("items", [])),
                        "images": list(cb.get("images", []))
                    })

        if "homepage" in data and isinstance(data["homepage"], dict):
            await db.homepage.delete_many({})
            for k, v in data["homepage"].items():
                await db.homepage.update_one({"section_key": k}, {"$set": {"section_key": k, "data": v}}, upsert=True)

        if "orders" in data and isinstance(data["orders"], list):
            await db.orders.delete_many({})
            for o in data["orders"]:
                await db.orders.insert_one({
                    "id": o["id"],
                    "customer": o["customer"],
                    "email": o["email"],
                    "phone": o.get("phone", ""),
                    "date": o.get("date", ""),
                    "total": float(o["total"]),
                    "status": o.get("status", "Processing"),
                    "paymentMethod": o.get("paymentMethod", "Cash on Delivery"),
                    "address": o.get("address", ""),
                    "items": list(o.get("items", [])),
                    "created_at": now_iso,
                    "updated_at": now_iso
                })

        if "settings" in data and isinstance(data["settings"], dict):
            await db.settings.update_one({"key": "main"}, {"$set": {"key": "main", "data": data["settings"]}}, upsert=True)

        if "navigation" in data and isinstance(data["navigation"], dict):
            await db.navigation.update_one({"key": "main"}, {"$set": {"key": "main", "data": data["navigation"]}}, upsert=True)

        await db_manager.sync_category_counts()
        return True
    except Exception as e:
        logger.error(f"MongoDB import error: {e}")
        return False

async def reset_all_data():
    db = get_database()
    await db.products.delete_many({})
    await db.categories.delete_many({})
    await db.reviews.delete_many({})
    await db.coupons.delete_many({})
    await db.combos.delete_many({})
    await db.orders.delete_many({})
    await db.homepage.delete_many({})
    await db.settings.delete_many({})
    await db.navigation.delete_many({})
    await db.pages.delete_many({})
    await db.media.delete_many({})
    await db_manager._seed_defaults_if_needed()
    await db_manager.sync_category_counts()
