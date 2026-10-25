"""POS Fiscal Receipt lifecycle. The sale id sent to the terminal is a GUID on POS Fiscal Receipt.uid."""

import json
import uuid

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, get_fullname, now_datetime

from erpnext_moldova_pos.services.pos_fiscal_receipt import attach_fiscal_receipt_pdf
from erpnext_moldova_pos.services.pos_call_service import as_dict, create_pos_call
from erpnext_moldova_pos.services.pos_command_payload import build_sale_data
from erpnext_moldova_pos.services.receipt_match import match_device_receipts, match_shift


LOCKED_STATUSES = ("Open", "Unreconciled", "Registered")


def prepare_sale_receipt(profile, invoice: dict) -> tuple:
	"""Return (receipt, action). action is reuse, create, submit_only, or locked."""

	sale = build_sale_data(invoice)
	cart_key = _cart_key(sale)
	requested = invoice.get("fiscal_receipt")
	open_receipts = _open_receipts(profile.pos_station, get_fullname(frappe.session.user))

	if requested:
		receipt = frappe.get_doc("POS Fiscal Receipt", requested)
		if receipt.pos_station != profile.pos_station or receipt.status not in LOCKED_STATUSES:
			frappe.throw(_("POS Fiscal Receipt {0} cannot be used for this sale.").format(requested))
		if receipt.resolution == "Printed" and not _linked_sale(receipt):
			return receipt, "submit_only"
		if receipt.cart_key != cart_key:
			_throw_locked(receipt)
		return receipt, "reuse"

	for receipt in open_receipts:
		if receipt.resolution == "Printed" and not _linked_sale(receipt) and receipt.cart_key == cart_key:
			return receipt, "submit_only"
		if receipt.cart_key == cart_key and receipt.status == "Open":
			return receipt, "reuse"
		if receipt.status in ("Open", "Unreconciled"):
			_throw_locked(receipt)

	return _insert_receipt(profile, invoice, sale, cart_key), "create"


def begin_attempt(receipt) -> None:
	receipt.db_set("attempt_count", int(receipt.attempt_count or 0) + 1, update_modified=True)


def link_failure_response(receipt) -> dict:
	attempt = int(frappe.db.get_value("POS Fiscal Receipt", receipt.name, "attempt_count") or 0)
	if attempt >= 2:
		outcome = "unconfirmed"
		message = _(
			"The operation could not be completed. Check that the receipt was not printed on the terminal."
		)
	else:
		outcome = "link_failure"
		message = _("The connection to the terminal failed.")
	return {
		"outcome": outcome,
		"fiscal_receipt": receipt.name,
		"attempt_count": attempt,
		"message": message,
	}


def _http_url(value) -> str:
	if not isinstance(value, str):
		return ""
	text = value.strip()
	if text.lower().startswith(("http://", "https://")):
		return text
	return ""


def mark_registered(receipt_name: str, result: dict) -> None:
	receipt = as_dict(result).get("receipt") or {}
	shift = as_dict(result).get("shift") or {}
	values = {"status": "Registered", "receipt_state": "Printed"}
	number = receipt.get("receipt_number")
	if number not in (None, ""):
		values["receipt_number"] = str(number)
	if shift.get("shift_id"):
		values["shift_id"] = str(shift.get("shift_id"))
	if receipt.get("receipt_id"):
		values["receipt_id"] = str(receipt.get("receipt_id"))
	url = _http_url(receipt.get("verification_url"))
	if url:
		values["mev_verification_url"] = url
	frappe.db.set_value("POS Fiscal Receipt", receipt_name, values, update_modified=True)
	copy_terminal_receipt(receipt_name, receipt, state="Printed")
	enqueue_terminal_receipt(receipt_name)


def mark_rejected(receipt_name: str) -> None:
	if not receipt_name:
		return
	status = frappe.db.get_value("POS Fiscal Receipt", receipt_name, "status")
	if status in ("Open", "Registered"):
		frappe.db.set_value("POS Fiscal Receipt", receipt_name, "status", "Rejected", update_modified=True)


def enqueue_terminal_receipt(receipt_name: str, *, force: bool = False):
	"""Ask the terminal for the closed receipt by the POS Fiscal Receipt uid."""

	receipt = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	uid = (receipt.uid or "").strip()
	if not uid:
		if force:
			frappe.throw(_("POS Fiscal Receipt {0} has no uid.").format(receipt_name))
		return None
	if not force and _command_in_flight(receipt.pos_station, "get_receipt", receipt_id=uid):
		return None
	return create_pos_call(
		command="get_receipt",
		pos_station=receipt.pos_station,
		pos_fiscal_receipt=receipt.name,
		data={"uid": uid},
		include_uid=False,
	)


def copy_terminal_receipt(receipt_name: str, device: dict, state: str = "Confirmed") -> None:
	"""Replace the receipt snapshot with the terminal copy. ERP values are only a placeholder until this arrives."""

	if not isinstance(device, dict) or not device:
		return
	doc = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	doc.receipt_state = state
	if device.get("uid"):
		doc.uid = str(device.get("uid"))
	if device.get("receipt_id"):
		doc.receipt_id = str(device.get("receipt_id"))
	number = device.get("receipt_number")
	if number not in (None, ""):
		doc.receipt_number = str(number)
	if device.get("mev_id"):
		doc.mev_id = str(device.get("mev_id"))
	url = _http_url(device.get("verification_url"))
	if url:
		doc.mev_verification_url = url
	if device.get("amount") is not None:
		doc.grand_total = flt(device.get("amount"))
	if device.get("change") is not None:
		doc.change = flt(device.get("change"))
	if device.get("deposit") is not None:
		doc.deposit = flt(device.get("deposit"))
	if device.get("date"):
		doc.sale_at = get_datetime(device.get("date"))
	_copy_text(doc, "company_name", device.get("company"))
	_copy_text(doc, "tax_id", device.get("company_idno"))
	_copy_text(doc, "registration_number", device.get("registration_number"))
	_copy_text(doc, "address_display", device.get("sales_point_address"))
	_copy_text(doc, "device_serial", device.get("factory_number"))
	_copy_text(doc, "device_id", device.get("device_id"))
	_copy_text(doc, "shift_number", device.get("shift_number"))
	if isinstance(device.get("items"), list) and device["items"]:
		doc.set("items", [_terminal_item(row) for row in device["items"] if isinstance(row, dict)])
	if isinstance(device.get("payments"), list):
		doc.set("payments", [_terminal_payment(row) for row in device["payments"] if isinstance(row, dict)])
	if isinstance(device.get("taxes"), list):
		doc.set("taxes", [tax for row in device["taxes"] if isinstance(row, dict) and (tax := _terminal_tax(row))])
	doc.flags.ignore_permissions = True
	doc.save()


def _copy_text(doc, field: str, value) -> None:
	if isinstance(value, str) and value.strip():
		doc.set(field, value.strip())


def _terminal_item(row: dict) -> dict:
	item = {
		"item_code": row.get("code"),
		"item_name": row.get("name"),
		"qty": row.get("qty"),
		"uom": row.get("unit"),
		"rate": row.get("price"),
		"total": row.get("total"),
		"amount": row.get("amount"),
	}
	item.update(_item_tax(row.get("tax")))
	item.update(_named_pair(row.get("discount"), "discount_percent", "discount_amount"))
	item.update(_named_pair(row.get("margin"), "margin_percent", "margin_amount"))
	return item


def _item_tax(tax) -> dict:
	if not isinstance(tax, dict):
		return {}
	values = {}
	if "code" in tax:
		values["tax_code"] = tax.get("code")
	if tax.get("percent") is not None:
		values["tax_percent"] = tax.get("percent")
	if tax.get("amount") is not None:
		values["tax_amount"] = tax.get("amount")
	if tax.get("brut") is not None:
		values["tax_brut"] = tax.get("brut")
	if "noVat" in tax:
		values["no_vat"] = 1 if tax.get("noVat") else 0
	return values


def _named_pair(block, percent_field: str, amount_field: str) -> dict:
	if not isinstance(block, dict):
		return {}
	values = {}
	if block.get("percent") is not None:
		values[percent_field] = block.get("percent")
	if block.get("amount") is not None:
		values[amount_field] = block.get("amount")
	return values


def _terminal_payment(row: dict) -> dict:
	return {
		"payment_type": row.get("type"),
		"mode_of_payment": row.get("mode_of_payment"),
		"amount": row.get("amount"),
	}


def _terminal_tax(row: dict) -> dict | None:
	code = row.get("code")
	gross = row.get("gross")
	vat = row.get("vat")
	if code in (None, "") or gross is None or vat is None:
		return None
	return {
		"tax_code": code,
		"tax_rate": row.get("rate"),
		"gross_amount": gross,
		"vat_amount": vat,
	}


def finish_invoice(
	receipt_name: str, invoice_name: str, *, unreconciled: bool, doctype: str = "Sales Invoice"
) -> None:
	status = "Unreconciled" if unreconciled else "Invoiced"
	# The station writes this row while the sale request is waiting. Commit first so
	# the update does not run against a snapshot MariaDB has already invalidated.
	frappe.db.commit()
	link_field = "sales_order" if doctype == "Sales Order" else "sales_invoice"
	values = {link_field: invoice_name, "status": status}
	try:
		frappe.db.set_value("POS Fiscal Receipt", receipt_name, values, update_modified=True)
	except frappe.QueryDeadlockError:
		frappe.db.rollback()
		frappe.db.set_value("POS Fiscal Receipt", receipt_name, values, update_modified=True)


def cancel_receipt(receipt_name: str) -> None:
	receipt = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	if receipt.status != "Open":
		frappe.throw(_("POS Fiscal Receipt {0} can no longer be cancelled.").format(receipt_name))
	receipt.db_set(
		{
			"status": "Rejected",
			"resolution": "Cancelled",
			"resolved_on": now_datetime(),
		},
		update_modified=True,
	)


def mark_printed(receipt_name: str) -> None:
	receipt = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	if _linked_sale(receipt):
		return
	if receipt.status != "Open":
		frappe.throw(_("POS Fiscal Receipt {0} is not waiting for confirmation.").format(receipt_name))
	receipt.db_set(
		{"resolution": "Printed", "resolved_on": now_datetime()},
		update_modified=True,
	)


def enqueue_one(receipt_name: str, receipt_number: str | None = None, mev_id: str | None = None, shift_id: str | None = None) -> dict:
	"""Manual match. A Not Found receipt becomes Unreconciled again for one more lookup."""

	receipt = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	if receipt.status not in ("Unreconciled", "Not Found"):
		frappe.throw(_("POS Fiscal Receipt {0} is not waiting for device details.").format(receipt_name))
	updates = {}
	if receipt.status == "Not Found":
		updates["status"] = "Unreconciled"
	if receipt_number:
		updates["receipt_number"] = receipt_number
	if mev_id:
		updates["mev_id"] = mev_id
	if shift_id:
		updates["shift_id"] = shift_id
	if updates:
		frappe.db.set_value("POS Fiscal Receipt", receipt_name, updates, update_modified=True)
	receipt = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	_queue_lookup(receipt)
	return {"fiscal_receipt": receipt_name, "status": "Unreconciled"}


def enqueue_reconcile() -> None:
	names = frappe.get_all("POS Fiscal Receipt", filters={"status": "Unreconciled"}, pluck="name")
	for name in names:
		_queue_lookup(frappe.get_doc("POS Fiscal Receipt", name))


def _queue_lookup(receipt) -> None:
	"""Ask the station for lists or one receipt. Matching stays in ERPNext."""

	if not receipt.shift_id:
		if not _command_in_flight(receipt.pos_station, "list_shifts"):
			create_pos_call(command="list_shifts", pos_station=receipt.pos_station, data={}, include_uid=False)
		return
	if not receipt.receipt_id:
		if not _command_in_flight(receipt.pos_station, "list_shift_receipts", shift_id=receipt.shift_id):
			create_pos_call(
				command="list_shift_receipts",
				pos_station=receipt.pos_station,
				data={"shift_id": receipt.shift_id},
				include_uid=False,
			)
		return
	if not _command_in_flight(receipt.pos_station, "get_receipt", receipt_id=receipt.uid):
		create_pos_call(
			command="get_receipt",
			pos_station=receipt.pos_station,
			pos_fiscal_receipt=receipt.name,
			data={"uid": receipt.uid},
			include_uid=False,
		)


def apply_shift_list(pos_call_name: str, success: bool) -> None:
	if not success:
		return
	pos_call = frappe.get_doc("POS Call", pos_call_name)
	shifts = as_dict(pos_call.result).get("shifts") or []
	names = frappe.get_all(
		"POS Fiscal Receipt",
		filters={"status": "Unreconciled", "pos_station": pos_call.pos_station, "shift_id": ["in", ["", None]]},
		pluck="name",
	)
	for name in names:
		receipt = frappe.get_doc("POS Fiscal Receipt", name)
		chosen = match_shift(shifts, receipt.sale_at)
		if not chosen:
			if shifts:
				frappe.db.set_value("POS Fiscal Receipt", name, "status", "Not Found", update_modified=True)
			continue
		frappe.db.set_value(
			"POS Fiscal Receipt",
			name,
			"shift_id",
			str(chosen.get("shift_id")),
			update_modified=True,
		)
		_queue_lookup(frappe.get_doc("POS Fiscal Receipt", name))


def apply_shift_receipts(pos_call_name: str, success: bool) -> None:
	if not success:
		return
	pos_call = frappe.get_doc("POS Call", pos_call_name)
	shift_id = str(as_dict(pos_call.payload).get("data", {}).get("shift_id") or "")
	rows = as_dict(pos_call.result).get("receipts") or []
	names = frappe.get_all(
		"POS Fiscal Receipt",
		filters={
			"status": "Unreconciled",
			"pos_station": pos_call.pos_station,
			"shift_id": shift_id,
			"receipt_id": ["in", ["", None]],
		},
		pluck="name",
	)
	names = [name for name in names if not _get_receipt_started(name)]
	claimed = set(
		frappe.get_all(
			"POS Fiscal Receipt",
			filters={"uid": ["is", "set"]},
			pluck="uid",
		)
	)
	for name in names:
		receipt = frappe.get_doc("POS Fiscal Receipt", name)
		chosen = match_device_receipts(
			rows,
			amount=receipt.grand_total,
			attempted_at=receipt.sale_at,
			known_ids=claimed - {receipt.uid or ""},
			mev_id=receipt.mev_id,
		)
		device_uid = str((chosen or {}).get("uid") or "")
		if not device_uid:
			frappe.db.set_value("POS Fiscal Receipt", name, "status", "Not Found", update_modified=True)
			continue
		claimed.add(device_uid)
		values = {"uid": device_uid}
		terminal_id = chosen.get("receipt_id")
		if terminal_id not in (None, ""):
			values["receipt_id"] = str(terminal_id)
		if chosen.get("mev_id"):
			values["mev_id"] = str(chosen.get("mev_id"))
		frappe.db.set_value("POS Fiscal Receipt", name, values, update_modified=True)
		updated = frappe.get_doc("POS Fiscal Receipt", name)
		if not _command_in_flight(updated.pos_station, "get_receipt", receipt_id=updated.uid):
			create_pos_call(
				command="get_receipt",
				pos_station=updated.pos_station,
				pos_fiscal_receipt=updated.name,
				data={"uid": updated.uid},
				include_uid=False,
			)


def apply_receipt_detail(pos_call_name: str, success: bool) -> None:
	pos_call = frappe.get_doc("POS Call", pos_call_name)
	receipt_name = pos_call.pos_fiscal_receipt
	if not receipt_name:
		return
	status = frappe.db.get_value("POS Fiscal Receipt", receipt_name, "status")
	if status == "Unreconciled":
		if not success:
			frappe.db.set_value("POS Fiscal Receipt", receipt_name, "status", "Not Found", update_modified=True)
			return
		device = as_dict(pos_call.result).get("receipt") or {}
		_confirm_receipt(receipt_name, device)
		frappe.db.set_value("POS Fiscal Receipt", receipt_name, "status", "Invoiced", update_modified=True)
		return
	if status not in ("Registered", "Invoiced") or not success:
		return
	_confirm_receipt(receipt_name, as_dict(pos_call.result).get("receipt") or {})


def _confirm_receipt(receipt_name: str, device: dict) -> None:
	previous = frappe.db.get_value("POS Fiscal Receipt", receipt_name, "receipt_state")
	copy_terminal_receipt(receipt_name, device)
	if previous != "Confirmed" and frappe.db.get_value("POS Fiscal Receipt", receipt_name, "receipt_state") == "Confirmed":
		attach_fiscal_receipt_pdf(receipt_name)


def _insert_receipt(profile, invoice: dict, sale: dict, cart_key: str):
	items = []
	for item in sale.get("items") or []:
		items.append(
			{
				"item_code": item.get("code"),
				"item_name": item.get("name"),
				"qty": item.get("qty"),
				"uom": item.get("unit"),
				"rate": item.get("price"),
				"total": flt(flt(item.get("qty")) * flt(item.get("price")), 2),
				"amount": item.get("amount"),
			}
		)
	doc = frappe.get_doc(
		{
			"doctype": "POS Fiscal Receipt",
			"pos_station": profile.pos_station,
			"pos_profile": profile.name,
			"pos_opening_shift": invoice.get("posa_pos_opening_shift") or None,
			"company": profile.company,
			"cashier": get_fullname(frappe.session.user),
			"grand_total": flt(sale.get("amount")),
			"currency": sale.get("currency"),
			"cart_key": cart_key,
			"uid": str(uuid.uuid4()),
			"sale_at": now_datetime(),
			"status": "Open",
			"items": items,
			"payments": [
				{
					"payment_type": row.get("type"),
					"mode_of_payment": row.get("mode_of_payment"),
					"amount": row.get("amount"),
				}
				for row in sale.get("payments") or []
			],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _cart_key(sale: dict) -> str:
	payload = {
		"amount": flt(sale.get("amount")),
		"items": [
			{
				"code": item.get("code"),
				"qty": flt(item.get("qty")),
				"price": flt(item.get("price")),
				"amount": flt(item.get("amount")),
				"tax": [flt(rate) for rate in item.get("tax_rates") or []],
			}
			for item in sale.get("items") or []
		],
		"payments": [
			{"type": row.get("type"), "mode": row.get("mode_of_payment"), "amount": flt(row.get("amount"))}
			for row in sale.get("payments") or []
		],
	}
	return frappe.generate_hash(json.dumps(payload, sort_keys=True, default=str), length=16)


def _open_receipts(pos_station: str, cashier: str):
	names = frappe.get_all(
		"POS Fiscal Receipt",
		filters={
			"pos_station": pos_station,
			"cashier": cashier,
			"status": ["in", ["Open", "Unreconciled"]],
			"sales_invoice": ["is", "not set"],
			"sales_order": ["is", "not set"],
		},
		order_by="creation asc",
		pluck="name",
	)
	return [frappe.get_doc("POS Fiscal Receipt", name) for name in names]


def _get_receipt_started(receipt_name: str) -> bool:
	return bool(
		frappe.get_all(
			"POS Call",
			filters={
				"command": "get_receipt",
				"pos_fiscal_receipt": receipt_name,
				"status": ["in", ["Pending", "Sent", "Completed"]],
			},
			limit=1,
		)
	)


def _command_in_flight(pos_station: str, command: str, *, shift_id: str | None = None, receipt_id: str | None = None) -> bool:
	rows = frappe.get_all(
		"POS Call",
		filters={"pos_station": pos_station, "command": command, "status": ["in", ["Pending", "Sent"]]},
		fields=["payload"],
	)
	for row in rows:
		data = as_dict(row.payload).get("data") or {}
		if shift_id is not None and str(data.get("shift_id") or "") != str(shift_id):
			continue
		if receipt_id is not None and str(data.get("uid") or data.get("receipt_id") or "") != str(receipt_id):
			continue
		return True
	return False


def _linked_sale(receipt) -> str | None:
	return receipt.sales_invoice or receipt.sales_order


def _throw_locked(receipt) -> None:
	frappe.throw(
		_(
			"POS Fiscal Receipt {0} is still open for the previous cart. Repeat that sale, or wait until the terminal rejects it, before changing the items."
		).format(receipt.name),
		title=_("POS Station"),
	)
