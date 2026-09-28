# Dazzle by Dua ? Production REST API Backend

A clean, modular, production-ready REST API backend engineered specifically for the **Dazzle by Dua** fine jewellery e-commerce platform.

- **Backend Directory**: `C:\Users\abuba\Documents\dazzle_bend`
- **Frontend Directory**: `C:\Users\abuba\Documents\dazzle_fend`
- **Interactive OpenAPI/Swagger Documentation**: `http://127.0.0.1:8000/docs`
- **Alternative ReDoc**: `http://127.0.0.1:8000/redoc`

---

## ?? Key Capabilities & Features

1. **100% Data Compatibility with Frontend**:
   Matches all frontend keys and data structures: `products`, `categories`, `orders`, `reviews`, `offers`, `homepage`, `settings`, and `navigation`.
2. **Real Persistence with SQLite**:
   Full ACID transactions, WAL mode for high concurrency, auto-seeding with exact default jewellery catalog on initialization.
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

## ?? Quick Start Guide

### 1. Requirements
- Python 3.10+ (tested and verified on Python 3.13)
- Dependencies installed via `pip install -r requirements.txt`:
  - `fastapi`, `uvicorn`, `pydantic`, `python-dotenv`, `python-jose`, `bcrypt`, `python-multipart`, `aiofiles`, `pytest`, `requests`, `httpx`

### 2. Run the Backend Server
From the backend directory:
```bash
python run.py
```
Or directly using Uvicorn:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The API will be available at:
- Base API: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/api/health`

---

## ?? Default Admin Credentials

| Username | Email | Password | Role |
| :--- | :--- | :--- | :--- |
| `admin` | `admin@dazzlebydua.com` | `admin123` | Master Administrator |
| `dua` | `dua@dazzlebydua.com` | `dazzleadmin` | Store Owner |

---

## ?? API Endpoint Reference

### 1. Authentication (`/api/auth`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/login` | Authenticate admin, returns JWT token & user profile | No |
| `GET` | `/api/auth/me` | Get currently authenticated admin details | **Yes** |
| `POST` | `/api/auth/logout` | Clear session and cookies | No |

### 2. Products (`/api/products`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/products` | List all products (supports `?category=`, `?inStock=`, `?search=`, `?sort=`) | No |
| `GET` | `/api/products/{id}` | Get product by ID | No |
| `GET` | `/api/products/details/map` | Get product details map | No |
| `POST` | `/api/products` | Create new product | **Yes** |
| `PUT` | `/api/products/{id}` | Update product fields | **Yes** |
| `PATCH`| `/api/products/{id}/stock` | Toggle in-stock status | **Yes** |
| `DELETE`| `/api/products/{id}` | Delete product | **Yes** |

### 3. Categories (`/api/categories`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/categories` | List all categories with live product count | No |
| `GET` | `/api/categories/{id}` | Get category by ID | No |
| `POST` | `/api/categories` | Add new category | **Yes** |
| `PUT` | `/api/categories/{id}` | Update category | **Yes** |
| `DELETE`| `/api/categories/{id}` | Delete category | **Yes** |

### 4. Orders (`/api/orders`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/orders` | List orders (supports `?status=`, `?search=`) | No / Storefront |
| `GET` | `/api/orders/{id}` | Get order details & tracking info | No / Storefront |
| `POST` | `/api/orders` | Place new order (checkout) | No / Storefront |
| `PATCH`| `/api/orders/{id}/status` | Update fulfillment status (`Processing`, `Shipped`, etc.) | **Yes** |
| `DELETE`| `/api/orders/{id}` | Remove order | **Yes** |

### 5. Customers (`/api/customers`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/customers` | Get customer analytics (order counts, lifetime spend) | **Yes** |
| `GET` | `/api/customers/{email}` | Get customer profile and order history | **Yes** |

### 6. Reviews (`/api/reviews`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/reviews` | List reviews (supports `?approved_only=true`, `?product=`) | No |
| `POST` | `/api/reviews` | Submit new review | No / Storefront |
| `PUT` | `/api/reviews/{id}` | Edit review text/rating | **Yes** |
| `PATCH`| `/api/reviews/{id}/status` | Approve or hide review | **Yes** |
| `DELETE`| `/api/reviews/{id}` | Delete review | **Yes** |

### 7. Offers, Coupons & Combos (`/api/offers`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/offers` | Get all coupons and bundle combos | No |
| `GET` | `/api/offers/coupons` | List coupons | No |
| `POST` | `/api/offers/coupons` | Add new coupon | **Yes** |
| `PUT` | `/api/offers/coupons/{id}` | Update coupon | **Yes** |
| `DELETE`| `/api/offers/coupons/{id}` | Delete coupon | **Yes** |
| `POST` | `/api/offers/coupons/validate` | Validate coupon code against cart total | No / Storefront |
| `GET` | `/api/offers/combos` | List combos | No |
| `POST` | `/api/offers/combos` | Add new combo | **Yes** |
| `PUT` | `/api/offers/combos/{id}` | Update combo | **Yes** |
| `DELETE`| `/api/offers/combos/{id}` | Delete combo | **Yes** |

### 8. Homepage CMS (`/api/homepage`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/homepage` | Get configuration for all 9 homepage sections | No |
| `PUT` | `/api/homepage` | Save complete homepage configuration | **Yes** |
| `PATCH`| `/api/homepage/{section}` | Update specific section (`hero`, `announcement`, etc.) | **Yes** |

### 9. Store Settings (`/api/settings`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/settings` | Get store settings, currency, contacts, social | No |
| `PUT` | `/api/settings` | Save store settings | **Yes** |

### 10. Navigation Menus (`/api/navigation`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/navigation` | Get header, footerQuick, footerCare links | No |
| `PUT` | `/api/navigation` | Save entire navigation structure | **Yes** |
| `POST` | `/api/navigation/{section}` | Add navigation link to section | **Yes** |
| `DELETE`| `/api/navigation/{section}/{idx}`| Remove navigation link by index | **Yes** |

### 11. Static Pages & Policies (`/api/pages`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/pages` | Get jewellery care guide, shipping terms, FAQs | No |
| `PUT` | `/api/pages` | Update static pages content | **Yes** |

### 12. Media Assets (`/api/media`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/media` | List media files with thumbnails, sizes and URLs | No |
| `POST` | `/api/media/upload` | Upload image file (multipart/form-data) | **Yes** |
| `DELETE`| `/api/media/{filename}` | Delete image file from server | **Yes** |

### 13. Dashboard Analytics (`/api/dashboard`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/dashboard/stats` | Live revenue, order count breakdown, low stock | **Yes** |

### 14. Database Backup & Restore (`/api/backup`)
| Method | Endpoint | Description | Protected |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/backup/export` | Export complete database in DazzleStore JSON format | **Yes** |
| `POST` | `/api/backup/import` | Restore complete database from backup JSON | **Yes** |
| `POST` | `/api/backup/reset` | Factory reset database to initial default demo data | **Yes** |

---

## ?? Connecting Frontend to API

When you are ready to switch the frontend from localStorage to the backend:

1. Add `<script src="dazzle_api_client.js"></script>` to your HTML files.
2. The provided `client_adapter/dazzle_api_client.js` exposes `window.DazzleApi` with full Promise-based methods and `syncFromBackend()` method to instantly synchronize all local collections.
3. Every CRUD action performed in the Admin Panel automatically updates the database and reflects in the customer storefront.

---

## ?? Testing

Run the full automated test suite anytime:
```bash
pytest tests/test_api.py -v
```
All 10 test suites test end-to-end integration and verify zero regressions.
