import frappe

def handle_pos_call_result(pos_call):
    """
    Entry point for domain-level POS Call result handling.
    Called after POS Call is completed (success or failure).
    """

    pos_call_doc = frappe.get_doc("POS Call", pos_call)

    handlers = {
        "open_shift": handle_open_shift_result,
        "sale": handle_sale_result,
        "list_shifts": handle_list_shifts_result,
        "list_shift_receipts": handle_list_shift_receipts_result,
        "get_receipt": handle_get_receipt_result,
    }

    handler = handlers.get(pos_call_doc.command)
    if handler:
        handler(pos_call)


def handle_sale_result(pos_call):
    pos_call_doc = frappe.get_doc("POS Call", pos_call)
    if not pos_call_doc.pos_fiscal_receipt:
        return
    from erpnext_moldova_pos.services.pos_fiscal_receipt_service import mark_registered, mark_rejected
    from erpnext_moldova_pos.services.pos_call_service import as_dict

    if pos_call_doc.status == "Completed":
        mark_registered(pos_call_doc.pos_fiscal_receipt, as_dict(pos_call_doc.result))
    elif pos_call_doc.status == "Failed":
        mark_rejected(pos_call_doc.pos_fiscal_receipt)


def handle_list_shifts_result(pos_call):
    from erpnext_moldova_pos.services.pos_fiscal_receipt_service import apply_shift_list

    pos_call_doc = frappe.get_doc("POS Call", pos_call)
    apply_shift_list(pos_call_doc.name, pos_call_doc.status == "Completed")


def handle_list_shift_receipts_result(pos_call):
    from erpnext_moldova_pos.services.pos_fiscal_receipt_service import apply_shift_receipts

    pos_call_doc = frappe.get_doc("POS Call", pos_call)
    apply_shift_receipts(pos_call_doc.name, pos_call_doc.status == "Completed")


def handle_get_receipt_result(pos_call):
    from erpnext_moldova_pos.services.pos_fiscal_receipt_service import apply_receipt_detail
    from erpnext_moldova_pos.services.pos_service_receipt_service import apply_terminal_refresh

    pos_call_doc = frappe.get_doc("POS Call", pos_call)
    completed = pos_call_doc.status == "Completed"
    apply_receipt_detail(pos_call_doc.name, completed)
    apply_terminal_refresh(pos_call_doc.name, completed)


def handle_open_shift_result(pos_call):
    """
    Domain handler for Open Shift command.
    """
    
    pos_call_doc = frappe.get_doc("POS Call", pos_call)

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

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Rollback Open Shift failed for POS Call: " + pos_call_doc.name,
        )


