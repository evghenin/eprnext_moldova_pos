import frappe
from frappe.utils import now_datetime, get_fullname
from erpnext_moldova_pos.services.pos_station_device_selector import (
    select_station_device_for_command,
)


def create_pos_call(
    *,
    command: str,
    pos_station: str,
    data: dict,
    opening_shift_reference_doctype: str | None = None,
    opening_shift_reference_name: str | None = None,
    closing_shift_reference_doctype: str | None = None,
    closing_shift_reference_name: str | None = None,
    invoice_reference_doctype: str | None = None,
    invoice_reference_name: str | None = None,
):
    """
    Create a POS Call in Pending state.
    """

    device, app = select_station_device_for_command(
        pos_station=pos_station, 
        command=command
    )

    doc = frappe.get_doc(
        {
            "doctype": "POS Call",
            "command": command,
            "pos_station": pos_station,
            "status": "Pending",
            "payload": {
                "device": {
                    "serial_number": device.serial_number,
                    "device_type": device.device_type,
                    "device_app": app.app_name,
                },
                "user": get_fullname(frappe.session.user),
                "data": data,
            },
            "opening_shift_reference_doctype": opening_shift_reference_doctype,
            "opening_shift_reference_name": opening_shift_reference_name,
            "closing_shift_reference_doctype": closing_shift_reference_doctype,
            "closing_shift_reference_name": closing_shift_reference_name,
            "invoice_reference_doctype": invoice_reference_doctype,
            "invoice_reference_name": invoice_reference_name,
            "created_date": now_datetime(),
        }
    )
    doc.insert(ignore_permissions=True)
    
    return doc


def mark_pos_call_sent(pos_call):
    """
    Atomically mark POS Call as Sent to avoid race conditions.
    """

    frappe.db.sql(
        """
        UPDATE `tabPOS Call`
        SET status = 'Sent'
        WHERE name = %s AND status = 'Pending'
        """,
        (pos_call.name,),
    )


def complete_pos_call(
    *,
    pos_call,
    result: dict,
    success: bool,
):
    """
    Complete POS Call with success or failure.
    """
    
    pos_call_doc = frappe.get_cached_doc("POS Call", pos_call)

    pos_call_doc.result = result
    pos_call_doc.completed_date = now_datetime()
    pos_call_doc.status = "Completed" if success else "Failed"
    pos_call_doc.save(ignore_permissions=True)
