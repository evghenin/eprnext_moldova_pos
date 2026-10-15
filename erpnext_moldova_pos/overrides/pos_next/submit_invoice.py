import frappe
import json
from frappe import _
from erpnext_moldova_pos.services.pos_call_service import create_pos_call
from erpnext_moldova_pos.services.pos_call_waiter import (
    wait_for_pos_call_result_short,
)
from pos_next.api.invoices import submit_invoice as original_method


SHORT_WAIT_SECONDS = 300


@frappe.whitelist()
def submit_invoice(*args, **kwargs):
    """
    Override for POSNext submit_invoice.
    """
    kwargs.pop("cmd", None)

    # 1. Determine POS Profile
    if kwargs.get("invoice"):
        invoice = json.loads(kwargs.get("invoice"))
    else:
        frappe.throw(_("Offline invoices are not acceptable for POS processing"))

    pos_profile = invoice.get("pos_profile")

    if not pos_profile:
        return original_method(*args, **kwargs)

    profile = frappe.get_doc("POS Profile", pos_profile)

    # 2. Check if POS Station is configured
    if not profile.pos_station:
        # No POS integration — fallback to default behavior
        return original_method(*args, **kwargs)

    items = []
    item_tax_templates = {}

    for item in invoice.get("items", []):
        item_tax_template_name = item.get("item_tax_template")
        tax_template = item_tax_templates.get(item_tax_template_name);
        if tax_template is None:
            tax_template = frappe.get_doc("Item Tax Template", item_tax_template_name)
            item_tax_templates[item_tax_template_name] = tax_template

        if tax_template is None:
            continue
        
        taxes = []

        for tax in tax_template.taxes:
            taxes.append(
                {
                    "taxCode": "A",
                    "taxName": tax_template.title,
                    "fullName": tax_template.title,
                    "taxPrc": tax.tax_rate * 100,
                    "calcType": 1, # Tax calculation type (required if not used taxCode), possible values: 1 – including, 2 - fixed (excise amount*number of goods), 3 - simplified (percentage of the sale amount), Default value - 1
                }
            )

        items.append({
            "itemName": item.get("item_name"),
            "itemCode": item.get("item_code"),
            "itemUnit": item.get("stock_uom"),
            "itemQty": item.get("stock_qty", 0) * 1000, # qty * 1000
            "itemAmount": item.get("base_amount", 0) * 100, # amount * 100
            "discount": item.get("discount_amount", 0) * item.get("qty", 0) * 100, # discount * 100
            "itemTaxes": taxes,
        })

    payments = {}

    for payment in invoice.get("payments", []):
        if payment.get("type") == "Cash":
            payments["cashAmount"] = payment.get("amount", 0) * 100

        if payment.get("type") == "Bank":
            payments["cashlessAmount"] = payment.get("amount", 0) * 100

        if payment.get("type") == "General":
            payments["invoiceAmount"] = payment.get("amount", 0) * 100

    invoice_data = {
        "docNumber": invoice.get("name"),
        "docTime": invoice.get("posting_date") + " " + invoice.get("posting_time"),
        "amount": invoice.get("base_total", 0) * 100,
        "currency": invoice.get("currency"),
        "items": items,
        "payments": payments,
    }
    
    # 3. Create POS Call
    pos_call = create_pos_call(
        command="sale",
        pos_station=profile.pos_station,
        data=invoice_data,
        invoice_reference_doctype="Sales Invoice",
        invoice_reference_name=None,  # created later
    )

    # 4. Short wait for POS Station response
    status = wait_for_pos_call_result_short(
        pos_call.name,
        timeout=SHORT_WAIT_SECONDS,
    )

    # 5. Handle early failure
    if status != "Completed":
        frappe.throw(_("Failed to submit sale on POS Station"))

    # 6. Proceed with original ERPNext logic
    submit_invoice_data = original_method(*args, **kwargs)

    return submit_invoice_data
