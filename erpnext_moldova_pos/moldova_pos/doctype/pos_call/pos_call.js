frappe.ui.form.on("POS Call", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		show_pretty_json(frm, "payload");
		show_pretty_json(frm, "result");
		if (!["Pending", "Sent"].includes(frm.doc.status)) {
			return;
		}
		frm.add_custom_button(__("Mark Failed"), () => {
			frm.call("mark_failed").then(() => frm.reload_doc());
		});
	},
});

function show_pretty_json(frm, fieldname) {
	const field = frm.get_field(fieldname);
	if (!field || field._pretty_json) {
		return;
	}
	field._pretty_json = true;
	const original = field.set_disp_area.bind(field);
	field.set_disp_area = function (value) {
		original(value);
		const text = pretty_json(this.value || value);
		if (!this.disp_area || !text) {
			return;
		}
		this.disp_area.style.whiteSpace = "pre-wrap";
		this.disp_area.style.fontFamily = "monospace";
		this.disp_area.textContent = text;
	};
	field.set_disp_area(field.value);
}

function pretty_json(value) {
	if (value == null || value === "") {
		return "";
	}
	let parsed = value;
	if (typeof value === "string") {
		try {
			parsed = JSON.parse(value);
		} catch (error) {
			return value;
		}
	}
	return JSON.stringify(parsed, null, 2);
}
