import json

import frappe
from frappe import _
from frappe.utils import flt


POS_COMMANDS = (
	"open_shift",
	"close_shift",
	"sale",
	"list_shifts",
	"list_shift_receipts",
	"get_receipt",
	"cash_deposit",
	"cash_withdrawal",
)


def build_open_shift_data(balance_details) -> dict:
	"""Neutral open-shift command.

	Asks the station to report device state. Opening cash is included so an
	adapter can record it. This is not a device-protocol open call.

	SmartOne only opens the shift. The device keeps the drawer from the
	previous shift, and opening_balances is a reconciliation with ERPNext.

	MCR has no open-shift operation. A Z-report leaves the drawer at 0.
	The adapter still reads device state, then deposits cash with
	RegisterServiceReceipt: every opening_balances row whose mode of payment
	is Cash, in lei, with no conversion to bani. Card and other modes stay
	out of the drawer. A zero cash sum is not sent; the device rejects it.
	"""

	return {"opening_balances": _opening_balances(balance_details)}


def build_close_shift_data() -> dict:
	"""Neutral close-shift command. The adapter decides how the device closes."""

	return {}


def build_sale_data(invoice: dict) -> dict:
	"""Neutral sale command. Amounts are currency units, quantities are counts."""

	return {
		"document_number": invoice.get("name") or "",
		"currency": invoice.get("currency"),
		"amount": flt(
			invoice.get("base_grand_total") or invoice.get("grand_total") or invoice.get("base_total")
		),
		"items": [
			_sale_item(item, invoice.get("company")) for item in invoice.get("items") or []
		],
		"payments": _sale_payments(invoice.get("payments") or []),
	}


def _opening_balances(balance_details) -> list[dict]:
	if isinstance(balance_details, str):
		balance_details = json.loads(balance_details) if balance_details else []

	balances = []
	for row in balance_details or []:
		mode = row.get("mode_of_payment") or ""
		payment_type = row.get("type") or ("Cash" if str(mode).strip().lower() == "cash" else mode)
		balances.append(
			{
				"type": payment_type,
				"mode_of_payment": mode,
				"amount": flt(row.get("opening_amount", row.get("amount", 0))),
			}
		)
	return balances


def _sale_item(item: dict, company: str | None = None) -> dict:
	tax_rates = _tax_rates(item, company)
	if not tax_rates:
		frappe.throw(
			_(
				"Item {0} has no tax rate. Set an Item Tax Template before selling it. The fiscal device needs a rate such as 20% or 0%."
			).format(item.get("item_code") or item.get("item_name") or "—"),
			title=_("POS Station"),
		)
	qty = flt(item.get("qty") if item.get("qty") is not None else item.get("stock_qty"))
	base_price = flt(
		item.get("base_price_list_rate")
		or item.get("price_list_rate")
		or item.get("base_rate")
		or item.get("rate"),
		2,
	)
	reduced_cost = flt(
		item.get("base_amount") if item.get("base_amount") is not None else item.get("amount"),
		2,
	)
	# The station reads price, a numeric line discount, and amount. It does not
	# derive the line total from qty and price.
	return {
		"code": item.get("item_code"),
		"name": item.get("item_name"),
		"qty": qty,
		"unit": item.get("uom") or item.get("stock_uom"),
		"price": base_price,
		"discount": _line_discount(item, qty),
		"amount": reduced_cost,
		"tax_rates": tax_rates,
	}


def _line_discount(item: dict, qty: float) -> float:
	"""Line discount. ERP stores discount_amount per unit."""

	return flt(flt(item.get("discount_amount")) * qty, 2)


def _tax_rates(item: dict, company: str | None = None) -> list[float]:
	template = item.get("item_tax_template") or _template_from_original_row(item)
	if not template:
		template = _template_from_item_master(item.get("item_code"), company)
	if template:
		tax_template = frappe.get_doc("Item Tax Template", template)
		return [flt(tax.tax_rate) for tax in tax_template.taxes]

	return _rates_from_item_tax_rate(item.get("item_tax_rate"))


def _template_from_original_row(item: dict) -> str | None:
	"""POSNext returns omit the tax template and keep only the original row link."""

	row_name = item.get("sales_invoice_item")
	if not row_name:
		return None

	return frappe.db.get_value("Sales Invoice Item", row_name, "item_tax_template")


def _template_from_item_master(item_code: str | None, company: str | None) -> str | None:
	"""POS cart lines often omit the tax template even when the item has one."""

	if not item_code:
		return None

	rows = frappe.get_all(
		"Item Tax",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["item_tax_template"],
		order_by="idx asc",
	)
	templates = [row.item_tax_template for row in rows if row.item_tax_template]
	if company:
		for template in templates:
			template_company = frappe.db.get_value("Item Tax Template", template, "company")
			if template_company in (company, None, ""):
				return template
	return templates[0] if templates else None


def _rates_from_item_tax_rate(item_tax_rate) -> list[float]:
	if not item_tax_rate:
		return []
	if isinstance(item_tax_rate, str):
		item_tax_rate = json.loads(item_tax_rate)
	if not isinstance(item_tax_rate, dict):
		return []
	return [flt(rate) for rate in item_tax_rate.values()]


def _sale_payments(payments: list) -> list[dict]:
	rows = []
	for payment in payments:
		amount = flt(payment.get("amount") or 0)
		if not amount:
			continue
		rows.append(
			{
				"type": payment.get("type"),
				"mode_of_payment": payment.get("mode_of_payment"),
				"amount": amount,
			}
		)
	return rows
