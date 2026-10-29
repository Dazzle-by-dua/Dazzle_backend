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

    # 8. Submit review as qualified customer -> 201 Created, approved=False
    res_submit = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 5,
        "text": "Absolutely breathtaking craftsmanship and sparkling finish!"
    }, headers=cust_headers)
    assert res_submit.status_code == 201
    rev_data = res_submit.json()
    rev_id = rev_data["id"]
    assert rev_data["approved"] is False  # Pending admin approval!
    assert rev_data["verified"] is True
    assert rev_data["name"] == cust_name
    assert rev_data["customer_email"] == cust_email

    # 9. Verify duplicate review prevention -> already_reviewed
    res_elig_dup = client.get("/api/reviews/eligibility?product_id=1", headers=cust_headers)
    assert res_elig_dup.json()["eligible"] is False
    assert res_elig_dup.json()["reason"] == "already_reviewed"

    res_submit_dup = client.post("/api/reviews", json={
        "product_id": 1,
        "rating": 4,
        "text": "Trying to post another review"
    }, headers=cust_headers)
    assert res_submit_dup.status_code == 400
    assert "already submitted" in res_submit_dup.json()["detail"].lower()

    # 10. Storefront GET /api/reviews -> should NOT display pending review to public
    res_pub_reviews = client.get("/api/reviews?product_id=1")
    assert res_pub_reviews.status_code == 200
    pub_ids = [r["id"] for r in res_pub_reviews.json()]
    assert rev_id not in pub_ids

    # 11. Admin view -> sees pending review
    res_admin_reviews = client.get("/api/reviews?approved_only=false", headers=admin_headers)
    assert res_admin_reviews.status_code == 200
    admin_ids = [r["id"] for r in res_admin_reviews.json()]
    assert rev_id in admin_ids

    # 12. Admin approves review
    res_approve = client.patch(f"/api/reviews/{rev_id}/status", json={"approved": True}, headers=admin_headers)
    assert res_approve.status_code == 200
    assert res_approve.json()["approved"] is True

    # 13. Storefront GET /api/reviews -> NOW displays the approved review!
    res_pub_after = client.get("/api/reviews?product_id=1")
    assert res_pub_after.status_code == 200
    pub_ids_after = [r["id"] for r in res_pub_after.json()]
    assert rev_id in pub_ids_after

    # Cleanup
    await db.orders.delete_many({"email": cust_email})
    await db.reviews.delete_many({"customer_email": cust_email})
    await db.customers.delete_many({"email": cust_email})
