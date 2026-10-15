import json
import frappe


def log_outbound_request(
    *,
    pos_station: str,
    pos_calls: list[str],
    request_headers: str = None,
    request_data: dict = None,
    response_data: dict = None,
):
    """
    Log outbound request sent to POS Station.
    """

    log = frappe.get_doc(
        {
            "doctype": "POS Station Log",
            "pos_station": pos_station,
            "direction": "Outbound",
            "status": "Success",
            "request_headers": request_headers,
            "request_data": json.dumps(request_data, indent=4) if request_data else None,
            "response_data": json.dumps(response_data, indent=4) if response_data else None,
        }
    )

    # Link POS Calls to the station log
    for pos_call in pos_calls or []:
        log.append(
            "pos_calls",  # child table fieldname in POS Station Log
            {
                "pos_call": pos_call,
            }
        )
    
    log.insert(ignore_permissions=True)



def log_inbound_response(
    *,
    pos_station: str,
    pos_call: str,
    request_headers: str = None,
    request_data: dict = None,
    response_data: dict = None,
    success: bool,
):
    """
    Log inbound response received from POS Station.
    """

    log = frappe.get_doc(
        {
            "doctype": "POS Station Log",
            "pos_station": pos_station,
            "direction": "Inbound",
            "status": "Success" if success else "Fail",
            "request_headers": request_headers,
            "request_data": json.dumps(request_data, indent=4) if request_data else None,
            "response_data": json.dumps(response_data, indent=4) if response_data else None,
        }
    )
    
    # Link POS Calls to the station log
    log.append(
        "pos_calls",  # child table fieldname in POS Station Log
        {
            "pos_call": pos_call,
        }
    )
    
    log.insert(ignore_permissions=True)
