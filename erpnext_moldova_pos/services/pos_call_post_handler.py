import frappe
from pos_next.realtime_events import emit_shift_closed_event

def handle_pos_call_result(pos_call):
    """
    Entry point for domain-level POS Call result handling.
    Called after POS Call is completed (success or failure).
    """

    pos_call_doc = frappe.get_cached_doc("POS Call", pos_call)

    handlers = {
        "Open Shift": handle_open_shift_result,
        # later:
        # "Close Shift": handle_close_shift_result,
        # "Sale": handle_sale_result,
    }

    handler = handlers.get(pos_call_doc.command)
    if handler:
        handler(pos_call)


def handle_open_shift_result(pos_call):
    """
    Domain handler for Open Shift command.
    """
    
    pos_call_doc = frappe.get_cached_doc("POS Call", pos_call)

    # We only care about failures here
    if pos_call_doc.status != "Failed":
        return

    rollback_open_shift(pos_call_doc)


def rollback_open_shift(pos_call_doc):
    """
    Rollback ERPNext Open Shift if POS Station reports failure late.
    """
    
    try:
        if not pos_call_doc.opening_shift_reference_doctype:
            return

        doc = frappe.get_doc(
            pos_call_doc.opening_shift_reference_doctype,
            pos_call_doc.opening_shift_reference_name,
        )

        # Set ignore permissions to allow system user to cancel/delete
        doc.flags.ignore_permissions = True

        if doc.docstatus == 1:
            doc.cancel()
        elif doc.docstatus == 0:
            doc.delete()

        # Reset ignore permissions
        doc.flags.ignore_permissions = False

        # Emit shift closed event for frontend updates
        opening_shift = frappe.get_doc(pos_call_doc.opening_shift_reference_doctype, pos_call_doc.opening_shift_reference_name)
        emit_shift_closed_event(opening_shift.name, pos_profile=opening_shift.pos_profile, closed_by=frappe.session.user)

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Rollback Open Shift failed for POS Call: " + pos_call_doc.name,
        )


