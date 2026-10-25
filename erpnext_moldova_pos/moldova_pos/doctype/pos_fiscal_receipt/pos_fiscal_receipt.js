frappe.ui.form.on("POS Fiscal Receipt", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		if (frm.doc.receipt_state === "Confirmed") {
			frm.add_custom_button(
				__("Regenerate Receipt PDF"),
				() => {
					frm.call("regenerate_pdf").then(() => frm.reload_doc());
				},
				__("Actions")
			);
		}
		frm.add_custom_button(
			__("Refresh from Terminal"),
			() => {
				frm.call("refresh_from_terminal").then((result) => {
					const name = result.message && result.message.pos_call;
					frappe.show_alert({
						message: name ? __("POS Call {0} queued", [name]) : __("Receipt refresh requested"),
						indicator: "green",
					});
				});
			},
			__("Actions")
		);
	},
});
