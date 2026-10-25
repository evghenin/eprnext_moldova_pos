# Copyright (c) 2026, Evgheni Nemerenco and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class POSCall(Document):
	@frappe.whitelist()
	def mark_failed(self):
		"""Close a call the station took and never answered. The station log keeps the link."""

		if self.status not in ("Pending", "Sent"):
			frappe.throw(_("POS Call {0} is already {1}.").format(self.name, self.status))
		self.db_set(
			{"status": "Failed", "completed_date": now_datetime()},
			update_modified=True,
		)
		return {"name": self.name, "status": "Failed"}
