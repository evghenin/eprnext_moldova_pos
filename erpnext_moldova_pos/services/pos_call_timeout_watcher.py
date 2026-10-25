import frappe
from frappe.utils import now_datetime, add_to_date

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
            pos_call.status = "Pending"
            pos_call.save(ignore_permissions=True)
            continue

        pos_call.status = "Timeout"
        pos_call.save(ignore_permissions=True)
