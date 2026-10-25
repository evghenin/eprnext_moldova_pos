import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	# Runs before the DocType rename, so unmigrated sites still use the old table.
	for doctype in ("Fiscal Receipt", "POS Fiscal Receipt"):
		if frappe.db.has_column(doctype, "device_receipt_id") and not frappe.db.has_column(doctype, "receipt_id"):
			rename_field(doctype, "device_receipt_id", "receipt_id")
			return
