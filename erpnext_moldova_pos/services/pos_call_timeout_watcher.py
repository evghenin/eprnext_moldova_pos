import frappe
from frappe.utils import now_datetime, add_to_date

from erpnext_moldova_pos.services.pos_call_service import mark_pos_call_sent, publish_pos_call

DEFAULT_MAX_EXECUTION_SECONDS = 300  # 5 minutes


def mark_timed_out_pos_calls():
    """
    Mark POS Calls as Timeout if execution SLA is exceeded.
    """

    deadline = add_to_date(
        now_datetime(),
        seconds=-DEFAULT_MAX_EXECUTION_SECONDS,
    )

    expired_calls = frappe.get_all(
        "POS Call",
        filters={
            "status": ["in", ["Pending", "Sent"]],
            "created_date": ["<=", deadline],
        },
        pluck="name",
    )

    for name in expired_calls:
        pos_call = frappe.get_doc("POS Call", name)

        # Idempotency guard
        if pos_call.completed_date:
            continue

        if pos_call.command == "sale":
            if pos_call.status != "Sent":
                continue
            pos_call.status = "Pending"
            pos_call.created_date = now_datetime()
            pos_call.save(ignore_permissions=True)
            # A new attempt: claim and publish again. Timeout itself is not delivered.
            if mark_pos_call_sent(pos_call.name):
                pos_call.status = "Sent"
                frappe.clear_document_cache("POS Call", pos_call.name)
                publish_pos_call(pos_call)
            continue

        pos_call.status = "Timeout"
        pos_call.save(ignore_permissions=True)
