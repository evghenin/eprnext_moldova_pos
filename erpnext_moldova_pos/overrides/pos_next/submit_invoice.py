import json
import uuid

import frappe
from frappe import _
from frappe.utils import flt
from erpnext_moldova_pos.services.pos_call_service import create_pos_call
from erpnext_moldova_pos.services.pos_call_failure import raise_for_pos_call
from erpnext_moldova_pos.services.pos_command_payload import build_sale_data
from erpnext_moldova_pos.services.pos_fiscal_receipt_service import (
    begin_attempt,
    finish_invoice,
    link_failure_response,
    mark_rejected,
    prepare_sale_receipt,
)
from erpnext_moldova_pos.services.pos_call_waiter import (
    wait_for_pos_call_result_short,
)
from pos_next.api.invoices import submit_invoice as original_method
from erpnext_moldova_pos.services.order_payments import restore as restore_order_payments


SHORT_WAIT_SECONDS = 300


def _item_tax_template_name(profile, invoice: dict, item: dict) -> str | None:
    """Item tax template for the POS Profile tax category. Customer and line values are ignored."""

    from erpnext.stock.get_item_details import get_item_tax_template

    if not profile.tax_category:
        frappe.throw(
            _("POS Profile {0} has no Tax Category.").format(profile.name),
            title=_("Tax Configuration Error"),
        )

    return get_item_tax_template(
        {
            "item_code": item.get("item_code"),
            "company": profile.company,
            "tax_category": profile.tax_category,
            "posting_date": invoice.get("posting_date")
            or invoice.get("transaction_date")
            or invoice.get("delivery_date"),
            "base_net_rate": item.get("base_net_rate") or item.get("net_rate") or item.get("rate"),
        }
    )


@frappe.whitelist()
def submit_invoice(*args, **kwargs):
    """
    Override for POSNext submit_invoice.
    """
    kwargs.pop("cmd", None)

    # 1. Determine POS Profile
    if kwargs.get("invoice"):
        invoice = json.loads(kwargs.get("invoice"))
    else:
        frappe.throw(_("Offline invoices are not acceptable for POS processing"))

    pos_profile = invoice.get("pos_profile")

    if not pos_profile:
        return original_method(*args, **kwargs)

    profile = frappe.get_doc("POS Profile", pos_profile)

    # 2. Check if POS Station is configured
    if not profile.pos_station:
        # No POS integration — fallback to default behavior
        return original_method(*args, **kwargs)

    items = invoice.get("items") or []
    for item in items:
        template_name = _item_tax_template_name(profile, invoice, item)
        if template_name:
            item["item_tax_template"] = template_name
            continue
        if not profile.taxes_and_charges:
            frappe.throw(
                _("POS Profile {0} has no Sales Taxes and Charges Template.").format(profile.name),
                title=_("Tax Configuration Error"),
            )
        charges = frappe.get_doc("Sales Taxes and Charges Template", profile.taxes_and_charges)
        item["item_tax_template"] = None
        item["item_tax_rate"] = {charges.title: tax.rate for tax in charges.taxes}

    restore_order_payments(invoice)
    _require_full_tender(invoice, kwargs.get("data"))

    receipt, action = prepare_sale_receipt(profile, invoice)
    sale_doctype = invoice.get("doctype") or "Sales Invoice"
    if action == "submit_only":
        return _submit_original(args, kwargs, receipt, unreconciled=True, doctype=sale_doctype)

    pos_call = create_pos_call(
        command="sale",
        pos_station=profile.pos_station,
        data=build_sale_data(invoice),
        invoice_reference_doctype=sale_doctype,
        invoice_reference_name=None,
        pos_fiscal_receipt=receipt.name,
        sale_uid=_receipt_uid(receipt),
    )
    receipt.db_set("pos_call", pos_call.name, update_modified=False)
    serial = (pos_call.payload.get("device") or {}).get("serial_number")
    if serial and not receipt.device_serial:
        receipt.db_set("device_serial", serial, update_modified=False)
    begin_attempt(receipt)

    try:
        status = wait_for_pos_call_result_short(
            pos_call.name,
            timeout=SHORT_WAIT_SECONDS,
        )

        if status == "Failed":
            mark_rejected(receipt.name)
            raise_for_pos_call(pos_call.name, status, _("the sale"))

        if status != "Completed":
            return link_failure_response(receipt)

        return _submit_original(
            args, kwargs, receipt, unreconciled=False, pos_call_name=pos_call.name, doctype=sale_doctype
        )
    except frappe.ValidationError:
        raise
    except Exception:
        # The terminal may already have printed. A 500 leaves the cashier with no recovery.
        frappe.db.rollback()
        frappe.log_error(title="POS sale interrupted", message=frappe.get_traceback())
        return link_failure_response(receipt)


def _receipt_uid(receipt) -> str:
    """Fiscal Service stores Uid only when it is a GUID. The document name is not."""

    uid = (receipt.uid or "").strip()
    if uid:
        return uid
    uid = str(uuid.uuid4())
    receipt.db_set("uid", uid, update_modified=False)
    return uid


def _submit_original(
    args, kwargs, receipt, *, unreconciled: bool, pos_call_name: str | None = None, doctype: str = "Sales Invoice"
):
    submit_invoice_data = original_method(*args, **kwargs)
    invoice_name = (submit_invoice_data or {}).get("name")
    if invoice_name:
        if pos_call_name:
            frappe.db.set_value("POS Call", pos_call_name, "invoice_name", invoice_name, update_modified=False)
        finish_invoice(receipt.name, invoice_name, unreconciled=unreconciled, doctype=doctype)
    return submit_invoice_data


def _require_full_tender(invoice: dict, data) -> None:
    """A fiscal sale is all or nothing. A failed card part must not leave a partly paid invoice."""

    if isinstance(data, str):
        data = json.loads(data) if data else {}
    data = data or {}
    if data.get("is_credit_sale"):
        return

    total = flt(invoice.get("grand_total") or invoice.get("rounded_total") or invoice.get("base_grand_total"))
    paid = sum(flt(payment.get("amount")) for payment in (invoice.get("payments") or []))
    write_off = flt(data.get("write_off_amount") or invoice.get("write_off_amount"))
    if paid + write_off + 0.009 < total:
        frappe.throw(
            _(
                "The sale is not fully paid ({0} of {1}). The receipt is not printed until every payment method succeeds."
            ).format(flt(paid, 2), flt(total, 2)),
            title=_("POS Station"),
        )
