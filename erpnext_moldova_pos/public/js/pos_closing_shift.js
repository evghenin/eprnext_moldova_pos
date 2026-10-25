frappe.ui.form.on("POS Closing Shift", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frm.doc.pos_profile) {
			return;
		}
		frappe.db.get_value("POS Profile", frm.doc.pos_profile, "allow_pos_print", (row) => {
			if (!cint(row && row.allow_pos_print)) {
				frm.remove_custom_button(__("Print EOD Report"), __("Print"));
			}
		});
	},
});
