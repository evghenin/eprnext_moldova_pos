import frappe
from frappe import _
from erpnext_moldova_pos.services.pos_call_service import create_pos_call
from erpnext_moldova_pos.services.pos_command_payload import build_open_shift_data
from erpnext_moldova_pos.services.pos_call_failure import raise_for_pos_call
from erpnext_moldova_pos.services.pos_call_waiter import (
    wait_for_pos_call_result_short,
)
from pos_next.api.shifts import create_opening_shift as original_method


SHORT_WAIT_SECONDS = 30


@frappe.whitelist()
def create_opening_shift(*args, **kwargs):
    """
    Override for POSNext create_opening_shift.
    """
    kwargs.pop("cmd", None)

    # 1. Determine POS Profile
    pos_profile = kwargs.get("pos_profile")
    if not pos_profile:
        return original_method(*args, **kwargs)

    profile = frappe.get_doc("POS Profile", pos_profile)

    from erpnext_moldova_pos.services.pos_service_receipt_service import (
        post_opening_cash_deposit,
        require_cashbox_reset_accounts,
    )

    require_cashbox_reset_accounts(profile)

    # 2. Check if POS Station is configured
    if not profile.pos_station:
        # No POS integration — fallback to default behavior
        return original_method(*args, **kwargs)

    from erpnext_moldova_pos.services.pos_service_receipt_service import require_cash_accounts

    require_cash_accounts(profile)

    # 3. Create POS Call. The station reports device state; it is not told which device API to call.
    pos_call = create_pos_call(
        command="open_shift",
        pos_station=profile.pos_station,
        data=build_open_shift_data(kwargs.get("balance_details")),
        opening_shift_reference_doctype="POS Opening Shift",
        opening_shift_reference_name=None,  # created later
    )

    # 4. Short wait for POS Station response
    status = wait_for_pos_call_result_short(
        pos_call.name,
        timeout=SHORT_WAIT_SECONDS,
    )

    # 5. Handle early failure
    if status != "Completed":
        raise_for_pos_call(pos_call.name, status, _("opening the shift"))

    # 6. Proceed with original ERPNext logic
    opening_data = original_method(*args, **kwargs)
    opening_shift = opening_data.get("pos_opening_shift")

    # 7. Bind Opening Shift to POS Call (important)
    if isinstance(opening_shift, dict) and opening_shift.get("name"):
        frappe.db.set_value(
            "POS Call",
            pos_call.name,
            "opening_shift_reference_name",
            opening_shift.get("name"),
            update_modified=False,
        )
        post_opening_cash_deposit(opening_shift.get("name"), kwargs.get("balance_details"))

    return opening_data
