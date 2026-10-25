import frappe
import json
from frappe import _
from erpnext_moldova_pos.services.pos_call_service import create_pos_call
from erpnext_moldova_pos.services.pos_command_payload import build_close_shift_data
from erpnext_moldova_pos.services.pos_call_failure import raise_for_pos_call
from erpnext_moldova_pos.services.pos_call_waiter import (
    wait_for_pos_call_result_short,
)
from pos_next.api.shifts import submit_closing_shift as original_method


CLOSE_WAIT_SECONDS = 90
REUSABLE_CLOSE_STATUSES = ("Pending", "Sent", "Completed")


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
        return _close_and_drop_unpaid_drafts(closing_shift, *args, **kwargs)

    profile = frappe.get_doc("POS Profile", pos_profile)

    from erpnext_moldova_pos.services.pos_service_receipt_service import (
        post_closing_cash_collection,
        require_cashbox_reset_accounts,
    )

    require_cashbox_reset_accounts(profile)

    # 2. Check if POS Station is configured
    if not profile.pos_station:
        # No POS integration — fallback to default behavior
        return _close_and_drop_unpaid_drafts(closing_shift, *args, **kwargs)

    from erpnext_moldova_pos.services.pos_service_receipt_service import assert_shift_can_close

    opening_name = closing_shift.get("pos_opening_shift")
    if opening_name:
        assert_shift_can_close(opening_name)
    
    # 3. Reuse an unlinked close from this opening shift. A new call would
    # print a second Z-report. A close from an earlier shift must not count:
    # the terminal still has this shift open.
    pos_call = _existing_close_call(profile.pos_station, opening_name)
    if not pos_call:
        pos_call = create_pos_call(
            command="close_shift",
            pos_station=profile.pos_station,
            data=build_close_shift_data(),
            closing_shift_reference_doctype="POS Closing Shift",
            closing_shift_reference_name=None,  # created later
        )

    # 4. Wait for POS Station response. A finished call is not waited on again.
    status = pos_call.status
    if status not in ("Completed", "Failed"):
        status = wait_for_pos_call_result_short(
            pos_call.name,
            timeout=CLOSE_WAIT_SECONDS,
        )

    # 5. Handle early failure
    if status != "Completed":
        raise_for_pos_call(pos_call.name, status, _("closing the shift"))

    # 6. Proceed with original ERPNext logic
    closing_data = _close_and_drop_unpaid_drafts(closing_shift, *args, **kwargs)
    closing_name = closing_data.get("name") if isinstance(closing_data, dict) else None

    # 7. Bind Closing Shift to POS Call
    if closing_name:
        frappe.db.set_value(
            "POS Call",
            pos_call.name,
            "closing_shift_reference_name",
            closing_name,
            update_modified=False,
        )
        post_closing_cash_collection(closing_name)

    return closing_data


def _existing_close_call(pos_station: str, opening_shift: str | None):
    """Latest close_shift of this opening shift that is not linked yet.

    Pending and Sent are still on the device. Completed means the Z-report
    already printed and only the ERPNext close is left. Failed is skipped so
    the cashier can send a new command. A call created before this opening
    shift belongs to an earlier fiscal shift and is ignored.
    """

    filters = [
        ["pos_station", "=", pos_station],
        ["command", "=", "close_shift"],
        ["status", "in", REUSABLE_CLOSE_STATUSES],
        ["closing_shift_reference_name", "is", "not set"],
    ]
    if opening_shift:
        opened_at = frappe.db.get_value("POS Opening Shift", opening_shift, "creation")
        if opened_at:
            filters.append(["creation", ">", opened_at])

    name = frappe.db.get_value(
        "POS Call",
        filters=filters,
        fieldname="name",
        order_by="creation desc",
    )
    if not name:
        return None
    return frappe.get_doc("POS Call", name)


def _close_and_drop_unpaid_drafts(parsed_closing_shift, *args, **kwargs):
    # The JSON string stays in kwargs for the original method. A parameter
    # named closing_shift would collide with that keyword.
    closing_data = original_method(*args, **kwargs)
    _delete_unpaid_drafts(parsed_closing_shift)
    return closing_data


def _delete_unpaid_drafts(closing_shift: dict) -> None:
    """Drop Sales Invoice drafts left by failed card payments on this shift.

    A failed fiscal sale is saved as a draft before the receipt is printed.
    The customer has left, so the draft must not survive the shift close.
    """

    opening_shift = closing_shift.get("pos_opening_shift")
    pos_profile = closing_shift.get("pos_profile")
    filters = {"docstatus": 0, "is_pos": 1}
    if opening_shift:
        filters["posa_pos_opening_shift"] = opening_shift
    elif pos_profile:
        filters["pos_profile"] = pos_profile
    else:
        return

    names = frappe.get_all("Sales Invoice", filters=filters, pluck="name")
    for name in names:
        try:
            frappe.delete_doc("Sales Invoice", name, force=True, ignore_permissions=True)
        except Exception:
            frappe.log_error(
                title="Unpaid POS draft cleanup",
                message=frappe.get_traceback(),
            )
