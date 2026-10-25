import json

import frappe
from frappe.utils import now_datetime, get_fullname

from erpnext_moldova_pos.services.pos_command_payload import POS_COMMANDS
from erpnext_moldova_pos.services.pos_station_device_selector import (
	select_station_device_for_command,
)


def create_pos_call(
	*,
	command: str,
	pos_station: str,
	data: dict | None,
	opening_shift_reference_doctype: str | None = None,
	opening_shift_reference_name: str | None = None,
	closing_shift_reference_doctype: str | None = None,
	closing_shift_reference_name: str | None = None,
	invoice_reference_doctype: str | None = None,
	invoice_reference_name: str | None = None,
	pos_fiscal_receipt: str | None = None,
	pos_service_receipt: str | None = None,
	sale_uid: str | None = None,
	include_uid: bool = True,
):
	"""Create a POS Call in Pending state with a protocol-neutral payload."""

	if command not in POS_COMMANDS:
		frappe.throw(f"Unsupported POS command: {command}")

	device, _app = select_station_device_for_command(pos_station=pos_station, command=command)
	payload_data = dict(data or {})

	doc = frappe.get_doc(
		{
			"doctype": "POS Call",
			"command": command,
			"pos_station": pos_station,
			"status": "Pending",
			"payload": {
				"device": {
					"serial_number": device.serial_number,
				},
				"user": get_fullname(frappe.session.user),
				"data": payload_data,
			},
			"opening_shift_reference_doctype": opening_shift_reference_doctype,
			"opening_shift_reference_name": opening_shift_reference_name,
			"closing_shift_reference_doctype": closing_shift_reference_doctype,
			"closing_shift_reference_name": closing_shift_reference_name,
			"invoice_doctype": invoice_reference_doctype,
			"invoice_name": invoice_reference_name,
			"pos_fiscal_receipt": pos_fiscal_receipt,
			"pos_service_receipt": pos_service_receipt,
			"created_date": now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)

	payload = as_dict(doc.payload)
	payload.setdefault("data", {})
	if include_uid:
		payload["data"]["uid"] = sale_uid or doc.name
	# db_set does not encode JSON fields; a dict becomes a Python literal in SQL.
	doc.db_set("payload", json.dumps(payload, default=str), update_modified=False)
	doc.payload = payload
	return doc


def mark_pos_call_sent(pos_call_name: str) -> bool:
	"""Claim a Pending call. True only when this request won the update."""

	frappe.db.sql(
		"""
		UPDATE `tabPOS Call`
		SET status = 'Sent'
		WHERE name = %s AND status = 'Pending'
		""",
		(pos_call_name,),
	)
	return _affected_rows() == 1


def complete_pos_call(
	*,
	pos_call: str,
	result: dict,
	success: bool,
) -> bool:
	"""Move Sent -> Completed or Failed. False when the row was no longer Sent."""

	new_status = "Completed" if success else "Failed"
	frappe.db.sql(
		"""
		UPDATE `tabPOS Call`
		SET status = %s,
			result = %s,
			completed_date = %s
		WHERE name = %s AND status = 'Sent'
		""",
		(new_status, json.dumps(result, default=str), now_datetime(), pos_call),
	)
	applied = _affected_rows() == 1
	if applied:
		frappe.clear_document_cache("POS Call", pos_call)
	return applied


def as_dict(value):
	"""Return a JSON field as a dict. Frappe may already have parsed it."""

	if value is None or value == "":
		return {}
	if isinstance(value, str):
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	if isinstance(value, dict):
		return value
	return {}


def _affected_rows() -> int:
	return int(frappe.db._cursor.rowcount or 0)
