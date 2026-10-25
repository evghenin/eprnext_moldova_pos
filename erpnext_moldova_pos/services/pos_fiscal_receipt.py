"""PDF copy of a fiscal receipt. Values come from the POS Fiscal Receipt snapshot."""

import re
from datetime import datetime
from pathlib import Path

import frappe
from fpdf import FPDF
from frappe.utils import flt, now_datetime
from frappe.utils.file_manager import save_file

from erpnext_moldova_pos.services.mev_qr import _matrix


_PAYMENT_LABELS = {
	"cash": "NUMERAR",
	"bank": "CARD",
	"card": "CARD",
	"general": "CARD",
}
_WIDTH = 40
_PAGE_WIDTH_MM = 57
_MARGIN_MM = 4
_CONTENT_MM = _PAGE_WIDTH_MM - 2 * _MARGIN_MM
_QR_MM = 28
_LINE_FACTOR = 1.5
_FONT_PATH = Path(__file__).resolve().parents[1] / "public" / "fonts" / "RobotoMono-Regular.ttf"
_CENTER = "\u0001"

def attach_fiscal_receipt_pdf(receipt_name: str) -> str:
	"""Build the receipt PDF and attach it to the fiscal receipt."""

	receipt = frappe.get_doc("POS Fiscal Receipt", receipt_name)
	context = receipt_context(receipt)
	text = render_receipt_text(context)
	pdf = render_receipt_pdf(context, text)
	file_doc = save_file(context["filename"], pdf, "POS Fiscal Receipt", receipt.name, is_private=1)
	return file_doc.file_name


def attach_service_receipt_pdf(receipt_name: str) -> str:
	"""Build the service receipt PDF from the stored snapshot and attach it."""

	receipt = frappe.get_doc("POS Service Receipt", receipt_name)
	context = service_receipt_context(receipt)
	text = render_service_receipt_text(context)
	pdf = render_receipt_pdf(context, text, copy_label="Copie a bonului de serviciu")
	file_doc = save_file(context["filename"], pdf, "POS Service Receipt", receipt.name, is_private=1)
	return file_doc.file_name


def regenerate_service_receipt_pdf(receipt_name: str) -> str:
	"""Replace the attached service receipt PDF with a freshly rendered copy."""

	frappe.has_permission("POS Service Receipt", "write", doc=receipt_name, throw=True)
	delete_service_receipt_pdfs(receipt_name)
	return attach_service_receipt_pdf(receipt_name)


@frappe.whitelist()
def regenerate_fiscal_receipt_pdf(receipt_name: str) -> str:
	"""Replace the attached receipt PDF with a freshly rendered copy."""

	frappe.has_permission("POS Fiscal Receipt", "write", doc=receipt_name, throw=True)
	delete_receipt_pdfs(receipt_name)
	return attach_fiscal_receipt_pdf(receipt_name)


def delete_service_receipt_pdfs(receipt_name: str) -> None:
	names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "POS Service Receipt", "attached_to_name": receipt_name},
		fields=["name", "file_name"],
	)
	for row in names:
		file_name = row.file_name or ""
		if file_name.startswith("bon_serviciu_") and file_name.endswith(".pdf"):
			frappe.delete_doc("File", row.name, ignore_permissions=True, force=True)


def delete_receipt_pdfs(receipt_name: str) -> None:
	names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "POS Fiscal Receipt", "attached_to_name": receipt_name},
		fields=["name", "file_name"],
	)
	for row in names:
		file_name = row.file_name or ""
		if file_name.startswith("bon_fiscal_") and file_name.endswith(".pdf"):
			frappe.delete_doc("File", row.name, ignore_permissions=True, force=True)


def receipt_context(receipt) -> dict:
	printed_at = receipt.sale_at or now_datetime()
	number = str(receipt.receipt_number or "1").strip() or "1"
	day = printed_at.strftime("%Y-%m-%d")
	return {
		"company_name": receipt.company_name,
		"tax_id": receipt.tax_id,
		"registration": receipt.registration_number,
		"address_lines": [line for line in (receipt.address_display or "").split("\n") if line],
		"address_display": receipt.address_display or "",
		"items": [
			{
				"name": row.item_name,
				"qty": row.qty,
				"price": row.rate,
				"total": row.total,
				"amount": row.amount,
				"letter": row.tax_code,
				"discount_amount": row.discount_amount,
				"margin_amount": row.margin_amount,
			}
			for row in receipt.items
		],
		"groups": [
			{"letter": row.tax_code, "rate": row.tax_rate, "gross": row.gross_amount, "vat": row.vat_amount}
			for row in receipt.taxes
		],
		"payments": [
			{"label": _payment_label(row.payment_type, row.mode_of_payment), "amount": row.amount}
			for row in receipt.payments
		],
		"total": receipt.grand_total,
		"change": receipt.change,
		"number": number,
		"date": printed_at.strftime("%d.%m.%Y"),
		"time": printed_at.strftime("%H:%M:%S"),
		"serial": receipt.device_serial or "",
		"mev_id": receipt.mev_id or "",
		"verification_url": receipt.mev_verification_url or "",
		"unreconciled": receipt.status == "Unreconciled",
		"filename": receipt_filename(number, day),
	}


def service_receipt_context(receipt) -> dict:
	printed_at = receipt.attempted_at or now_datetime()
	number = str(receipt.receipt_number or "1").strip() or "1"
	day = printed_at.strftime("%Y-%m-%d")
	if receipt.movement_type == "deposit":
		amount_label = "Sume introduse"
	else:
		amount_label = "Sume scoase"
	return {
		"company_name": receipt.company_name or "",
		"tax_id": receipt.tax_id or "",
		"registration": receipt.registration_number or "",
		"address_lines": [line for line in (receipt.address_display or "").split("\n") if line],
		"title": "BON DE SERVICIU",
		"amount_label": amount_label,
		"reason_label": {"collection": "Încasare", "refund": "Retur"}.get(receipt.reason or ""),
		"amount": receipt.amount,
		"cash_in_drawer": receipt.cash_in_drawer,
		"number": number,
		"date": printed_at.strftime("%d.%m.%Y"),
		"time": printed_at.strftime("%H:%M:%S"),
		"serial": receipt.device_serial or "",
		"mev_id": receipt.mev_id or "",
		"verification_url": receipt.mev_verification_url or "",
		"filename": service_receipt_filename(number, day),
	}


def receipt_filename(number: str, posting_date: str) -> str:
	safe_number = re.sub(r"[^\w.-]+", "_", str(number).strip()) or "1"
	day = posting_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", posting_date or "") else datetime.now().strftime("%Y-%m-%d")
	return f"bon_fiscal_{safe_number}_{day}.pdf"


def service_receipt_filename(number: str, posting_date: str) -> str:
	safe_number = re.sub(r"[^\w.-]+", "_", str(number).strip()) or "1"
	day = posting_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", posting_date or "") else datetime.now().strftime("%Y-%m-%d")
	return f"bon_serviciu_{safe_number}_{day}.pdf"


def _font_point_size() -> float:
	"""Point size at which 40 Roboto Mono characters equal the printable width."""

	probe = FPDF(unit="mm", format=(_PAGE_WIDTH_MM, 40))
	probe.add_font("RobotoMono", "", str(_FONT_PATH))
	probe.add_page()
	probe.set_font("RobotoMono", size=10)
	measured = probe.get_string_width("0" * _WIDTH)
	return 10 * _CONTENT_MM / measured


def render_receipt_pdf(context: dict, text: str, copy_label: str = "Copie a bonului fiscal") -> bytes:
	lines = text.split("\n")
	font_pt = _font_point_size()
	line_mm = font_pt * 25.4 / 72 * _LINE_FACTOR
	height = _MARGIN_MM * 2 + len(lines) * line_mm
	has_qr = bool(context.get("verification_url"))
	if has_qr:
		height += 2 * line_mm + _QR_MM
	pdf = FPDF(unit="mm", format=(_PAGE_WIDTH_MM, height))
	pdf.set_auto_page_break(auto=False)
	pdf.set_margins(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM)
	pdf.c_margin = 0
	pdf.add_font("RobotoMono", "", str(_FONT_PATH))
	pdf.add_page()
	pdf.set_font("RobotoMono", size=font_pt)
	for line in lines:
		centered = line.startswith(_CENTER)
		pdf.cell(
			_CONTENT_MM,
			line_mm,
			line[1:] if centered else line,
			align="C" if centered else "L",
			new_x="LMARGIN",
			new_y="NEXT",
		)
	if has_qr:
		pdf.cell(_CONTENT_MM, line_mm, copy_label, align="C", new_x="LMARGIN", new_y="NEXT")
		pdf.cell(_CONTENT_MM, line_mm, "Verificați aici:", align="C", new_x="LMARGIN", new_y="NEXT")
		_draw_qr(pdf, context["verification_url"])
	return bytes(pdf.output())


def _draw_qr(pdf: FPDF, url: str) -> None:
	modules = _matrix(url.encode("utf-8"))
	count = len(modules)
	quiet = 4
	module_mm = _QR_MM / (count + quiet * 2)
	origin_x = _MARGIN_MM + (_CONTENT_MM - _QR_MM) / 2
	origin_y = pdf.get_y()
	pdf.set_fill_color(0)
	for y, row in enumerate(modules):
		for x, on in enumerate(row):
			if on:
				pdf.rect(
					origin_x + (x + quiet) * module_mm,
					origin_y + (y + quiet) * module_mm,
					module_mm,
					module_mm,
					style="F",
				)


def render_receipt_text(context: dict) -> str:
	lines = [
		_center(context["company_name"]),
		_center(f"Cod Fiscal:{context['tax_id']}"),
	]
	for line in context.get("address_lines") or []:
		lines.append(_center(line))
	if context["registration"]:
		lines.append(_center(f"Numărul de inregistrare: {context['registration']}"))
		lines.append("")
	for item in context["items"]:
		lines.append(_pair(item["name"], f"{_qty(item['qty'])} x {_money(item['price'])}"))
		total = _money(item["total"])
		letter = str(item.get("letter") or "").strip()
		lines.append(_pair("", f"{total} {letter}" if letter else total))
		#lines.append("")
		if flt(item.get("discount_amount")):
			lines.append(_pair("Reducere", f"-{_money(abs(flt(item['discount_amount'])))}"))
		if flt(item.get("margin_amount")):
			lines.append(_pair("Adaos", _money(item["margin_amount"])))
	lines.append(_rule())
	lines.append(_pair("TOTAL", _money(context["total"])))
	lines.append(_rule())
	for group in context["groups"]:
		lines.append(_pair(f"BRUT {group['letter']}", _money(group["gross"])))
		lines.append(_pair(f"TVA {_percent(group['rate'])}", _money(group["vat"])))
	for row in context["payments"]:
		lines.append(_pair(row["label"], _money(row["amount"])))
		if row["label"] == "NUMERAR" and flt(context.get("change")):
			lines.append(_pair("REST", _money(context["change"])))
	lines.append(_rule())
	lines.append(_pair(f"Data {context['date']}", f"Ora {context['time']}"))
	lines.append(_pair("Bon fiscal", context["number"]))
	lines.append(_pair("Numarul fabricarii", context["serial"]))
	lines.append(_center("MEV ID"))
	lines.append(_center(context["mev_id"]))
	lines.append(_rule())
	if context.get("unreconciled"):
		lines.append(_center("Neactualizat"))
	return "\n".join(lines)


def render_service_receipt_text(context: dict) -> str:
	lines = [
		_center(context["company_name"]),
		_center(f"Cod Fiscal:{context['tax_id']}"),
	]
	for line in context.get("address_lines") or []:
		lines.append(_center(line))
	if context["registration"]:
		lines.append(_center(f"Numărul de inregistrare: {context['registration']}"))
	lines.append("")
	lines.append(_center(context["title"]))
	lines.append(_rule())
	lines.append(_pair(context["amount_label"], _money(context["amount"])))
	if context.get("cash_in_drawer") not in (None, ""):
		if context.get("reason_label"):
			lines.append(context["reason_label"])
		lines.append(_pair("Numerar în sertar", _money(context["cash_in_drawer"])))
	lines.append(_rule())
	lines.append(_pair(f"Data {context['date']}", f"Ora {context['time']}"))
	lines.append(_pair("Bon de serviciu", context["number"]))
	lines.append(_pair("Numarul fabricarii", context["serial"]))
	lines.append(_center("MEV ID"))
	lines.append(_center(context["mev_id"]))
	lines.append(_rule())
	return "\n".join(lines)


def _center(value) -> str:
	text = "" if value is None else str(value).strip()
	return "\n".join(f"{_CENTER}{chunk}" for chunk in _chunks(text))


def _pair(left, right) -> str:
	left = "" if left is None else str(left)
	right = "" if right is None else str(right)
	gap = _WIDTH - len(right)
	if len(left) <= gap - 1:
		return left.ljust(gap) + right
	return f"{_wrap(left)}\n{right.rjust(_WIDTH)}"


def _chunks(value) -> list[str]:
	text = "" if value is None else str(value)
	if not text:
		return [""]
	return [text[index : index + _WIDTH] for index in range(0, len(text), _WIDTH)]


def _wrap(value) -> str:
	return "\n".join(_chunks(value))


def _rule() -> str:
	return "-" * _WIDTH


def _payment_label(payment_type, mode_of_payment) -> str:
	kind = str(payment_type or mode_of_payment or "").strip().lower()
	return _PAYMENT_LABELS.get(kind) or str(mode_of_payment or payment_type or "CARD").upper()


def _money(value) -> str:
	return f"{flt(value):,.2f}"


def _percent(rate) -> str:
	return f"{flt(rate):.2f}%"


def _qty(value) -> str:
	return f"{flt(value):.3f}"

