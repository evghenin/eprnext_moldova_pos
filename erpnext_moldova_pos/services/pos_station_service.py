import frappe
from frappe import _

from erpnext_moldova_pos.services.pos_call_log_service import (
	log_inbound_response,
	log_outbound_request,
)
from erpnext_moldova_pos.services.pos_call_post_handler import handle_pos_call_result
from erpnext_moldova_pos.services.pos_call_service import (
	call_message,
	complete_pos_call,
	mark_pos_call_sent,
)

TERMINAL_STATUSES = ("Completed", "Failed")


def get_pending_calls_for_station(pos_station: str, request_headers: str, request_data: dict, limit: int = 10) -> list[dict]:
	"""Return open calls for the station.

	Sent calls are redelivered until push_result, without a second claim.
	Pending calls are claimed here. A Pending row is returned only if this request marked it Sent.
	"""

	sent = frappe.get_all(
		"POS Call",
		filters={
			"pos_station": pos_station,
			"status": "Sent",
		},
		order_by="created_date asc",
		limit=limit,
		ignore_permissions=True,
	)

	result = []
	for row in sent:
		result.append(call_message(frappe.get_doc("POS Call", row.name)))

	remaining = limit - len(result)
	if remaining <= 0:
		if result:
			_log_pull(pos_station, request_headers, request_data, result)
		return result

	pending = frappe.get_all(
		"POS Call",
		filters={
			"pos_station": pos_station,
			"status": "Pending",
		},
		order_by="created_date asc",
		limit=remaining,
		ignore_permissions=True,
	)

	for row in pending:
		if not mark_pos_call_sent(row.name):
			continue

		doc = frappe.get_doc("POS Call", row.name)
		result.append(call_message(doc))

	if result:
		_log_pull(pos_station, request_headers, request_data, result)

	return result


def _log_pull(pos_station: str, request_headers: str, request_data: dict, result: list[dict]) -> None:
	log_outbound_request(
		pos_station=pos_station,
		pos_calls=[call["pos_call"] for call in result],
		request_headers=request_headers,
		request_data=request_data,
		response_data={"message": result},
	)


def receive_station_result(
	*,
	pos_station: str,
	pos_call: str,
	request_headers: str,
	request_data: dict,
	success: bool,
) -> dict:
	"""Store a station result. A repeat push for a finished call is a no-op."""

	current_status = frappe.db.get_value("POS Call", pos_call, "status")
	if current_status in TERMINAL_STATUSES:
		log_inbound_response(
			pos_station=pos_station,
			pos_call=pos_call,
			success=success,
			request_headers=request_headers,
			request_data=request_data,
		)
		return {"duplicate": True, "status": current_status}

	if current_status != "Sent":
		frappe.throw(
			_("POS Call {0} status is not Sent (current status: {1})").format(pos_call, current_status)
		)

	applied = complete_pos_call(
		pos_call=pos_call,
		result=request_data,
		success=success,
	)
	log_inbound_response(
		pos_station=pos_station,
		pos_call=pos_call,
		success=success,
		request_headers=request_headers,
		request_data=request_data,
	)
	if not applied:
		status = frappe.db.get_value("POS Call", pos_call, "status")
		return {"duplicate": True, "status": status}

	handle_pos_call_result(pos_call)
	return {"duplicate": False, "status": "Completed" if success else "Failed"}
