import frappe
from frappe.model.rename_doc import rename_doc


_RENAMES = (
	("Fiscal Receipt Item", "POS Fiscal Receipt Item"),
	("Fiscal Receipt Payment", "POS Fiscal Receipt Payment"),
	("Fiscal Receipt Tax", "POS Fiscal Receipt Tax"),
	("Fiscal Receipt", "POS Fiscal Receipt"),
)


def execute():
	for old, new in _RENAMES:
		if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
			rename_doc("DocType", old, new, force=True, ignore_permissions=True)
