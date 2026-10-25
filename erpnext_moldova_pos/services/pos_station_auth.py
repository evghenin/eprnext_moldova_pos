import hmac
import hashlib
import time
import frappe
import base64


MAX_DRIFT_SECONDS = 60


def verify_pos_station(
    *,
    pos_station: str,
    nonce: str,
    timestamp: int,
    signature: str,
) -> None:
    """Verify POS Station request using HMAC."""

    station = frappe.get_doc("POS Station", pos_station)

    if station.disabled:
        frappe.throw("POS Station is disabled", frappe.PermissionError)

    if not station.shared_secret:
        frappe.throw("POS Station Shared Secret (shared_secret) is not configured", frappe.PermissionError)

    now = int(time.time())
    if abs(now - int(timestamp)) > MAX_DRIFT_SECONDS:
        frappe.throw("Request timestamp is out of allowed range", frappe.PermissionError)

    expected_signature = base64.b64encode(
        hmac.new(
            station.shared_secret.encode(),
            f"{pos_station}:{timestamp}:{nonce}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()

    if not hmac.compare_digest(expected_signature, signature):
        frappe.throw("Invalid POS Station signature", frappe.PermissionError)

    frappe.set_user(station.service_user or "Guest")


def verify_pos_call(
    *,
    pos_call: str,
    pos_station: str,
) -> None:
    """Verify POS Call exists and belongs to POS Station."""

    owner = frappe.db.get_value("POS Call", pos_call, "pos_station")

    if not owner:
        frappe.throw("POS Call not found", frappe.DoesNotExistError)

    if owner != pos_station:
        frappe.throw("POS Call does not belong to POS Station", frappe.PermissionError)