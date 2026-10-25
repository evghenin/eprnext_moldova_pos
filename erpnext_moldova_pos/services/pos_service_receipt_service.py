"""Cash deposit and collection during an open shift.

The terminal ignores data.uid for these commands, so a lost answer is reconciled
from the shift history instead of being sent again.
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from erpnext_moldova_pos.services.pos_call_failure import station_error_detail
from erpnext_moldova_pos.services.pos_call_service import as_dict, create_pos_call
from erpnext_moldova_pos.services.pos_call_waiter import wait_for_pos_call_result_short
from erpnext_moldova_pos.services.pos_fiscal_receipt import attach_service_receipt_pdf


COMMAND_WAIT_SECONDS = 60
CLOCK_SLACK = timedelta(seconds=120)


def movement_state(pos_profile: str, opening_shift: str) -> dict:
	profile = _open_profile(pos_profile, opening_shift)
	enabled = bool(profile.pos_station and profile.cash_out_account)
	pending = _pending(opening_shift) if enabled else None
	rows = []
	if enabled:
		rows = frappe.get_all(
			"POS Service Receipt",
			filters={"pos_opening_shift": opening_shift, "status": "Registered"},
			fields=["name", "movement_type", "reason", "amount", "receipt_number"],
			order_by="creation asc",
		)
	return {
		"enabled": enabled,
		"unreconciled": _public(pending) if pending else None,
		"movements": rows,
	}


def submit_movement(pos_profile: str, opening_shift: str, movement_type: str, amount) -> dict:
	profile = _open_profile(pos_profile, opening_shift)
	_require_station(profile)
	require_cash_accounts(profile)
	if _pending(opening_shift):
		frappe.throw(_("Confirm the previous cash movement before starting another one."))
	movement_type = _movement_type(movement_type)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("The amount must be greater than zero."))

	receipt = frappe.get_doc(
		{
			"doctype": "POS Service Receipt",
			"status": "Unreconciled",
			"movement_type": movement_type,
			"reason": "collection" if movement_type == "withdrawal" else "",
			"amount": amount,
			"pos_opening_shift": opening_shift,
			"pos_station": profile.pos_station,
			"pos_profile": profile.name,
			"company": profile.company,
			"cashier": frappe.session.user,
			"attempted_at": now_datetime(),
		}
	)
	receipt.insert(ignore_permissions=True)
	command = "cash_deposit" if movement_type == "deposit" else "cash_withdrawal"
	data = {"amount": amount}
	if movement_type == "withdrawal":
		data["reason"] = "collection"
	pos_call = create_pos_call(
		command=command,
		pos_station=profile.pos_station,
		data=data,
		pos_service_receipt=receipt.name,
		include_uid=False,
	)
	receipt.db_set("pos_call", pos_call.name, update_modified=True)
	status = wait_for_pos_call_result_short(pos_call.name, timeout=COMMAND_WAIT_SECONDS)
	if status == "Completed":
		result = as_dict(frappe.db.get_value("POS Call", pos_call.name, "result"))
		_register_from_result(receipt.name, result)
		return {"outcome": "registered", "receipt": _registered(receipt.name, _cash_in_drawer(result.get("receipt")))}
	if status == "Failed":
		message = station_error_detail(as_dict(frappe.db.get_value("POS Call", pos_call.name, "result")))
		frappe.delete_doc("POS Service Receipt", receipt.name, ignore_permissions=True, force=True)
		return {"outcome": "rejected", "message": message or _("The POS station rejected the cash movement.")}
	return {"outcome": "unconfirmed", "receipt": _public(frappe.get_doc("POS Service Receipt", receipt.name))}


def mark_not_printed(receipt_name: str) -> dict:
	receipt = _pending_doc(receipt_name)
	receipt.db_set("status", "Rejected", update_modified=True)
	return {"outcome": "rejected", "receipt": receipt.name}


def load_printed(receipt_name: str, receipt_id: str | None = None) -> dict:
	receipt = _pending_doc(receipt_name)
	profile = frappe.get_doc("POS Profile", receipt.pos_profile)
	if receipt_id:
		return _fetch_one(receipt, profile, str(receipt_id))
	shift_id = _fiscal_shift_id(receipt)
	if not shift_id:
		return {"outcome": "load_failed", "receipt": _public(receipt)}
	pos_call = create_pos_call(
		command="list_shift_receipts",
		pos_station=profile.pos_station,
		data={"shift_id": shift_id},
		pos_service_receipt=receipt.name,
		include_uid=False,
	)
	status = wait_for_pos_call_result_short(pos_call.name, timeout=COMMAND_WAIT_SECONDS)
	if status != "Completed":
		return {"outcome": "load_failed", "receipt": _public(receipt)}
	rows = as_dict(frappe.db.get_value("POS Call", pos_call.name, "result")).get("receipts") or []
	candidates = _matching_rows(receipt, rows)
	if len(candidates) == 1:
		return _fetch_one(receipt, profile, _list_uid(candidates[0]))
	if len(candidates) > 1:
		return {
			"outcome": "choose",
			"receipt": _public(receipt),
			"candidates": [_candidate(row) for row in candidates],
		}
	return {"outcome": "load_failed", "receipt": _public(receipt)}


def assert_shift_can_close(opening_shift: str) -> None:
	if _pending(opening_shift):
		frappe.throw(_("Confirm whether the cash movement receipt was printed before closing the shift."))


def apply_to_expected_cash(opening_shift: str, payments: list, cash_mode: str) -> tuple[float, float]:
	assert_shift_can_close(opening_shift)
	deposits = 0.0
	collections = 0.0
	for row in frappe.get_all(
		"POS Service Receipt",
		filters={"pos_opening_shift": opening_shift, "status": "Registered"},
		fields=["movement_type", "reason", "amount"],
	):
		amount = flt(row.amount)
		if row.movement_type == "deposit":
			deposits += amount
			_add_cash(payments, cash_mode, amount)
		elif row.movement_type == "withdrawal" and row.reason == "collection":
			collections += amount
			_add_cash(payments, cash_mode, -amount)
	return deposits, collections


def _fetch_one(receipt, profile, receipt_id: str) -> dict:
	"""`receipt_id` here is the shift-list uid. get_receipt is addressed by the POS Service Receipt uid."""

	uid = (receipt_id or "").strip()
	if uid:
		frappe.db.set_value("POS Service Receipt", receipt.name, "uid", uid, update_modified=True)
	if not uid:
		return {"outcome": "load_failed", "receipt": _public(receipt)}
	pos_call = create_pos_call(
		command="get_receipt",
		pos_station=profile.pos_station,
		data={"uid": uid},
		pos_service_receipt=receipt.name,
		include_uid=False,
	)
	status = wait_for_pos_call_result_short(pos_call.name, timeout=COMMAND_WAIT_SECONDS)
	if status != "Completed":
		return {"outcome": "load_failed", "receipt": _public(receipt)}
	device = as_dict(frappe.db.get_value("POS Call", pos_call.name, "result")).get("receipt") or {}
	if not device:
		return {"outcome": "load_failed", "receipt": _public(receipt)}
	_register_from_device(receipt.name, device, pos_call.name, mev_id=device.get("mev_id"))
	return {"outcome": "registered", "receipt": _registered(receipt.name, _cash_in_drawer(device))}


def _register_from_result(receipt_name: str, result: dict) -> None:
	device = result.get("receipt") or {}
	loaded = _load_get_receipt(receipt_name, device)
	if loaded:
		for key in (
			"company",
			"company_idno",
			"registration_number",
			"sales_point_address",
			"factory_number",
			"verification_url",
		):
			if not device.get(key) and loaded.get(key):
				device[key] = loaded.get(key)
	_register_from_device(
		receipt_name,
		device,
		None,
		result.get("shift") or {},
		mev_id=(loaded or {}).get("mev_id"),
	)


def _load_get_receipt(receipt_name: str, device: dict) -> dict:
	"""The cash command receipt does not carry MEV. get_receipt does, keyed by the document uid."""

	receipt = frappe.get_doc("POS Service Receipt", receipt_name)
	uid = (receipt.uid or "").strip() or str(device.get("uid") or "").strip()
	if not uid:
		return None
	if not (receipt.uid or "").strip():
		frappe.db.set_value("POS Service Receipt", receipt.name, "uid", uid, update_modified=True)
	pos_call = create_pos_call(
		command="get_receipt",
		pos_station=receipt.pos_station,
		data={"uid": uid},
		pos_service_receipt=receipt.name,
		include_uid=False,
	)
	status = wait_for_pos_call_result_short(pos_call.name, timeout=COMMAND_WAIT_SECONDS)
	if status != "Completed":
		return {}
	return as_dict(frappe.db.get_value("POS Call", pos_call.name, "result")).get("receipt") or {}


def enqueue_terminal_refresh(receipt_name: str):
	"""Ask the terminal for this service receipt. The station answers in the background."""

	receipt = frappe.get_doc("POS Service Receipt", receipt_name)
	uid = (receipt.uid or "").strip()
	if not uid:
		frappe.throw(_("POS Service Receipt {0} has no uid.").format(receipt_name))
	from erpnext_moldova_pos.services.pos_fiscal_receipt_service import _command_in_flight

	if _command_in_flight(receipt.pos_station, "get_receipt", receipt_id=uid):
		return None
	return create_pos_call(
		command="get_receipt",
		pos_station=receipt.pos_station,
		data={"uid": uid},
		pos_service_receipt=receipt.name,
		include_uid=False,
	)


def apply_terminal_refresh(pos_call_name: str, success: bool) -> None:
	"""Copy a finished get_receipt onto an already registered service receipt."""

	pos_call = frappe.get_doc("POS Call", pos_call_name)
	receipt_name = pos_call.pos_service_receipt
	if not receipt_name or not success:
		return
	if frappe.db.get_value("POS Service Receipt", receipt_name, "status") != "Registered":
		return
	device = as_dict(pos_call.result).get("receipt") or {}
	if not device:
		return
	_register_from_device(receipt_name, device, None, link_journal=False, attach=False)


def _register_from_device(
	receipt_name: str,
	device: dict,
	pos_call: str | None,
	shift: dict | None = None,
	mev_id=None,
	*,
	link_journal: bool = True,
	attach: bool = True,
) -> None:
	receipt = frappe.get_doc("POS Service Receipt", receipt_name)
	drawer = _cash_in_drawer(device)
	if drawer not in (None, ""):
		receipt.cash_in_drawer = flt(drawer)
	if device.get("receipt_number") not in (None, ""):
		receipt.receipt_number = str(device.get("receipt_number"))
	if device.get("receipt_id") not in (None, ""):
		receipt.receipt_id = str(device.get("receipt_id"))
	if device.get("uid") not in (None, ""):
		receipt.uid = str(device.get("uid"))
	if device.get("mev_id") not in (None, ""):
		receipt.mev_id = str(device.get("mev_id"))
	if mev_id not in (None, ""):
		receipt.mev_id = str(mev_id)
	if device.get("currency") not in (None, ""):
		receipt.currency = str(device.get("currency"))
	_copy_text(receipt, "company_name", device.get("company"))
	_copy_text(receipt, "tax_id", device.get("company_idno"))
	_copy_text(receipt, "registration_number", device.get("registration_number"))
	_copy_text(receipt, "address_display", device.get("sales_point_address"))
	_copy_text(receipt, "device_serial", device.get("factory_number"))
	_copy_text(receipt, "device_id", device.get("device_id"))
	_copy_text(receipt, "shift_number", device.get("shift_number"))
	url = device.get("verification_url")
	if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
		receipt.mev_verification_url = url.strip()
	shift = shift or {}
	if shift.get("shift_id"):
		receipt.shift_id = str(shift.get("shift_id"))
	elif device.get("shift_id"):
		receipt.shift_id = str(device.get("shift_id"))
	if pos_call:
		receipt.pos_call = pos_call
	if link_journal:
		receipt.journal_entry = _journal_entry(receipt)
		receipt.status = "Registered"
	receipt.flags.ignore_permissions = True
	receipt.save(ignore_permissions=True)
	if attach:
		attach_service_receipt_pdf(receipt.name)


def _copy_text(doc, field: str, value) -> None:
	if isinstance(value, str) and value.strip():
		doc.set(field, value.strip())


def _journal_entry(receipt) -> str:
	if receipt.journal_entry:
		return receipt.journal_entry
	profile = frappe.get_doc("POS Profile", receipt.pos_profile)
	if receipt.movement_type == "deposit":
		remark = _("Cash deposit {0}").format(receipt.name)
		kind = "deposit"
	else:
		remark = _("Cash collection {0}").format(receipt.name)
		kind = "collection"
	return _submit_cash_journal(profile, flt(receipt.amount), kind, remark)


def post_opening_cash_deposit(opening_shift: str, balance_details) -> None:
	"""Journal for the cash put into a drawer that a Z-report had left at zero."""

	opening = frappe.db.get_value(
		"POS Opening Shift",
		opening_shift,
		["opening_cash_journal_entry", "pos_profile"],
		as_dict=True,
	)
	if not opening or opening.opening_cash_journal_entry:
		return
	profile = frappe.get_doc("POS Profile", opening.pos_profile)
	if not _resets_cashbox(profile):
		return
	amount = _opening_cash_amount(profile, balance_details)
	if amount <= 0:
		return
	entry = _submit_cash_journal(
		profile,
		amount,
		"deposit",
		_("Cash deposit on shift opening {0}").format(opening_shift),
	)
	frappe.db.set_value(
		"POS Opening Shift",
		opening_shift,
		"opening_cash_journal_entry",
		entry,
		update_modified=False,
	)


def post_closing_cash_collection(closing_shift: str) -> None:
	"""Journal for the expected cash a Z-report removes from the drawer."""

	closing = frappe.db.get_value(
		"POS Closing Shift",
		closing_shift,
		["closing_cash_journal_entry", "pos_profile"],
		as_dict=True,
	)
	if not closing or closing.closing_cash_journal_entry:
		return
	profile = frappe.get_doc("POS Profile", closing.pos_profile)
	if not _resets_cashbox(profile):
		return
	amount = _expected_cash(closing_shift, _cash_mode(profile))
	if amount <= 0:
		return
	entry = _submit_cash_journal(
		profile,
		amount,
		"collection",
		_("Cash collection on shift closing {0}").format(closing_shift),
	)
	frappe.db.set_value(
		"POS Closing Shift",
		closing_shift,
		"closing_cash_journal_entry",
		entry,
		update_modified=False,
	)


def require_cashbox_reset_accounts(profile) -> None:
	"""Block open and close when this station's app zeros the drawer and accounts are missing."""

	if _resets_cashbox(profile):
		require_cash_accounts(profile)


def _resets_cashbox(profile) -> bool:
	if not profile.pos_station:
		return False
	from erpnext_moldova_pos.services.pos_station_device_selector import select_station_device_for_command

	_device, app = select_station_device_for_command(pos_station=profile.pos_station, command="open_shift")
	return bool(app.reset_cashbox_on_shift_close)


def _submit_cash_journal(profile, amount: float, kind: str, remark: str) -> str:
	cash_account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": _cash_mode(profile), "company": profile.company},
		"default_account",
	)
	if not cash_account or not profile.cash_out_account:
		require_cash_accounts(profile)
	if kind == "deposit":
		debit, credit = cash_account, profile.cash_out_account
	else:
		debit, credit = profile.cash_out_account, cash_account
	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": profile.company,
			"posting_date": now_datetime().date(),
			"user_remark": remark,
			"accounts": [
				{"account": debit, "debit_in_account_currency": amount},
				{"account": credit, "credit_in_account_currency": amount},
			],
		}
	)
	entry.insert(ignore_permissions=True)
	entry.submit()
	return entry.name


def _cash_mode(profile) -> str:
	return frappe.db.get_value("POS Profile", profile.name, "posa_cash_mode_of_payment") or "Cash"


def _opening_cash_amount(profile, balance_details) -> float:
	if isinstance(balance_details, str):
		balance_details = frappe.parse_json(balance_details) if balance_details else []
	cash_mode = _cash_mode(profile)
	return sum(
		flt(row.get("opening_amount", row.get("amount", 0)))
		for row in balance_details or []
		if (row.get("mode_of_payment") or "") == cash_mode
	)


def _expected_cash(closing_shift: str, cash_mode: str) -> float:
	rows = frappe.get_all(
		"POS Closing Shift Detail",
		filters={"parent": closing_shift, "mode_of_payment": cash_mode},
		fields=["expected_amount"],
	)
	return sum(flt(row.expected_amount) for row in rows)


def _matching_rows(receipt, rows: list) -> list:
	known = set(
		frappe.get_all(
			"POS Service Receipt",
			filters={"uid": ["is", "set"]},
			pluck="uid",
		)
	)
	moment = get_datetime(receipt.attempted_at) if receipt.attempted_at else None
	found = []
	for row in rows or []:
		if not isinstance(row, dict):
			continue
		if abs(flt(row.get("amount")) - flt(receipt.amount)) > 0.009:
			continue
		if _row_type(row) != _expected_type(receipt):
			continue
		receipt_id = _list_uid(row)
		if not receipt_id or receipt_id in known:
			continue
		if moment and row.get("date"):
			try:
				if get_datetime(row.get("date")) < moment - CLOCK_SLACK:
					continue
			except Exception:
				pass
		found.append(row)
	return found


def _expected_type(receipt) -> str:
	if receipt.movement_type == "deposit":
		return "deposit"
	if receipt.movement_type == "withdrawal":
		return "withdrawal"
	return ""


def _list_uid(row: dict) -> str:
	return str(row.get("uid") or "")


def _row_type(row: dict):
	value = row.get("type")
	if not isinstance(value, str):
		return ""
	return value.strip().lower()


def _candidate(row: dict) -> dict:
	uid = _list_uid(row)
	return {
		"uid": uid,
		"receipt_id": uid,
		"number": "",
		"amount": flt(row.get("amount")),
		"date": row.get("date") or "",
	}


def _fiscal_shift_id(receipt) -> str:
	if receipt.shift_id:
		return receipt.shift_id
	calls = frappe.get_all(
		"POS Call",
		filters={
			"command": "open_shift",
			"opening_shift_reference_name": receipt.pos_opening_shift,
			"status": "Completed",
		},
		fields=["result"],
		order_by="creation desc",
		limit=1,
	)
	if calls:
		shift_id = str((as_dict(calls[0].result).get("shift") or {}).get("shift_id") or "")
		if shift_id:
			return shift_id
	latest = frappe.get_all(
		"POS Fiscal Receipt",
		filters={"pos_station": receipt.pos_station, "shift_id": ["is", "set"]},
		fields=["shift_id"],
		order_by="creation desc",
		limit=1,
	)
	return str(latest[0].shift_id) if latest else ""


def _add_cash(payments: list, cash_mode: str, amount: float) -> None:
	for pay in payments:
		if pay.mode_of_payment == cash_mode:
			pay.expected_amount = flt(pay.expected_amount) + flt(amount)
			return
	payments.append(
		frappe._dict(
			{
				"mode_of_payment": cash_mode,
				"opening_amount": 0,
				"expected_amount": flt(amount),
			}
		)
	)


def _pending(opening_shift: str):
	name = frappe.db.get_value(
		"POS Service Receipt",
		{"pos_opening_shift": opening_shift, "status": "Unreconciled"},
		"name",
	)
	return frappe.get_doc("POS Service Receipt", name) if name else None


def _pending_doc(receipt_name: str):
	receipt = frappe.get_doc("POS Service Receipt", receipt_name)
	_open_profile(receipt.pos_profile, receipt.pos_opening_shift)
	if receipt.status != "Unreconciled":
		frappe.throw(_("POS Service Receipt {0} is already closed.").format(receipt_name))
	return receipt


def _open_profile(pos_profile: str, opening_shift: str):
	opening = frappe.db.get_value(
		"POS Opening Shift",
		opening_shift,
		["pos_profile", "user", "status", "docstatus"],
		as_dict=True,
	)
	if not opening or opening.pos_profile != pos_profile or opening.docstatus != 1 or opening.status != "Open":
		frappe.throw(_("The shift is not open."))
	if opening.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only the cashier of this shift can record a cash movement."), frappe.PermissionError)
	return frappe.get_doc("POS Profile", pos_profile)


def missing_cash_accounts(profile) -> list[str]:
	"""Accounts required before a shift opens and before cash moves."""

	missing = []
	if not profile.cash_out_account:
		missing.append(_("Cash Out Account on POS Profile {0}").format(profile.name))
	cash_mode = _cash_mode(profile)
	cash_account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": cash_mode, "company": profile.company},
		"default_account",
	)
	if not cash_account:
		missing.append(
			_("Account for mode of payment {0}, company {1}").format(cash_mode, profile.company)
		)
	return missing


def require_cash_accounts(profile) -> None:
	missing = missing_cash_accounts(profile)
	if not missing:
		return
	frappe.throw(
		_("The operation cannot continue until these accounts are set: {0}").format("; ".join(missing)),
		title=_("Cash accounts"),
	)


def _require_station(profile) -> None:
	if not profile.pos_station:
		frappe.throw(_("Set the POS Station on POS Profile {0}.").format(profile.name), title=_("POS Station"))


def _movement_type(value: str) -> str:
	if value not in ("deposit", "withdrawal"):
		frappe.throw(_("Unknown cash movement."))
	return value


def _cash_in_drawer(device) -> object:
	if not isinstance(device, dict):
		return None
	for key in ("cash_in_drawer", "cashInDrawer"):
		if device.get(key) not in (None, ""):
			return device.get(key)
	return None


def _registered(receipt_name: str, cash_in_drawer=None) -> dict:
	receipt = frappe.get_doc("POS Service Receipt", receipt_name)
	data = _public(receipt)
	data["registered_at"] = str(receipt.modified)
	data["drawer_amount"] = None if cash_in_drawer in (None, "") else flt(cash_in_drawer)
	return data


def _public(receipt) -> dict:
	return {
		"name": receipt.name,
		"movement_type": receipt.movement_type,
		"reason": receipt.reason,
		"amount": flt(receipt.amount),
		"status": receipt.status,
		"receipt_number": receipt.receipt_number,
	}
