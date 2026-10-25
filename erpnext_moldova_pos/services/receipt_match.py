"""Pick one device receipt from a shift list using the fields ERPNext already has."""

from datetime import datetime

from frappe.utils import flt, get_datetime, now_datetime


PLACEHOLDER_MEV = "TESTARE"
SALE_TYPE = "sale"


def match_device_receipts(
	rows: list,
	*,
	amount,
	attempted_at=None,
	known_ids: set | None = None,
	mev_id: str | None = None,
) -> dict | None:
	"""Return one receipt row, or None when the list does not identify a single sale."""

	known = {str(value) for value in (known_ids or set()) if value}
	candidates = [_row(row) for row in rows or [] if _amount_matches(row, amount)]
	candidates = [row for row in candidates if _receipt_type(row) == SALE_TYPE]

	if mev_id and str(mev_id).strip().upper() != PLACEHOLDER_MEV:
		tagged = [row for row in candidates if str(row.get("mev_id") or "") == str(mev_id)]
		if tagged:
			candidates = tagged

	candidates = [row for row in candidates if _list_uid(row) not in known]
	if len(candidates) == 1:
		return candidates[0]
	if len(candidates) < 2 or not attempted_at:
		return None

	moment = get_datetime(attempted_at)
	ranked = sorted(candidates, key=lambda row: _distance(row, moment))
	if _distance(ranked[0], moment) < _distance(ranked[1], moment):
		return ranked[0]
	return None


def _amount_matches(row: dict, amount) -> bool:
	value = row.get("amount")
	if value is None:
		return False
	return abs(flt(value) - flt(amount)) <= 0.009


def _receipt_type(row: dict):
	"""Station receipt kind: sale, deposit, or withdrawal. Device numbers stay on the agent."""

	value = row.get("type")
	if not isinstance(value, str):
		return None
	return value.strip().lower() or None


def _distance(row: dict, moment: datetime) -> float:
	raw = row.get("date")
	if not raw:
		return 10**12
	try:
		return abs((get_datetime(raw) - moment).total_seconds())
	except Exception:
		return 10**12


def match_shift(shifts: list, sale_at) -> dict | None:
	"""Return the one shift that contains the sale time."""

	if not sale_at:
		return None
	moment = get_datetime(sale_at)
	hits = []
	for row in shifts or []:
		row = _row(row)
		if not row.get("shift_id") or not row.get("opened_at"):
			continue
		try:
			opened = get_datetime(row.get("opened_at"))
		except Exception:
			continue
		if moment < opened:
			continue
		closed_at = row.get("closed_at")
		if closed_at:
			try:
				closed = get_datetime(closed_at)
			except Exception:
				continue
		else:
			closed = get_datetime(now_datetime())
		if moment > closed:
			continue
		hits.append(row)
	if len(hits) == 1:
		return hits[0]
	return None


def receipt_contents_match(device: dict, receipt) -> bool:
	"""The device receipt is the ERP receipt only when amount, lines, and payments agree."""

	if device.get("amount") is None or abs(flt(device.get("amount")) - flt(receipt.grand_total)) > 0.009:
		return False
	if not _same_lines(_device_items(device.get("items")), _erp_items(receipt)):
		return False
	return _same_lines(_device_payments(device.get("payments")), _erp_payments(receipt))


def _device_items(rows) -> list:
	return [
		(
			str(row.get("code") or ""),
			flt(row.get("qty")),
			flt(row.get("price")),
			flt(row.get("amount")),
		)
		for row in rows or []
		if isinstance(row, dict)
	]


def _erp_items(receipt) -> list:
	return [
		(str(row.item_code or ""), flt(row.qty), flt(row.rate), flt(row.amount))
		for row in receipt.items
	]


def _device_payments(rows) -> list:
	return [
		(str(row.get("type") or ""), flt(row.get("amount")))
		for row in rows or []
		if isinstance(row, dict)
	]


def _erp_payments(receipt) -> list:
	return [(str(row.payment_type or ""), flt(row.amount)) for row in receipt.payments]


def _same_lines(left: list, right: list) -> bool:
	return sorted(left) == sorted(right)


def _list_uid(row: dict) -> str:
	"""Identifier of a list_shift_receipts row. The station names it uid."""

	return str(row.get("uid") or "")


def _row(row):
	return row if isinstance(row, dict) else {}
