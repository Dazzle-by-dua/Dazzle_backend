"""
Dazzle by Dua - Resend Email Notification Service
Handles automated, reliable administrative notifications for new customer orders.
Includes full customer checkout details, trusted backend pricing, and clickable product links.
"""

import html
import logging
import asyncio
import datetime
from typing import Dict, Any, Optional

import resend
from app.config import (
    RESEND_API_KEY,
    ADMIN_EMAIL,
    RESEND_FROM_EMAIL,
    FRONTEND_BASE_URL,
    IS_PRODUCTION
)

logger = logging.getLogger("dazzle.resend")

ADMIN_ORDERS_URL = f"{FRONTEND_BASE_URL}/admin/index.html#orders"
IST_TIMEZONE = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def is_resend_configured() -> bool:
    """Check whether Resend API key and destination admin email are configured."""
    return bool(RESEND_API_KEY and ADMIN_EMAIL)


def get_resend_status() -> Dict[str, Any]:
    """Safe diagnostic status without exposing secret API key."""
    masked_admin = None
    if ADMIN_EMAIL:
        parts = ADMIN_EMAIL.split("@")
        if len(parts) == 2:
            name, domain = parts
            masked_name = name[0] + "***" if len(name) > 1 else name
            masked_admin = f"{masked_name}@{domain}"
        else:
            masked_admin = "***"

    return {
        "configured": is_resend_configured(),
        "from_email": RESEND_FROM_EMAIL,
        "admin_email": masked_admin
    }


def get_product_url(product_id: Any) -> str:
    """Generate live product detail page link matching Dazzle by Dua frontend routing."""
    if product_id is None or str(product_id).strip() == "":
        return f"{FRONTEND_BASE_URL}/shop.html"
    import urllib.parse
    clean_id = urllib.parse.quote(str(product_id).strip(), safe="")
    return f"{FRONTEND_BASE_URL}/product-details.html?id={clean_id}"


def get_product_image_url(img: Optional[str]) -> str:
    """Resolve full image URL for email rendering."""
    if not img or not str(img).strip():
        return f"{FRONTEND_BASE_URL}/logo.png"
    img_clean = str(img).strip()
    if img_clean.startswith("http://") or img_clean.startswith("https://"):
        return img_clean
    return f"{FRONTEND_BASE_URL}/{img_clean}"


def format_order_datetime(iso_str: Optional[str]) -> str:
    """Format order timestamp in Indian Standard Time (IST)."""
    if iso_str:
        try:
            dt = datetime.datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            ist_dt = dt.astimezone(IST_TIMEZONE)
            return ist_dt.strftime("%d %b %Y, %I:%M %p IST")
        except Exception:
            pass

    now_ist = datetime.datetime.now(IST_TIMEZONE)
    return now_ist.strftime("%d %b %Y, %I:%M %p IST")


def generate_order_email_content(order: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate professional, responsive HTML and plain-text email templates.
    Customer input is rigorously escaped to prevent HTML injection.
    """
    order_id = str(order.get("id") or "UNKNOWN")
    safe_order_id = html.escape(order_id)
    safe_customer = html.escape(str(order.get("customer") or "Valued Customer"))
    safe_email = html.escape(str(order.get("email") or "Not provided"))
    safe_phone = html.escape(str(order.get("phone") or "Not provided"))
    safe_address = html.escape(str(order.get("address") or "Not provided"))
    safe_landmark = html.escape(str(order.get("landmark") or "").strip())
    safe_notes = html.escape(str(order.get("notes") or "").strip())
    safe_payment_method = html.escape(str(order.get("paymentMethod") or "Cash on Delivery"))
    safe_payment_status = html.escape(str(order.get("paymentStatus") or "Pending"))
    safe_order_status = html.escape(str(order.get("status") or "Processing"))
    safe_currency = html.escape(str(order.get("currency") or "INR"))

    formatted_time = format_order_datetime(order.get("created_at") or order.get("date"))

    # Trusted financial totals
    total = float(order.get("total", 0.0))
    subtotal = float(order.get("subtotal", total))
    discount = float(order.get("discount", 0.0))
    shipping = max(0.0, round(total - (subtotal - discount), 2)) if subtotal > 0 else 0.0

    # Payment badge color
    is_paid = safe_payment_status.lower() == "paid"
    badge_bg = "#2E7D32" if is_paid else "#E65100"
    badge_text = "PAID & VERIFIED" if is_paid else "PAYMENT PENDING"

    # Build products HTML & Text
    items = order.get("items") or []
    items_html_rows = []
    items_text_rows = []

    for idx, item in enumerate(items, 1):
        item_id = item.get("id")
        item_name = str(item.get("name") or f"Item #{idx}")
        safe_item_name = html.escape(item_name)
        qty = int(item.get("qty", 1))
        price = float(item.get("price", 0.0))
        line_total = price * qty
        variant = str(item.get("variant") or "").strip()
        safe_variant = html.escape(variant)
        img_url = html.escape(get_product_image_url(item.get("img")), quote=True)
        product_url = get_product_url(item_id)
        safe_product_url = html.escape(product_url, quote=True)

        variant_html = f"<div style='font-size:12px;color:#888;'>Variant: {safe_variant}</div>" if variant else ""

        items_html_rows.append(f"""
        <tr style="border-bottom: 1px solid #ECECEC;">
          <td style="padding: 12px 8px; vertical-align: middle; width: 64px;">
            <img src="{img_url}" alt="{safe_item_name}" style="width: 56px; height: 56px; object-fit: cover; border-radius: 6px; border: 1px solid #E0E0E0;" />
          </td>
          <td style="padding: 12px 8px; vertical-align: middle;">
            <div style="font-weight: 600; font-size: 14px; color: #1A1A1A;">{safe_item_name}</div>
            <div style="font-size: 11px; color: #777;">ID: {html.escape(str(item_id))}</div>
            {variant_html}
            <div style="margin-top: 4px;">
              <a href="{safe_product_url}" style="font-size: 12px; color: #C5A880; font-weight: 600; text-decoration: none;">View Product &rarr;</a>
            </div>
          </td>
          <td style="padding: 12px 8px; vertical-align: middle; text-align: center; font-size: 13px; color: #333;">
            {qty}
          </td>
          <td style="padding: 12px 8px; vertical-align: middle; text-align: right; font-size: 13px; color: #333;">
            &#8377;{price:,.2f}
          </td>
          <td style="padding: 12px 8px; vertical-align: middle; text-align: right; font-size: 13px; font-weight: 600; color: #1A1A1A;">
            &#8377;{line_total:,.2f}
          </td>
        </tr>
        """)

        variant_text = f" ({variant})" if variant else ""
        items_text_rows.append(
            f"  * {item_name}{variant_text} [Qty: {qty}] @ Rs. {price:,.2f} = Rs. {line_total:,.2f}\n"
            f"    Link: {product_url}"
        )

    items_html_tbody = "".join(items_html_rows) if items_html_rows else "<tr><td colspan='5' style='padding:16px;text-align:center;color:#888;'>No items listed.</td></tr>"
    items_text_body = "\n".join(items_text_rows) if items_text_rows else "  (No items listed)"

    notes_section_html = ""
    notes_section_text = ""
    if safe_notes:
        notes_section_html = f"""
        <div style="background: #FFF8E7; border-left: 4px solid #C5A880; padding: 12px 16px; margin: 20px 0; border-radius: 4px;">
          <strong style="color: #6D4C41; font-size: 13px;">Customer Order Notes / Special Instructions:</strong>
          <div style="color: #3E2723; font-size: 13px; margin-top: 4px; font-style: italic;">&ldquo;{safe_notes}&rdquo;</div>
        </div>
        """
        notes_section_text = f"\nCustomer Notes:\n\"{order.get('notes', '').strip()}\"\n"

    # HTML Body
    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>New Order #{safe_order_id} Received</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F5F5F3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #222222;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #F5F5F3; padding: 30px 15px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" width="100%" style="max-width: 650px; background-color: #FFFFFF; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #E5E5E0;" cellspacing="0" cellpadding="0">
          
          <!-- Header Banner -->
          <tr>
            <td style="background-color: #1A1A1A; padding: 28px 30px; text-align: center; border-bottom: 3px solid #C5A880;">
              <h1 style="margin: 0; color: #FFFFFF; font-size: 24px; letter-spacing: 1.5px; font-weight: 600; text-transform: uppercase;">
                Dazzle by Dua
              </h1>
              <div style="color: #C5A880; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; margin-top: 4px;">
                Fine Jewellery &bull; New Order Notification
              </div>
            </td>
          </tr>

          <!-- Order Status Bar -->
          <tr>
            <td style="background-color: #FAFAF8; padding: 16px 30px; border-bottom: 1px solid #EFEFEA;">
              <table width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="vertical-align: middle;">
                    <span style="font-size: 18px; font-weight: 700; color: #1A1A1A;">Order #{safe_order_id}</span>
                    <div style="font-size: 12px; color: #666; margin-top: 2px;">{formatted_time}</div>
                  </td>
                  <td style="text-align: right; vertical-align: middle;">
                    <span style="display: inline-block; background-color: {badge_bg}; color: #FFFFFF; font-size: 11px; font-weight: 700; padding: 5px 12px; border-radius: 20px; letter-spacing: 0.5px;">
                      {badge_text}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 28px 30px;">
              
              <!-- Greeting / Summary Callout -->
              <div style="font-size: 15px; line-height: 1.5; color: #333; margin-bottom: 24px;">
                A new order has been placed on the store. Below are the customer checkout details, purchased items, and delivery information.
              </div>

              <!-- Customer Details Card -->
              <table width="100%" cellspacing="0" cellpadding="0" style="background-color: #FBFBFA; border: 1px solid #EBEBE6; border-radius: 6px; margin-bottom: 24px;">
                <tr>
                  <td style="padding: 18px 20px;">
                    <div style="font-size: 13px; font-weight: 700; color: #C5A880; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">
                      1. Customer &amp; Shipping Details
                    </div>
                    <table width="100%" cellspacing="0" cellpadding="4" style="font-size: 13px;">
                      <tr>
                        <td style="width: 130px; color: #777; vertical-align: top;">Customer Name:</td>
                        <td style="color: #1A1A1A; font-weight: 600;">{safe_customer}</td>
                      </tr>
                      <tr>
                        <td style="color: #777; vertical-align: top;">Email Address:</td>
                        <td style="color: #1A1A1A;"><a href="mailto:{safe_email}" style="color: #1A1A1A; text-decoration: underline;">{safe_email}</a></td>
                      </tr>
                      <tr>
                        <td style="color: #777; vertical-align: top;">Phone / Mobile:</td>
                        <td style="color: #1A1A1A; font-weight: 600;"><a href="tel:{safe_phone}" style="color: #1A1A1A; text-decoration: none;">{safe_phone}</a></td>
                      </tr>
                      <tr>
                        <td style="color: #777; vertical-align: top;">Delivery Address:</td>
                        <td style="color: #1A1A1A; line-height: 1.4;">{safe_address}</td>
                      </tr>
                      <tr>
                        <td style="color: #777; vertical-align: top;">Landmark:</td>
                        <td style="color: #1A1A1A; font-weight: 600;">{safe_landmark if safe_landmark else 'Not provided'}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Payment & Order Lifecycle Card -->
              <table width="100%" cellspacing="0" cellpadding="0" style="background-color: #FBFBFA; border: 1px solid #EBEBE6; border-radius: 6px; margin-bottom: 24px;">
                <tr>
                  <td style="padding: 18px 20px;">
                    <div style="font-size: 13px; font-weight: 700; color: #C5A880; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">
                      2. Payment &amp; Fulfillment
                    </div>
                    <table width="100%" cellspacing="0" cellpadding="4" style="font-size: 13px;">
                      <tr>
                        <td style="width: 130px; color: #777;">Payment Method:</td>
                        <td style="color: #1A1A1A; font-weight: 600;">{safe_payment_method}</td>
                      </tr>
                      <tr>
                        <td style="color: #777;">Payment Status:</td>
                        <td style="color: #1A1A1A; font-weight: 600;">{safe_payment_status}</td>
                      </tr>
                      <tr>
                        <td style="color: #777;">Order Status:</td>
                        <td style="color: #1A1A1A;">{safe_order_status}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              {notes_section_html}

              <!-- Items Table -->
              <div style="font-size: 13px; font-weight: 700; color: #C5A880; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px;">
                3. Ordered Items ({len(items)})
              </div>
              <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse: collapse; margin-bottom: 20px; font-size: 13px;">
                <thead>
                  <tr style="background-color: #F2F2EE; border-bottom: 2px solid #E0E0D8; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; color: #555;">
                    <th style="padding: 10px 8px; text-align: left;" colspan="2">Product</th>
                    <th style="padding: 10px 8px; text-align: center; width: 50px;">Qty</th>
                    <th style="padding: 10px 8px; text-align: right; width: 85px;">Price</th>
                    <th style="padding: 10px 8px; text-align: right; width: 95px;">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {items_html_tbody}
                </tbody>
              </table>

              <!-- Totals Breakdown -->
              <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom: 28px;">
                <tr>
                  <td style="width: 55%;"></td>
                  <td style="width: 45%;">
                    <table width="100%" cellspacing="0" cellpadding="6" style="font-size: 13px; color: #444;">
                      <tr>
                        <td style="color: #666;">Subtotal:</td>
                        <td style="text-align: right; font-weight: 500;">&#8377;{subtotal:,.2f}</td>
                      </tr>
                      {"<tr><td style='color: #2E7D32;'>Discount:</td><td style='text-align: right; color: #2E7D32; font-weight: 600;'>-&#8377;" + f"{discount:,.2f}</td></tr>" if discount > 0 else ""}
                      <tr>
                        <td style="color: #666;">Delivery Fee:</td>
                        <td style="text-align: right; font-weight: 500;">{"FREE" if shipping == 0 else f"&#8377;{shipping:,.2f}"}</td>
                      </tr>
                      <tr style="border-top: 2px solid #1A1A1A;">
                        <td style="font-size: 16px; font-weight: 700; color: #1A1A1A; padding-top: 10px;">Total:</td>
                        <td style="font-size: 18px; font-weight: 700; color: #C5A880; text-align: right; padding-top: 10px;">
                          &#8377;{total:,.2f} <span style="font-size: 11px; color: #888;">{safe_currency}</span>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Call to Action: Admin Dashboard -->
              <div style="text-align: center; padding: 20px 0 10px 0; border-top: 1px solid #EBEBE6;">
                <a href="{ADMIN_ORDERS_URL}" style="display: inline-block; background-color: #1A1A1A; color: #D4AF7C; border: 1px solid #D4AF7C; font-weight: 600; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 4px; letter-spacing: 0.5px;">
                  Open Admin Orders Dashboard &rarr;
                </a>
                <div style="font-size: 11px; color: #888; margin-top: 8px;">
                  Direct link: {ADMIN_ORDERS_URL}
                </div>
              </div>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #F5F5F3; padding: 20px 30px; text-align: center; font-size: 12px; color: #888; border-top: 1px solid #E5E5E0;">
              <div>This is an automated administrative notification from Dazzle by Dua.</div>
              <div style="margin-top: 4px;">&copy; {datetime.datetime.now().year} Dazzle by Dua. All rights reserved.</div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    # Plain text fallback
    plain_text = f"""===================================================================
DAZZLE BY DUA - NEW ORDER NOTIFICATION
Order #{order_id} | {badge_text}
===================================================================

Order Date: {formatted_time}
Order Status: {safe_order_status}
Payment Method: {safe_payment_method}
Payment Status: {safe_payment_status}

1. CUSTOMER & SHIPPING DETAILS
-------------------------------------------------------------------
Name:    {order.get('customer', 'Valued Customer')}
Email:   {order.get('email', 'Not provided')}
Phone:   {order.get('phone', 'Not provided')}
Address:  {order.get('address', 'Not provided')}
Landmark: {order.get('landmark', 'Not provided')}
{notes_section_text}
2. ORDERED PRODUCTS ({len(items)})
-------------------------------------------------------------------
{items_text_body}

3. FINANCIAL SUMMARY
-------------------------------------------------------------------
Subtotal:     Rs. {subtotal:,.2f}
Discount:     -Rs. {discount:,.2f}
Delivery Fee: {'FREE' if shipping == 0 else f'Rs. {shipping:,.2f}'}
-------------------------------------------------------------------
TOTAL:        Rs. {total:,.2f} {safe_currency}

ADMIN DASHBOARD ORDERS LINK:
{ADMIN_ORDERS_URL}

===================================================================
Dazzle by Dua Fine Jewellery - Automated Notification
"""

    subject = f"New Order Received – Dazzle by Dua | Order #{order_id}"
    return {
        "subject": subject,
        "html": html_body,
        "text": plain_text
    }


async def send_new_order_admin_notification(order: Dict[str, Any], db=None) -> Dict[str, Any]:
    """
    Send admin email notification for a verified order via Resend.
    - Idempotent: checks and claims the notification in MongoDB to prevent duplicate emails.
    - Non-blocking and resilient: failure does not invalidate or abort the saved order.
    - Never exposes Resend API keys or secrets.
    """
    if not is_resend_configured():
        logger.info("Resend is not configured (RESEND_API_KEY or ADMIN_EMAIL missing). Skipping email notification.")
        return {"status": "skipped", "reason": "not_configured"}

    order_id = str(order.get("id") or "")
    if not order_id:
        logger.warning("Attempted to send order notification for order without an ID.")
        return {"status": "error", "reason": "missing_order_id"}

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Database-backed idempotency check
    if db is not None:
        try:
            # Atomic claim:
            # 1. Must not have already been successfully sent (admin_new_order_sent != True)
            # 2. Must not be currently in-flight by a concurrent worker (admin_new_order_pending != True),
            #    UNLESS the existing in-flight lock is stale (>120s old, e.g. process crashed mid-send).
            stale_cutoff = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=120)
            ).isoformat()

            claim_result = await db.orders.update_one(
                {
                    "id": order_id,
                    "notifications.admin_new_order_sent": {"$ne": True},
                    "$or": [
                        {"notifications.admin_new_order_pending": {"$ne": True}},
                        {"notifications.admin_new_order_claimed_at": {"$lt": stale_cutoff}}
                    ]
                },
                {
                    "$set": {
                        "notifications.admin_new_order_pending": True,
                        "notifications.admin_new_order_claimed_at": now_iso
                    },
                    "$inc": {
                        "notifications.admin_new_order_attempts": 1
                    }
                }
            )
            if claim_result.modified_count == 0:
                existing = await db.orders.find_one({"id": order_id}, {"notifications": 1})
                if existing and existing.get("notifications", {}).get("admin_new_order_sent"):
                    logger.info(f"Order #{order_id} admin notification already sent. Skipping duplicate.")
                    return {"status": "skipped", "reason": "already_sent"}
                logger.info(f"Order #{order_id} admin notification currently in-flight. Skipping duplicate.")
                return {"status": "skipped", "reason": "already_sent_or_in_flight"}
        except Exception as e:
            logger.warning(f"Could not check/claim notification lock for order #{order_id}: {e}")

    content = generate_order_email_content(order)

    # Initialize Resend client
    resend.api_key = RESEND_API_KEY

    params = {
        "from": RESEND_FROM_EMAIL,
        "to": [ADMIN_EMAIL],
        "subject": content["subject"],
        "html": content["html"],
        "text": content["text"]
    }

    try:
        # Run synchronous Resend SDK call in a separate thread to avoid blocking FastAPI
        response = await asyncio.to_thread(resend.Emails.send, params)
        resend_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        if not resend_id:
            raise RuntimeError(f"Resend API did not return a valid message id: {response}")

        logger.info(f"Successfully sent admin order notification for Order #{order_id} via Resend (ID: {resend_id})")

        if db is not None:
            try:
                await db.orders.update_one(
                    {"id": order_id},
                    {
                        "$set": {
                            "notifications.admin_new_order_sent": True,
                            "notifications.admin_new_order_sent_at": now_iso,
                            "notifications.admin_new_order_id": resend_id,
                            "notifications.admin_new_order_pending": False
                        }
                    }
                )
            except Exception as db_err:
                logger.warning(f"Failed to record Resend notification success in MongoDB for order #{order_id}: {db_err}")

        return {
            "status": "sent",
            "order_id": order_id,
            "resend_id": resend_id
        }

    except Exception as err:
        logger.error(f"Failed to send Resend admin order notification for Order #{order_id}: {err}")

        if db is not None:
            try:
                await db.orders.update_one(
                    {"id": order_id},
                    {
                        "$set": {
                            "notifications.admin_new_order_error": str(err),
                            "notifications.admin_new_order_pending": False
                        }
                    }
                )
            except Exception as db_err:
                logger.warning(f"Failed to record Resend notification error in MongoDB for order #{order_id}: {db_err}")

        return {
            "status": "error",
            "order_id": order_id,
            "error": str(err)
        }


# =========================================================================
# Customer Authentication Email Templates & Dispatchers
# =========================================================================

async def send_customer_otp_email(email: str, name: str, otp: str) -> Dict[str, Any]:
    """
    Send cryptographically generated 6-digit OTP to customer for email verification.
    """
    if not RESEND_API_KEY:
        if not IS_PRODUCTION:
            logger.info(f"[DEV/TEST] Resend API key not set. Simulated OTP email sent to {email}.")
            return {"success": True, "status": "simulated"}
        logger.error("Resend API key missing in production. Cannot deliver OTP email.")
        return {"success": False, "error": "Email service not configured"}

    safe_name = html.escape(name or "Valued Customer")
    safe_otp = html.escape(str(otp).strip())

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Your Verification Code - Dazzle by Dua</title>
</head>
<body style="margin:0;padding:0;background-color:#F5F5F3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#222;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:40px 15px;background-color:#F5F5F3;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:540px;background:#FFF;border-radius:8px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);border:1px solid #E5E5E0;" cellspacing="0" cellpadding="0">
          <tr>
            <td style="background-color:#1A1A1A;padding:26px 30px;text-align:center;border-bottom:3px solid #C5A880;">
              <h1 style="margin:0;color:#FFF;font-size:22px;letter-spacing:1.5px;font-weight:600;text-transform:uppercase;">Dazzle by Dua</h1>
              <div style="color:#C5A880;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:4px;">Fine Jewellery</div>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 30px;">
              <div style="font-size:16px;font-weight:600;color:#1A1A1A;margin-bottom:12px;">Dear {safe_name},</div>
              <p style="font-size:14px;line-height:1.6;color:#555;margin:0 0 20px;">
                Thank you for choosing Dazzle by Dua. To complete your account registration, please enter the six-digit verification code below:
              </p>
              
              <div style="background:#FAF8F5;border:1px solid #E2D1B8;border-radius:8px;padding:22px;text-align:center;margin:24px 0;">
                <div style="font-size:32px;font-weight:700;letter-spacing:8px;color:#1A1A1A;font-family:monospace;">
                  {safe_otp}
                </div>
                <div style="font-size:12px;color:#888;margin-top:8px;">
                  This code expires in <strong>5 minutes</strong>.
                </div>
              </div>

              <p style="font-size:13px;line-height:1.6;color:#777;margin:0 0 16px;">
                For your security, never share this code with anyone. Dazzle by Dua representatives will never ask for your verification code.
              </p>
              <p style="font-size:12px;color:#999;margin:0;">
                If you did not request this verification code, you can safely disregard this email.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#F5F5F3;padding:18px 30px;text-align:center;font-size:11px;color:#888;border-top:1px solid #E5E5E0;">
              &copy; {datetime.datetime.now().year} Dazzle by Dua. All rights reserved.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    plain_text = f"""DAZZLE BY DUA - FINE JEWELLERY
Email Verification Code

Dear {name or 'Valued Customer'},

Your six-digit verification code is: {otp}

This code expires in 5 minutes.
Never share this code with anyone.

If you did not request this code, you can safely ignore this email.

(c) {datetime.datetime.now().year} Dazzle by Dua.
"""

    resend.api_key = RESEND_API_KEY
    params = {
        "from": RESEND_FROM_EMAIL,
        "to": [email],
        "subject": "Your Verification Code – Dazzle by Dua",
        "html": html_content,
        "text": plain_text
    }

    try:
        response = await asyncio.to_thread(resend.Emails.send, params)
        res_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        logger.info(f"OTP verification email sent to {email} (ID: {res_id})")
        return {"success": True, "id": res_id}
    except Exception as e:
        logger.error(f"Failed to send customer OTP email to {email}: {e}")
        return {"success": False, "error": str(e)}


async def send_customer_password_reset_email(email: str, name: str, reset_link: str) -> Dict[str, Any]:
    """
    Send branded password reset link to customer via Resend.
    """
    if not RESEND_API_KEY:
        if not IS_PRODUCTION:
            logger.info(f"[DEV/TEST] Resend API key not set. Simulated Password Reset link for {email}: {reset_link}")
            return {"success": True, "status": "simulated"}
        logger.error("Resend API key missing in production. Cannot deliver password reset email.")
        return {"success": False, "error": "Email service not configured"}

    safe_name = html.escape(name or "Valued Customer")
    safe_link = html.escape(reset_link, quote=True)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Reset Your Password - Dazzle by Dua</title>
</head>
<body style="margin:0;padding:0;background-color:#F5F5F3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#222;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:40px 15px;background-color:#F5F5F3;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:540px;background:#FFF;border-radius:8px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);border:1px solid #E5E5E0;" cellspacing="0" cellpadding="0">
          <tr>
            <td style="background-color:#1A1A1A;padding:26px 30px;text-align:center;border-bottom:3px solid #C5A880;">
              <h1 style="margin:0;color:#FFF;font-size:22px;letter-spacing:1.5px;font-weight:600;text-transform:uppercase;">Dazzle by Dua</h1>
              <div style="color:#C5A880;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:4px;">Fine Jewellery</div>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 30px;">
              <div style="font-size:16px;font-weight:600;color:#1A1A1A;margin-bottom:12px;">Dear {safe_name},</div>
              <p style="font-size:14px;line-height:1.6;color:#555;margin:0 0 20px;">
                We received a request to reset the password for your Dazzle by Dua customer account. Click the button below to choose a new password:
              </p>
              
              <div style="text-align:center;margin:28px 0;">
                <a href="{safe_link}" style="display:inline-block;background-color:#1A1A1A;color:#D4AF7C;border:1px solid #D4AF7C;font-weight:600;font-size:14px;text-decoration:none;padding:14px 32px;border-radius:4px;letter-spacing:1px;text-transform:uppercase;">
                  Reset Password &rarr;
                </a>
              </div>

              <div style="background:#FAF8F5;border-left:3px solid #C5A880;padding:12px 16px;margin:20px 0;font-size:12px;color:#666;">
                This link is valid for <strong>20 minutes</strong> and can only be used once.
              </div>

              <p style="font-size:12px;line-height:1.5;color:#888;margin:20px 0 8px;">
                If the button above does not work, copy and paste this link into your browser:
              </p>
              <div style="font-size:11px;color:#999;word-break:break-all;background:#F9F9F9;padding:8px 10px;border-radius:4px;">
                {safe_link}
              </div>

              <p style="font-size:12px;color:#999;margin-top:20px;">
                If you did not request a password reset, please disregard this email. Your password will remain unchanged.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#F5F5F3;padding:18px 30px;text-align:center;font-size:11px;color:#888;border-top:1px solid #E5E5E0;">
              &copy; {datetime.datetime.now().year} Dazzle by Dua. All rights reserved.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    plain_text = f"""DAZZLE BY DUA - FINE JEWELLERY
Password Reset Request

Dear {name or 'Valued Customer'},

We received a request to reset your password. Click or copy the following link to choose a new password:
{reset_link}

This link is valid for 20 minutes and is single-use only.

If you did not request a password reset, you can safely ignore this email.

(c) {datetime.datetime.now().year} Dazzle by Dua.
"""

    resend.api_key = RESEND_API_KEY
    params = {
        "from": RESEND_FROM_EMAIL,
        "to": [email],
        "subject": "Reset Your Password – Dazzle by Dua",
        "html": html_content,
        "text": plain_text
    }

    try:
        response = await asyncio.to_thread(resend.Emails.send, params)
        res_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        logger.info(f"Password reset email sent to {email} (ID: {res_id})")
        return {"success": True, "id": res_id}
    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {e}")
        return {"success": False, "error": str(e)}


async def send_customer_password_changed_notification(email: str, name: str) -> Dict[str, Any]:
    """
    Send notification to customer confirming that their password was successfully changed.
    """
    if not RESEND_API_KEY:
        if not IS_PRODUCTION:
            logger.info(f"[DEV/TEST] Resend API key not set. Simulated Password Changed confirmation for {email}.")
            return {"success": True, "status": "simulated"}
        return {"success": False, "error": "Email service not configured"}

    safe_name = html.escape(name or "Valued Customer")

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Password Changed - Dazzle by Dua</title>
</head>
<body style="margin:0;padding:0;background-color:#F5F5F3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#222;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:40px 15px;background-color:#F5F5F3;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:540px;background:#FFF;border-radius:8px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);border:1px solid #E5E5E0;" cellspacing="0" cellpadding="0">
          <tr>
            <td style="background-color:#1A1A1A;padding:26px 30px;text-align:center;border-bottom:3px solid #C5A880;">
              <h1 style="margin:0;color:#FFF;font-size:22px;letter-spacing:1.5px;font-weight:600;text-transform:uppercase;">Dazzle by Dua</h1>
              <div style="color:#C5A880;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:4px;">Fine Jewellery</div>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 30px;">
              <div style="font-size:16px;font-weight:600;color:#1A1A1A;margin-bottom:12px;">Dear {safe_name},</div>
              <p style="font-size:14px;line-height:1.6;color:#555;margin:0 0 20px;">
                Your password for Dazzle by Dua was successfully changed. All existing sessions have been signed out for your security.
              </p>
              <div style="background:#E8F5E9;border-left:4px solid #2E7D32;padding:12px 16px;margin:20px 0;font-size:13px;color:#1B5E20;">
                &#10003; Password successfully updated.
              </div>
              <p style="font-size:13px;line-height:1.6;color:#777;margin:0;">
                If you did not perform this change, please contact our support team immediately.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#F5F5F3;padding:18px 30px;text-align:center;font-size:11px;color:#888;border-top:1px solid #E5E5E0;">
              &copy; {datetime.datetime.now().year} Dazzle by Dua. All rights reserved.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    plain_text = f"""DAZZLE BY DUA - FINE JEWELLERY
Password Changed Successfully

Dear {name or 'Valued Customer'},

Your password for Dazzle by Dua has been changed successfully. All previous sessions have been signed out.

If you did not perform this change, please contact us immediately.

(c) {datetime.datetime.now().year} Dazzle by Dua.
"""

    resend.api_key = RESEND_API_KEY
    params = {
        "from": RESEND_FROM_EMAIL,
        "to": [email],
        "subject": "Your Password Has Been Changed – Dazzle by Dua",
        "html": html_content,
        "text": plain_text
    }

    try:
        response = await asyncio.to_thread(resend.Emails.send, params)
        res_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        return {"success": True, "id": res_id}
    except Exception as e:
        logger.error(f"Failed to send password changed notification to {email}: {e}")
        return {"success": False, "error": str(e)}
