import frappe


# Command → role priority mapping
ROLE_PRIORITY_BY_COMMAND = {
    "open_shift": [
        "All-in-One",
        # "Fiscal Terminal",
    ],
    "close_shift": [
        "All-in-One",
        # "Fiscal Terminal",
    ],
    "sale": [
        "All-in-One",
        # "Fiscal Terminal",
    ],
}


def select_station_device_for_command(
    *,
    pos_station: str,
    command: str,
):
    """
    Select POS Station Device (device + app) by command role priority.
    Returns dict with device, app, role.
    Throws if no suitable device found.
    """

    station = frappe.get_doc("POS Station", pos_station)

    role_priority = ROLE_PRIORITY_BY_COMMAND.get(command)
    if not role_priority:
        frappe.throw(f"No device role priority defined for command: {command}")

    # Build candidate list
    candidates = []

    for row in station.pos_devices:
        if row.disabled:
            continue

        app = frappe.get_doc("POS Device App", row.pos_device_app)
        if app.disabled:
            continue

        device = frappe.get_doc("POS Device", row.pos_device)

        candidates.append(
            {
                "device": device,
                "app": app,
                "role": app.app_role,
            }
        )

    # Select by role priority
    for role in role_priority:
        for candidate in candidates:
            if candidate["role"] == role:
                return [candidate["device"], candidate["app"]]

    frappe.throw(
        f"No suitable POS Station Device found for command '{command}'. "
        f"Expected roles: {', '.join(role_priority)}"
    )
