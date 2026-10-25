import frappe
from frappe import _

from erpnext_moldova_pos.services.pos_call_service import as_dict


def raise_for_pos_call(pos_call_name: str, status: str | None, action: str):
	"""Tell the cashier why the station did not complete the command."""

	result = as_dict(frappe.db.get_value("POS Call", pos_call_name, "result"))
	frappe.throw(
		failure_message(action, status, result),
		title=_("POS Station"),
	)


def failure_message(action: str, status: str | None, result) -> str:
	detail = station_error_detail(result)
	if status == "Failed":
		text = _("The POS station rejected {0}.").format(action)
	elif not status:
		text = _("The POS station did not answer in time for {0}.").format(action)
	else:
		text = _("The POS station did not finish {0}. Status: {1}.").format(action, status)
	if detail:
		if detail.lower().startswith(text.lower()):
			return detail
		return f"{text} {detail}"
	return text


def station_error_detail(result) -> str:
	error = as_dict(result).get("error")
	if not isinstance(error, dict):
		error = {}

	tax_detail = _tax_rate_detail(error)
	if tax_detail:
		return tax_detail

	raw = str(error.get("message") or "").strip()
	message = _message_for_code(error.get("code")) or (_cashier(raw) if raw else "")
	extras = []

	error_code = error.get("code")
	if error_code and not _message_for_code(error_code) and str(error_code) not in message:
		extras.append(str(error_code))

	item_code = error.get("item_code")
	if item_code:
		extras.append(_cashier("item {0}").format(item_code))

	tax_rate = error.get("tax_rate")
	if tax_rate not in (None, ""):
		extras.append(_cashier("tax rate {0}").format(tax_rate))

	if message and extras:
		return f"{message} ({', '.join(extras)})"
	if extras:
		return ", ".join(extras)
	return message


# English text is the contract `error.message`. `_()` picks the cashier language.
STATION_ERROR_MESSAGES = {
	"DEVICE_OFFLINE": "The target device is offline.",
	"UNSUPPORTED_COMMAND": "The command is not supported by this POS station.",
	"INVALID_PAYLOAD": "The payload provided is invalid.",
	"AUTHENTICATION_FAILED": "Authentication with ERPNext server failed.",
	"INVALID_AMOUNT": "The amount must be greater than zero.",
	"INVALID_REASON": "The withdrawal reason must be collection.",
	"MISSING_UID": "A receipt uid is required.",
	"MISSING_SHIFT_ID": "A shift id is required.",
	"RETURN_NOT_SUPPORTED": "This device cannot register a return.",
	"CARD_CHARGED_NOT_REGISTERED": "The card was charged and the fiscal receipt was not registered.",
	"SALE_NOT_CONFIRMED": "The device did not confirm the sale.",
	"SERVICE_RECEIPT_NOT_CONFIRMED": "The device did not confirm the cash operation.",
	"REPORT_NOT_CONFIRMED": "The device did not confirm the report.",
	"RECEIPT_NOT_FOUND": "The receipt was not found.",
	"SHIFTS_UNAVAILABLE": "The device did not return shifts.",
	"RECEIPTS_UNAVAILABLE": "The device did not return the shift receipts.",
	"UNKNOWN_DEVICE_ERROR": "The device returned an unknown error.",
	"SERVICE_INTERNAL_ERROR": "The fiscal service reported an unknown internal error.",
	"SERVICE_DATABASE_UNAVAILABLE": "The fiscal service database is unavailable.",
	"SERVICE_DATABASE_CORRUPTED": "The fiscal service database is corrupted.",
	"SERVICE_SIGNATURE_INVALID": "The fiscal service signature is invalid.",
	"SERVICE_NOT_CONFIGURED": "The fiscal service is not configured.",
	"SERVICE_ACTIVATION_CANCELLED": "The fiscal service registration in MEV has been cancelled.",
	"SERVICE_CLOCK_INVALID": "The clock on the fiscal service computer is set incorrectly.",
	"CLOUD_SYNC_ERROR": "The fiscal service could not synchronize transactions with ISFiscalCloud or MEV.",
	"DAILY_REPORT_REQUIRED": "A daily report with shift close (Z) must be printed.",
	"DAILY_REPORT_PRINTING": "A daily report with shift close is printing.",
	"CLOUD_CONNECTION_ERROR": "The fiscal service cannot reach ISFiscalCloud, and offline work is not allowed.",
	"CLOUD_TIMEOUT": "ISFiscalCloud did not answer in time, and offline work is not allowed.",
	"PAYMENT_RECEIPT_RANGE_EXHAUSTED": "The link with MEV is beyond the offline limit, and the payment receipt number range is missing or exhausted.",
	"SMS_NOT_CONFIGURED": "The receipt has a phone number, but SMS sending is not configured.",
	"EMAIL_NOT_CONFIGURED": "The receipt has an e-mail address, but e-mail sending is not configured.",
	"DEVICE_BUSY": "The device is registering another receipt or report. Retry in a few seconds.",
	"RECEIPT_HAS_NO_LINES": "The receipt has no items.",
	"RECEIPT_HAS_NO_PAYMENTS": "The receipt has no payments.",
	"INVALID_PRODUCT_NAME": "The product name is missing or invalid.",
	"INVALID_QUANTITY": "The quantity is invalid.",
	"INVALID_PRICE": "The price is invalid.",
	"UNKNOWN_UNIT": "The unit of measure is unknown or not allowed.",
	"UNKNOWN_VAT": "The VAT rate is unknown.",
	"UNKNOWN_PAYMENT": "The payment code is unknown.",
	"UNKNOWN_DEPARTMENT": "The department is unknown.",
	"PHONE_REQUIRED": "A phone number is required when the receipt is sent by SMS.",
	"EMAIL_REQUIRED": "An e-mail address is required when the receipt is sent by e-mail.",
	"INSUFFICIENT_CASH": "There is not enough cash in the drawer.",
	"PAYMENTS_BELOW_TOTAL": "The payments total is less than the receipt total.",
	"CHANGE_CANNOT_BE_CALCULATED": "The change cannot be calculated. Change is given from the cash payment only.",
	"TRANSACTION_NOT_FOUND": "The transaction was not found on the device.",
	"TRANSACTION_ALREADY_FINISHED": "The transaction is already finished.",
	"ILLEGAL_COMMAND": "The command is not allowed in the current device state.",
	"DUPLICATE_RECEIPT": "A receipt with this identifier is already registered.",
	"PRINTER_NOT_FOUND": "The printer was not found.",
	"PRINTER_UNAVAILABLE": "The printer is unavailable.",
	"PRINTER_OFFLINE": "The printer is offline.",
	"PRINTER_QUEUE_BUSY": "The printer queue has unfinished jobs.",
	"PRINTER_OUT_OF_PAPER": "The printer is out of paper.",
	"FISCAL_MEMORY_NOT_CONNECTED": "The fiscal memory is not connected.",
	"FISCAL_MEMORY_NOT_FISCALIZED": "The fiscal memory is not fiscalized.",
	"FISCAL_MEMORY_ID_UNREADABLE": "The fiscal memory identifier could not be read.",
	"FISCAL_MEMORY_WRONG_ID": "The fiscal memory identifier is wrong.",
	"FISCAL_MEMORY_REPORT_NOT_WRITTEN": "The report was not written to the fiscal memory.",
}


def _cashier(text: str) -> str:
	"""Translate for the POS language, which can differ from the Desk language."""

	lang = None
	user = getattr(frappe.session, "user", None)
	if user and user != "Guest":
		lang = frappe.db.get_value("User", user, "pos_language")
	if lang:
		return _(text, lang=lang)
	return _(text)


def _message_for_code(code) -> str:
	text = STATION_ERROR_MESSAGES.get(str(code or "").strip())
	if not text:
		return ""
	return _cashier(text)


def _tax_rate_detail(error: dict) -> str:
	"""Explain a VAT-list rejection from the normalized station error."""

	tva = error.get("device_vat")
	if not isinstance(tva, list) or not tva:
		return ""

	item_code = error.get("item_code") or "—"
	tax_rate = error.get("tax_rate")
	device_rates = _device_rates(tva)
	rate_label = _format_rate(tax_rate) if tax_rate not in (None, "") else ""
	match = _matching_vat_code(tva, tax_rate) if tax_rate not in (None, "") else None
	on_device = _rate_on_device(tva, tax_rate) if tax_rate not in (None, "") else False

	if match:
		return _cashier(
			"Item {0} is taxed at {1}. The device already has that rate as VAT code {2}. The station did not map the rate to the code."
		).format(item_code, rate_label, match)
	if on_device:
		return _cashier(
			"Item {0} is taxed at {1}. The device has that rate, but the VAT code letter could not be read."
		).format(item_code, rate_label)
	if rate_label:
		return _cashier(
			"Item {0} is taxed at {1}, and that rate is not on the device. Device rates: {2}."
		).format(item_code, rate_label, device_rates)
	return _cashier("Item {0} has no tax rate. Device rates: {1}.").format(item_code, device_rates)


def _device_rates(tva: list) -> str:
	parts = []
	for row in tva:
		if not isinstance(row, dict):
			continue
		code = row.get("code")
		value = row.get("rate")
		if code is None or value in (None, ""):
			continue
		parts.append(f"{code} {_format_rate(value)}")
	return ", ".join(parts)


def _rate_on_device(tva: list, tax_rate) -> bool:
	wanted = _as_float(tax_rate)
	if wanted is None:
		return False
	for row in tva:
		if isinstance(row, dict) and _as_float(row.get("rate")) == wanted:
			return True
	return False


def _matching_vat_code(tva: list, tax_rate) -> str | None:
	wanted = _as_float(tax_rate)
	if wanted is None:
		return None
	for row in tva:
		if not isinstance(row, dict):
			continue
		if _as_float(row.get("rate")) == wanted and row.get("code"):
			return str(row.get("code"))
	return None


def _format_rate(value) -> str:
	number = _as_float(value)
	if number is None:
		return str(value)
	if number == int(number):
		return f"{int(number)}%"
	return f"{number}%"


def _as_float(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return None
