// Copyright (c) 2026, Evgheni Nemerenco and contributors
// For license information, please see license.txt

frappe.ui.form.on('POS Device', {
    setup(frm) {
        frm.set_query('device_app', function () {
            if (!frm.doc.device_type) {
                return {};
            }

            return {
                filters: {
                    device_type: frm.doc.device_type,
                    disabled: 0
                }
            };
        });
    },

    device_type(frm) {
        frm.set_value('device_app', null);
    }
});

