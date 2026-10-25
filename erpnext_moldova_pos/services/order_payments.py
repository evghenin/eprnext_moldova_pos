"""Sales Order has no payments table. POS Next drops those rows when it saves the draft."""

import json

import frappe


_TTL_SECONDS = 60 * 60


def remember(order_name: str, payments) -> None:
	if not order_name or not payments:
		return
	frappe.cache.set_value(_key(order_name), payments, expires_in_sec=_TTL_SECONDS)


def restore(invoice: dict) -> None:
	"""Put the cashier's tender back on the payload used for the fiscal sale."""

	if invoice.get("doctype") != "Sales Order" or invoice.get("payments"):
		return
	name = invoice.get("name")
	if not name:
		return
	stored = frappe.cache.get_value(_key(name))
	if stored:
		invoice["payments"] = stored


def payments_from_update(data) -> tuple[str, str | None, list]:
	parsed = json.loads(data) if isinstance(data, str) else data
	parsed = parsed or {}
	return parsed.get("doctype") or "Sales Invoice", parsed.get("name"), list(parsed.get("payments") or [])


def _key(order_name: str) -> str:
	return f"moldova_pos:order_payments:{order_name}"
