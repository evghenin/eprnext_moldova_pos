import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if frappe.db.has_column("POS Call", "fiscal_receipt") and not frappe.db.has_column(
		"POS Call", "pos_fiscal_receipt"
	):
		rename_field("POS Call", "fiscal_receipt", "pos_fiscal_receipt")
