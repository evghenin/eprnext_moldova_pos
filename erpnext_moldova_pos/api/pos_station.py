import json
from datetime import datetime, timedelta, timezone

import frappe
from frappe.sessions import clear_sessions

from erpnext_moldova_pos.services.pos_station_service import (
    get_pending_calls_for_station,
    receive_station_result,
)
from erpnext_moldova_pos.services.pos_station_auth import (
    verify_pos_station,
    verify_pos_call,
)

# Short enough that a dropped agent does not keep a desk session open.
SOCKET_SESSION_SECONDS = 600


@frappe.whitelist(allow_guest=True)
def socket_login(pos_station: str):
    """Trade the station HMAC for a short sid. The socket joins that user's room."""

    headers = frappe.request.headers
    verify_pos_station(
        pos_station=pos_station,
        nonce=headers.get("X-POS-Nonce"),
        timestamp=headers.get("X-POS-Timestamp"),
        signature=headers.get("X-POS-Signature"),
    )

    service_user = frappe.db.get_value("POS Station", pos_station, "service_user")
    if not service_user:
        frappe.throw("POS Station service user is not configured", frappe.PermissionError)

    session_end = (datetime.now(timezone.utc) + timedelta(seconds=SOCKET_SESSION_SECONDS)).isoformat()
    clear_sessions(service_user, force=True)
    frappe.local.login_manager.login_as(service_user, session_end=session_end)
    return {"sid": frappe.session.sid, "user": service_user}


@frappe.whitelist(allow_guest=True)
def pull_calls(pos_station: str):
    """POS Station pulls pending POS Calls."""

    headers = frappe.request.headers
    request_headers = "\n".join([f"{k}: {v}" for k, v in headers.items()])
    request_data = json.loads(frappe.request.get_data().decode("utf-8"))

    verify_pos_station(
        pos_station=pos_station,
        nonce=headers.get("X-POS-Nonce"),
        timestamp=headers.get("X-POS-Timestamp"),
        signature=headers.get("X-POS-Signature"),
    )

    return get_pending_calls_for_station(pos_station, request_headers, request_data)


@frappe.whitelist(allow_guest=True)
def push_result(
    pos_call: str,
    success: int,
    payload: dict | str | None = None,
):
    """POS Station pushes POS Call execution result."""

    headers = frappe.request.headers
    request_headers = "\n".join([f"{k}: {v}" for k, v in headers.items()])
    pos_station = headers.get("X-POS-Station")

    verify_pos_station(
        pos_station=pos_station,
        nonce=headers.get("X-POS-Nonce"),
        timestamp=headers.get("X-POS-Timestamp"),
        signature=headers.get("X-POS-Signature"),
    )

    verify_pos_call(
        pos_call=pos_call,
        pos_station=pos_station,
    )

    if isinstance(payload, str):
        payload = json.loads(payload) if payload else {}

    return receive_station_result(
        pos_station=pos_station,
        pos_call=pos_call,
        success=_as_bool(success),
        request_data=payload or {},
        request_headers=request_headers,
    )


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)
