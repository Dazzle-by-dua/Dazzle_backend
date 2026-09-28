# Dazzle by Dua ? Production REST API Backend

A clean, modular, production-ready REST API backend engineered specifically for the **Dazzle by Dua** fine jewellery e-commerce platform.

- **Backend Directory**: `C:\Users\abuba\Documents\dazzle_bend`
- **Frontend Directory**: `C:\Users\abuba\Documents\dazzle_fend`
- **Interactive OpenAPI/Swagger Documentation**: `http://127.0.0.1:8000/docs`
- **Alternative ReDoc**: `http://127.0.0.1:8000/redoc`

---

## ?? Key Capabilities & Features

1. **MongoDB Integration (Motor / PyMongo)**:
   - Primary database using asynchronous `motor` driver.
   - Centralized database connection pooling and graceful error handling.
   - Built-in automatic seeding from `DEFAULT_*` jewellery catalogs on initial launch.
   - Resilient fallback for local testing.
2. **100% Data Compatibility with Frontend**:
   Matches all frontend keys and data structures: `products`, `categories`, `orders`, `reviews`, `offers`, `homepage`, `settings`, and `navigation`.
3. **Products & Inventory Engine**:
   Full CRUD, stock toggles, pricing, discounts, finish variants, image galleries, and auto-calculating category counters.
4. **Order Management & Fulfillment Tracking**:
   Storefront checkout order placement, order status updates (`Processing`, `Shipped`, `Delivered`, `Cancelled`), and customer tracking synchronization.
5. **Customer Intelligence & CRM**:
   Unique customer profiles automatically aggregated from order history with lifetime spend and order count.
6. **Customer Reviews Moderation**:
   5-star rating submission from storefront, approval/hide moderation by admin, and instant storefront display.
7. **Offers, Coupons & Combo Deals**:
   Real-time coupon validation engine (minimum order check, percentage/fixed/free shipping calculation), bundle combos CRUD.
8. **Homepage CMS (9 Configurable Sections)**:
   Full control over `announcement`, `hero`, `categories`, `newArrivals`, `featured`, `whyChooseUs`, `reviewsSection`, `instagram`, and `footer`.
9. **Store Settings & Navigation**:
   Store contact info, currency symbol, free shipping threshold, header & footer navigation menu builder.
10. **Media & Asset Library**:
    Upload image files directly to the server, automatic file serving via `/uploads/{filename}`, copyable asset names.
11. **Secure Admin Authentication**:
    Bcrypt password hashing, JWT bearer tokens, cookie support, and protected administrative routes.
12. **Live Dashboard Analytics**:
    Revenue calculation, order count breakdown, low stock / out of stock alerts, and customer activity.
13. **Full Store Backup & Restore**:
    Export entire store database to JSON identical to `DazzleStore.exportAll()`, import/restore from JSON, and factory reset.
14. **Drop-in Client Adapter**:
    `client_adapter/dazzle_api_client.js` is provided as an instant bridge to switch the frontend from `localStorage` to the live backend API whenever ready.

---

## ?? Environment Variables

Configure these in your environment or on Render (**Environment** tab):

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `MONGODB_URI` | MongoDB connection string (e.g. MongoDB Atlas) | `mongodb+srv://USERNAME:PASSWORD@cluster.mongodb.net/` |
| `MONGODB_DB` | MongoDB database name | `dazzle_by_dua` |
| `HOST` | Host IP binding (use `0.0.0.0` for cloud deployment) | `0.0.0.0` |
| `PORT` | Web server listening port (Render sets `$PORT`) | `8000` |
| `SECRET_KEY` | JWT signing secret key | `your_secure_jwt_secret_key_here` |
| `ALGORITHM` | JWT signing algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token validity duration | `1440` (24 hours) |
| `CORS_ORIGINS` | Comma-separated list of allowed origins | `*` |

---

## ?? Render Deployment Guide

### Render Web Service Settings:
- **Environment**: `Python`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/api/health`

---

## ?? Default Admin Credentials

| Username | Email | Password | Role |
| :--- | :--- | :--- | :--- |
| `admin` | `admin@dazzlebydua.com` | `admin123` | Master Administrator |
| `dua` | `dua@dazzlebydua.com` | `dazzleadmin` | Store Owner |

---

## ?? Testing

Run the full automated test suite anytime:
```bash
pytest tests/test_api.py -v
```
*(All 10 integration test suites verify full database CRUD and synchronization).*
