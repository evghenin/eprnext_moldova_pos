import frappe


@frappe.whitelist()
def get_pos_profiles(*args, **kwargs):
    """
    Override for pos_next.api.pos_profile.get_pos_profiles.
    Filters POS Profiles by pos_app == 'POSNext'.
    """

    # Remove frappe RPC internal argument
    kwargs.pop("cmd", None)

    # Import original method
    from pos_next.api.pos_profile import get_pos_profiles as original_get_pos_profiles

    # Call original method (expected to return list[dict])
    profiles = original_get_pos_profiles(*args, **kwargs)

    # Get allowed POS Profile names
    allowed_profiles = set(
        frappe.get_all(
            "POS Profile",
            filters={
                "disabled": 0,
                "pos_app": "POSNext",
            },
            pluck="name"
        )
    )

    # Filter original result
    return [
        profile
        for profile in profiles
        if profile.get("name") in allowed_profiles
    ]
