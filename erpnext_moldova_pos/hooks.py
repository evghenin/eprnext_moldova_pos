app_name = "erpnext_moldova_pos"
app_title = "ERPNext Moldova POS"
app_publisher = "Evgheni Nemerenco"
app_description = "Moldovan POS terminals integration (like SmartOne)"
app_email = "evgheni.nemerenco@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "erpnext_moldova_pos",
# 		"logo": "/assets/erpnext_moldova_pos/logo.png",
# 		"title": "ERPNext Moldova POS",
# 		"route": "/erpnext_moldova_pos",
# 		"has_permission": "erpnext_moldova_pos.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of web template
# web_include_css = "/assets/erpnext_moldova_pos/css/erpnext_moldova_pos.css"
# web_include_js = "/assets/erpnext_moldova_pos/js/erpnext_moldova_pos.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "erpnext_moldova_pos/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"POS Closing Shift": "public/js/pos_closing_shift.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "erpnext_moldova_pos/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "erpnext_moldova_pos.utils.jinja_methods",
# 	"filters": "erpnext_moldova_pos.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "erpnext_moldova_pos.install.before_install"
# after_install = "erpnext_moldova_pos.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "erpnext_moldova_pos.uninstall.before_uninstall"
# after_uninstall = "erpnext_moldova_pos.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "erpnext_moldova_pos.utils.before_app_install"
# after_app_install = "erpnext_moldova_pos.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "erpnext_moldova_pos.utils.before_app_uninstall"
# after_app_uninstall = "erpnext_moldova_pos.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "erpnext_moldova_pos.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"erpnext_moldova_pos.tasks.all"
# 	],
# 	"daily": [
# 		"erpnext_moldova_pos.tasks.daily"
# 	],
# 	"hourly": [
# 		"erpnext_moldova_pos.tasks.hourly"
# 	],
# 	"weekly": [
# 		"erpnext_moldova_pos.tasks.weekly"
# 	],
# 	"monthly": [
# 		"erpnext_moldova_pos.tasks.monthly"
# 	],
# }

scheduler_events = {
    "cron": {
        "*/2 * * * *": [
            "erpnext_moldova_pos.services.pos_call_timeout_watcher.mark_timed_out_pos_calls",
            "erpnext_moldova_pos.services.pos_fiscal_receipt_service.enqueue_reconcile",
        ]
    }
}

# Testing
# -------

# before_tests = "erpnext_moldova_pos.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "erpnext_moldova_pos.event.get_events"
# }
#

override_whitelisted_methods = {
    "pos_next.api.pos_profile.get_pos_profiles":
        "erpnext_moldova_pos.overrides.pos_next.get_pos_profiles.get_pos_profiles",
    "pos_next.api.shifts.create_opening_shift": 
        "erpnext_moldova_pos.overrides.pos_next.create_opening_shift.create_opening_shift",
    "pos_next.api.shifts.submit_closing_shift": 
        "erpnext_moldova_pos.overrides.pos_next.submit_closing_shift.submit_closing_shift",
    "pos_next.api.invoices.update_invoice":
        "erpnext_moldova_pos.overrides.pos_next.update_invoice.update_invoice",
    "pos_next.api.invoices.submit_invoice":
        "erpnext_moldova_pos.overrides.pos_next.submit_invoice.submit_invoice",
}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
override_doctype_dashboards = {
	"Sales Invoice": "erpnext_moldova_pos.overrides.sales_invoice_dashboard.get_dashboard_data",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["erpnext_moldova_pos.utils.before_request"]
# after_request = ["erpnext_moldova_pos.utils.after_request"]

# Job Events
# ----------
# before_job = ["erpnext_moldova_pos.utils.before_job"]
# after_job = ["erpnext_moldova_pos.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"erpnext_moldova_pos.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [
			["module", "in", ["Moldova POS"]]
		]
	},
]