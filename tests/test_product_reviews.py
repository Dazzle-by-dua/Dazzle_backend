import datetime
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.database import get_database, clean_doc
from app.security import create_access_token

from tests.conftest import (
    TEST_ADMIN_USERNAME,
    TEST_ADMIN_PASSWORD
)

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def app_lifespan():
    with client:
        yield

def get_admin_headers():
    client.cookies.clear()
    res = client.post("/api/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD})
    token = res.json()["token"]
    client.cookies.clear()  # Clear cookie so it does not leak into subsequent client calls
    return {"Authorization": f"Bearer {token}"}

def create_test_customer_token(customer_id="cust_test_101", email="testcustomer@example.com", name="Sameer Ahmed"):
    token = create_access_token({
        "sub": email,
        "email": email,
        "name": name,
        "role": "customer",
        "token_version": 1
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_review_flow_and_eligibility():
    db = get_database()
    admin_headers = get_admin_headers()
    
    # 1. Setup Customer and Seed Products if needed
    cust_email = "verified.buyer@example.com"
    cust_id = "cust_verified_99"
    cust_name = "Verified Buyer"
    cust_headers = create_test_customer_token(customer_id=cust_id, email=cust_email, name=cust_name)

    # Ensure customer exists in db.customers for token validation
    await db.customers.delete_many({"email": cust_email})
    await db.customers.insert_one({
        "id": cust_id,
        "name": cust_name,
        "email": cust_email,
        "token_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })

    # Clear previous orders & reviews for this test customer
    await db.orders.delete_many({"email": cust_email})
    await db.reviews.delete_many({"customer_email": cust_email})

    # 2. Check eligibility without login -> login_required
    res_elig_unauth = client.get("/api/reviews/eligibility?product_id=1")
    assert res_elig_unauth.status_code == 200
    data_unauth = res_elig_unauth.json()
    assert data_unauth["eligible"] is False
    assert data_unauth["reason"] == "login_required"

    # Attempt POST /api/reviews without login -> 401
    res_post_unauth = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 5,
        "text": "Unauthorized attempt"
    })
    assert res_post_unauth.status_code == 401

    # 3. Customer is logged in, but has NO orders -> not_purchased
    res_elig_no_order = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_no_order.status_code == 200
    assert res_elig_no_order.json()["eligible"] is False
    assert res_elig_no_order.json()["reason"] == "not_purchased"

    res_post_no_order = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 5,
        "text": "I never bought this"
    }, headers=cust_headers)
    assert res_post_no_order.status_code == 403

    # 4. Customer has a CANCELLED order for product 1 -> must NOT qualify
    await db.orders.insert_one({
        "id": "DBD-TEST-CANCELLED",
        "customer": cust_name,
        "email": cust_email,
        "status": "Cancelled",
        "paymentStatus": "Paid",
        "paymentMethod": "Razorpay Online",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    })

    res_elig_cancelled = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_cancelled.json()["eligible"] is False
    assert res_elig_cancelled.json()["reason"] == "not_purchased"

    # 5. Customer has an unpaid pending Razorpay order -> must NOT qualify
    await db.orders.insert_one({
        "id": "DBD-TEST-UNPAID",
        "customer": cust_name,
        "email": cust_email,
        "status": "Payment Pending",
        "paymentStatus": "Pending",
        "paymentMethod": "Razorpay Online",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    })

    res_elig_unpaid = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_unpaid.json()["eligible"] is False
    assert res_elig_unpaid.json()["reason"] == "not_purchased"

    # 6. Customer has an undelivered Cash on Delivery order -> must NOT qualify
    await db.orders.insert_one({
        "id": "DBD-TEST-COD-PROCESSING",
        "customer": cust_name,
        "email": cust_email,
        "status": "Processing",
        "paymentStatus": "Pending",
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    })

    res_elig_cod_proc = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_cod_proc.json()["eligible"] is False
    assert res_elig_cod_proc.json()["reason"] == "not_purchased"

    # 7. Customer now has a completed/delivered COD order for product 1 -> QUALIFIED!
    await db.orders.insert_one({
        "id": "DBD-TEST-COD-DELIVERED",
        "customer": cust_name,
        "email": cust_email,
        "status": "Delivered",
        "paymentStatus": "Pending",
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    })

    res_elig_qualified = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_qualified.status_code == 200
    data_qual = res_elig_qualified.json()
    assert data_qual["eligible"] is True
    assert data_qual["can_review"] is True
    assert data_qual["reason"] == "eligible"

    # 8. Submit review as qualified customer -> 201 Created
    res_submit = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 5,
        "text": "Absolutely breathtaking craftsmanship and sparkling finish!"
    }, headers=cust_headers)
    assert res_submit.status_code == 201
    rev_data = res_submit.json()
    rev_id = rev_data["id"]
    assert rev_data["verified"] is True
    assert rev_data["name"] == cust_name
    assert rev_data["customer_email"] == cust_email

    # 9. Verify duplicate review prevention -> already_reviewed
    res_elig_dup = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_dup.json()["eligible"] is False
    assert res_elig_dup.json()["reason"] == "already_reviewed"
    assert res_elig_dup.json().get("can_edit") is True
    assert res_elig_dup.json()["existing_review"]["id"] == rev_id

    res_submit_dup = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 4,
        "text": "Trying to post another review"
    }, headers=cust_headers)
    assert res_submit_dup.status_code == 400
    assert "already submitted" in res_submit_dup.json()["detail"].lower()

    # 9b. Customer edits their written review via PUT /api/reviews/{rev_id}
    res_cust_edit = client.put(f"/api/reviews/{rev_id}", json={
        "rating": 4,
        "text": "Updated review text: Absolutely breathtaking craftsmanship!"
    }, headers=cust_headers)
    assert res_cust_edit.status_code == 200
    assert res_cust_edit.json()["rating"] == 4
    assert res_cust_edit.json()["text"] == "Updated review text: Absolutely breathtaking craftsmanship!"

    # 9c. Unauthorized customer cannot edit someone else's review
    intruder_email = "intruder@example.com"
    await db.customers.insert_one({
        "id": "cust_intruder",
        "name": "Intruder",
        "email": intruder_email,
        "token_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })
    other_headers = create_test_customer_token(customer_id="cust_intruder", email=intruder_email, name="Intruder")
    res_unauth_edit = client.put(f"/api/reviews/{rev_id}", json={
        "rating": 1,
        "text": "Unauthorized attempt to edit"
    }, headers=other_headers)
    assert res_unauth_edit.status_code == 403
    await db.customers.delete_many({"email": intruder_email})

    # Cleanup
    await db.orders.delete_many({"email": cust_email})
    await db.reviews.delete_many({"customer_email": cust_email})
    await db.customers.delete_many({"email": cust_email})


@pytest.mark.anyio
async def test_cod_and_razorpay_review_eligibility_matrix():
    """
    Focused test matrix as required:
    - COD + Delivered + Pending payment = REVIEW ALLOWED.
    - COD + Processing = REVIEW DENIED.
    - COD + Shipped = REVIEW DENIED.
    - Razorpay + verified payment (Paid) + Delivered = REVIEW ALLOWED.
    - Razorpay + Delivered + Pending payment = REVIEW DENIED.
    - Product not purchased = REVIEW DENIED.
    - Duplicate review = REVIEW DENIED.
    """
    db = get_database()
    cust_email = "matrix.buyer@example.com"
    cust_id = "CUST-MATRIX-001"
    cust_name = "Matrix Buyer"
    cust_headers = create_test_customer_token(customer_id=cust_id, email=cust_email, name=cust_name)

    await db.customers.delete_many({"email": cust_email})
    await db.customers.insert_one({
        "id": cust_id,
        "name": cust_name,
        "email": cust_email,
        "token_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })
    await db.orders.delete_many({"customer_id": cust_id})
    await db.orders.delete_many({"email": cust_email})
    await db.reviews.delete_many({"customer_email": cust_email})

    # Case 1: Product not purchased -> REVIEW DENIED
    r_not_purchased = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert r_not_purchased.status_code == 200
    assert r_not_purchased.json()["eligible"] is False
    assert r_not_purchased.json()["reason"] == "not_purchased"

    # Case 2: COD + Processing -> REVIEW DENIED
    ord_cod_proc = {
        "id": "DBD-COD-PROC",
        "customer": cust_name,
        "email": cust_email,
        "customer_id": cust_id,
        "customer_email": cust_email,
        "status": "Processing",
        "paymentStatus": "Pending",
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    }
    await db.orders.insert_one(ord_cod_proc)
    r_cod_proc = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert r_cod_proc.json()["eligible"] is False
    assert r_cod_proc.json()["reason"] == "not_purchased"
    await db.orders.delete_many({"id": "DBD-COD-PROC"})

    # Case 3: COD + Shipped -> REVIEW DENIED
    ord_cod_ship = {
        "id": "DBD-COD-SHIP",
        "customer": cust_name,
        "email": cust_email,
        "customer_id": cust_id,
        "customer_email": cust_email,
        "status": "Shipped",
        "paymentStatus": "Pending",
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    }
    await db.orders.insert_one(ord_cod_ship)
    r_cod_ship = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert r_cod_ship.json()["eligible"] is False
    assert r_cod_ship.json()["reason"] == "not_purchased"
    await db.orders.delete_many({"id": "DBD-COD-SHIP"})

    # Case 4: COD + Delivered + Pending payment -> REVIEW ALLOWED
    ord_cod_deliv = {
        "id": "DBD-COD-DELIV",
        "customer": cust_name,
        "email": cust_email,
        "customer_id": cust_id,
        "customer_email": cust_email,
        "status": "Delivered",
        "paymentStatus": "Pending",
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4999}]
    }
    await db.orders.insert_one(ord_cod_deliv)
    r_cod_deliv = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert r_cod_deliv.status_code == 200
    assert r_cod_deliv.json()["eligible"] is True
    assert r_cod_deliv.json()["reason"] == "eligible"

    # Case 5: Razorpay + Delivered + Pending payment -> REVIEW DENIED
    ord_rzp_pending = {
        "id": "DBD-RZP-PENDING",
        "customer": cust_name,
        "email": cust_email,
        "customer_id": cust_id,
        "customer_email": cust_email,
        "status": "Delivered",
        "paymentStatus": "Pending",
        "paymentMethod": "Razorpay Online",
        "items": [{"id": 2, "name": "Diamond Ring", "price": 6999}]
    }
    await db.orders.insert_one(ord_rzp_pending)
    r_rzp_pending = client.get("/api/reviews/eligibility?product_id=2", headers=cust_headers)
    assert r_rzp_pending.json()["eligible"] is False
    assert r_rzp_pending.json()["reason"] == "not_purchased"
    await db.orders.delete_many({"id": "DBD-RZP-PENDING"})

    # Case 6: Razorpay + verified payment (Paid) + Delivered -> REVIEW ALLOWED
    ord_rzp_paid = {
        "id": "DBD-RZP-PAID",
        "customer": cust_name,
        "email": cust_email,
        "customer_id": cust_id,
        "customer_email": cust_email,
        "status": "Delivered",
        "paymentStatus": "Paid",
        "paymentMethod": "Razorpay Online",
        "items": [{"id": 2, "name": "Diamond Ring", "price": 6999}]
    }
    await db.orders.insert_one(ord_rzp_paid)
    r_rzp_paid = client.get("/api/reviews/eligibility?product_id=2", headers=cust_headers)
    assert r_rzp_paid.status_code == 200
    assert r_rzp_paid.json()["eligible"] is True
    assert r_rzp_paid.json()["reason"] == "eligible"

    # Case 7: Duplicate review -> REVIEW DENIED
    post_res = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 5,
        "text": "First review for product 1"
    }, headers=cust_headers)
    assert post_res.status_code == 201

    r_dup = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert r_dup.json()["eligible"] is False
    assert r_dup.json()["reason"] == "already_reviewed"

    r_post_dup = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 4,
        "text": "Second review should be denied"
    }, headers=cust_headers)
    assert r_post_dup.status_code == 400
    assert "already submitted" in r_post_dup.json()["detail"].lower()

    # Cleanup
    await db.orders.delete_many({"customer_id": cust_id})
    await db.orders.delete_many({"email": cust_email})
    await db.reviews.delete_many({"customer_email": cust_email})
    await db.customers.delete_many({"email": cust_email})

