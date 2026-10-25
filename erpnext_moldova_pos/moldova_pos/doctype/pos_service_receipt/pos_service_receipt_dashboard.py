def get_data():
	return {
		"fieldname": "pos_service_receipt",
		"internal_links": {
			"Journal Entry": "journal_entry",
			"POS Opening Shift": "pos_opening_shift",
		},
		"transactions": [
			{
				"label": "Reference",
				"items": ["POS Call", "Journal Entry", "POS Opening Shift"],
			}
		],
	}
