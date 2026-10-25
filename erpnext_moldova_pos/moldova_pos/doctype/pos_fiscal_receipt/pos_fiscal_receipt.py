import frappe
from frappe.model.document import Document

from erpnext_moldova_pos.services.pos_fiscal_receipt import regenerate_fiscal_receipt_pdf
from erpnext_moldova_pos.services.pos_fiscal_receipt_service import enqueue_terminal_receipt


class POSFiscalReceipt(Document):
	@frappe.whitelist()
	def regenerate_pdf(self):
		if self.receipt_state != "Confirmed":
			frappe.throw("The receipt PDF is available only after the terminal confirms the receipt.")
		return regenerate_fiscal_receipt_pdf(self.name)

	@frappe.whitelist()
	def refresh_from_terminal(self):
		"""Queue get_receipt for this document. The station answers in the background."""

		pos_call = enqueue_terminal_receipt(self.name, force=True)
		return {"fiscal_receipt": self.name, "pos_call": pos_call.name}
