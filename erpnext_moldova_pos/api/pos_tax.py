import frappe
from frappe.utils import flt

from erpnext_moldova_pos.overrides.pos_next.submit_invoice import _item_tax_template_name


@frappe.whitelist()
def get_item_tax_rate(pos_profile, item_code, posting_date=None, base_net_rate=None):
	"""Percent for the POS cart. Uses the POS Profile tax category, then its sales template."""

	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	template_name = _item_tax_template_name(
		profile,
		{"posting_date": posting_date},
		{"item_code": item_code, "rate": base_net_rate},
	)
	if template_name:
		template = frappe.get_cached_doc("Item Tax Template", template_name)
		return sum(flt(tax.tax_rate) for tax in template.taxes)

	if profile.taxes_and_charges:
		charges = frappe.get_cached_doc("Sales Taxes and Charges Template", profile.taxes_and_charges)
		return sum(
			flt(tax.rate)
			for tax in charges.taxes
			if tax.charge_type in ("On Net Total", "On Previous Row Amount", "On Previous Row Total")
		)

	return 0
