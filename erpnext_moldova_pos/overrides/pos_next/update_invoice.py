import frappe
from pos_next.api.invoices import update_invoice as original_method

from erpnext_moldova_pos.services.order_payments import payments_from_update, remember


@frappe.whitelist()
def update_invoice(data):
	"""Keep Sales Order tender. The draft itself cannot store payment rows."""

	doctype, existing_name, payments = payments_from_update(data)
	result = original_method(data)
	if doctype == "Sales Order" and isinstance(result, dict):
		remember(result.get("name") or existing_name, payments)
	return result
