import frappe

from erpnext_moldova_pos.services.pos_service_receipt_service import (
	load_printed,
	mark_not_printed,
	movement_state,
	submit_movement,
)


@frappe.whitelist()
def get_cash_movement_state(pos_profile: str, opening_shift: str):
	return movement_state(pos_profile, opening_shift)


@frappe.whitelist()
def submit_cash_movement(pos_profile: str, opening_shift: str, movement_type: str, amount):
	return submit_movement(pos_profile, opening_shift, movement_type, amount)


@frappe.whitelist()
def mark_cash_movement_not_printed(receipt: str):
	return mark_not_printed(receipt)


@frappe.whitelist()
def load_printed_cash_movement(receipt: str, receipt_id: str | None = None):
	return load_printed(receipt, receipt_id or None)
