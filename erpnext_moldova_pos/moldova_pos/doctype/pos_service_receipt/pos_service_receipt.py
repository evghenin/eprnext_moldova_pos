import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_moldova_pos.services.pos_fiscal_receipt import regenerate_service_receipt_pdf
from erpnext_moldova_pos.services.pos_service_receipt_service import enqueue_terminal_refresh


class POSServiceReceipt(Document):
	@frappe.whitelist()
	def regenerate_pdf(self):
		if self.status != "Registered":
			frappe.throw(_("The receipt PDF is available only after the terminal confirms the receipt."))
		return regenerate_service_receipt_pdf(self.name)

	@frappe.whitelist()
	def refresh_from_terminal(self):
		"""Queue get_receipt for this document. The station answers in the background."""

		pos_call = enqueue_terminal_refresh(self.name)
		return {"service_receipt": self.name, "pos_call": pos_call.name if pos_call else None}
