import json
import frappe
from erpnext_moldova_pos.services.pos_call_service import (
    mark_pos_call_sent,
    complete_pos_call,
)
from erpnext_moldova_pos.services.pos_call_log_service import (
    log_outbound_request,
    log_inbound_response,
)
from erpnext_moldova_pos.services.pos_call_post_handler import (
    handle_pos_call_result,
)


def get_pending_calls_for_station(pos_station: str, request_headers: str, request_data: dict, limit: int = 10) -> list[dict]:
    """Return pending POS Calls for POS Station."""

    calls = frappe.get_all(
        "POS Call",
        filters={
            "pos_station": pos_station,
            "status": "Pending",
        },
        order_by="created_date asc",
        limit=limit,
    )

    result = []

    for row in calls:
        doc = frappe.get_doc("POS Call", row.name)
        mark_pos_call_sent(doc)

        result.append(
            {
                "pos_call": doc.name,
                "command": doc.command,
                "payload": json.loads(doc.payload),
            }
        )

    # Log outbound request only if there are calls
    if calls:        
        log_outbound_request(
            pos_station=pos_station,
            pos_calls=[c.get("name") for c in calls or []],
            request_headers=request_headers,
            request_data=request_data,
            response_data={"message": result},
        )

    return result


def receive_station_result(
    *,
    pos_station: str,
    pos_call: str,
    request_headers: str,
    request_data: dict,
    success: bool,
) -> None:
    """
    Receive POS Call execution result from POS Station.
    """

    # 1. Log inbound response
    log_inbound_response(
        pos_station=pos_station,
        pos_call=pos_call,
        success=success,
        request_headers=request_headers,
        request_data=request_data,
    )

    # 2. Update POS Call status/result
    complete_pos_call(
        pos_call=pos_call,
        result=request_data,
        success=success,
    )

    # 3. Domain-level reaction (rollback, compensation, etc.)
    handle_pos_call_result(pos_call)
