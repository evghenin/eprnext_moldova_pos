import json
import frappe
from erpnext_moldova_pos.services.pos_station_service import (
    get_pending_calls_for_station,
    receive_station_result,
)
from erpnext_moldova_pos.services.pos_station_auth import (
    verify_pos_station,
    verify_pos_call,
)


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
