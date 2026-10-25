from frappe import _


def get_dashboard_data(data):
	"""Show fiscal receipts linked from this sales invoice."""

	reference = next((group for group in data.get("transactions") or [] if group.get("label") == _("Reference")), None)
	if reference is None:
		data.setdefault("transactions", []).append({"label": _("Reference"), "items": ["POS Fiscal Receipt"]})
		return data
	if "POS Fiscal Receipt" not in reference["items"]:
		reference["items"].append("POS Fiscal Receipt")
	return data
