import frappe

from erpnext_moldova_pos.services.pos_fiscal_receipt_service import (
	cancel_receipt,
	enqueue_one,
	mark_printed,
)


@frappe.whitelist()
def cancel_fiscal_receipt(fiscal_receipt: str):
	"""Cashier confirmed the terminal did not print this receipt."""

	cancel_receipt(fiscal_receipt)
	return {"fiscal_receipt": fiscal_receipt, "status": "Rejected"}


@frappe.whitelist()
def confirm_fiscal_receipt_printed(fiscal_receipt: str, invoice=None, data=None):
	"""Cashier confirmed the receipt printed. Submit the invoice without a new fiscal sale."""

	mark_printed(fiscal_receipt)
	if invoice is None:
		frappe.throw("Invoice is required to close the sale")
	from erpnext_moldova_pos.overrides.pos_next.submit_invoice import submit_invoice

	return submit_invoice(invoice=invoice, data=data)


@frappe.whitelist()
def request_reconcile(fiscal_receipt: str, receipt_number: str | None = None, mev_id: str | None = None, shift_id: str | None = None):
	"""Ask the station for the shift receipt list and match this document again."""

	return enqueue_one(
		fiscal_receipt,
		receipt_number=receipt_number,
		mev_id=mev_id,
		shift_id=shift_id,
	)
