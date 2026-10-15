import time
from erpnext_moldova_pos.moldova_pos.doctype.pos_call import pos_call
import frappe


def wait_for_pos_call_result_short(
    pos_call_name: str,
    timeout: int = 30,
    poll_interval: float = 0.5,
) -> str | None:
    """
    Short wait for POS Call result.
    Returns 'Completed', 'Failed' or None.
    """

    deadline = time.time() + timeout

    while time.time() < deadline:
        frappe.db.commit()  # Ensure we read the latest data
        status = frappe.db.get_value(
            "POS Call",
            pos_call_name,
            "status",
        )

        if status in ("Completed", "Failed"):
            return status

        time.sleep(poll_interval)

    return None
