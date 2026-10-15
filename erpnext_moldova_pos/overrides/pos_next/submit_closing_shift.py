import frappe
import json
from frappe import _
from erpnext_moldova_pos.services.pos_call_service import create_pos_call
from erpnext_moldova_pos.services.pos_call_waiter import (
    wait_for_pos_call_result_short,
)
from pos_next.api.shifts import submit_closing_shift as original_method


SHORT_WAIT_SECONDS = 30


@frappe.whitelist()
def submit_closing_shift(*args, **kwargs):
    """
    Override for POSNext submit_closing_shift.
    """
    kwargs.pop("cmd", None)

    # 1. Determine POS Profile
    closing_shift = json.loads(kwargs.get("closing_shift"))
    pos_profile = closing_shift.get("pos_profile")

    if not pos_profile:
        return original_method(*args, **kwargs)

    profile = frappe.get_doc("POS Profile", pos_profile)

    # 2. Check if POS Station is configured
    if not profile.pos_station:
        # No POS integration — fallback to default behavior
        return original_method(*args, **kwargs)
    
    # 3. Create POS Call
    pos_call = create_pos_call(
        command="close_shift",
        pos_station=profile.pos_station,
        data=None,
        closing_shift_reference_doctype="POS Closing Shift",
        closing_shift_reference_name=None,  # created later
    )

    # 4. Short wait for POS Station response
    status = wait_for_pos_call_result_short(
        pos_call.name,
        timeout=SHORT_WAIT_SECONDS,
    )

    # 5. Handle early failure
    if status != "Completed":
        frappe.throw(_("Failed to close shift on POS Station"))

    # 6. Proceed with original ERPNext logic
    closing_data = original_method(*args, **kwargs)
    closing_shift = closing_data.get("pos_closing_shift")

    # 7. Bind Closing Shift to POS Call (important)
    if isinstance(closing_shift, dict) and closing_shift.get("name"):
        frappe.db.set_value(
            "POS Call",
            pos_call.name,
            "closing_shift_reference_name",
            closing_shift.get("name"),
            update_modified=False,
        )

    return closing_data
