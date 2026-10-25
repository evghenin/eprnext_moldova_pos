# TODO

Fixes found before release. Tests are out of scope until release.

The first part is a concrete defect list. The second part is the architectural work those defects come from. Solve the architecture items in order; each one names the defects it absorbs.

## API and call delivery

- [ ] Load `POS Station` and `POS Call` in `verify_pos_station` / `verify_pos_call` with `ignore_permissions`, and call `frappe.set_user(station.service_user)` only after the signature check passes.
- [ ] Give the station service user the DocType permissions those guest endpoints need, or keep every station read/write path on `ignore_permissions` after a successful HMAC check.
- [x] In `get_pending_calls_for_station`, pass `doc.payload` through as a dict. Remove `json.loads` on the JSON field.
- [x] In `create_pos_call`, put `device.pos_device_type` into the payload (`device_type` is not a field on `POS Device`).
- [x] Make `mark_pos_call_sent` return the affected row count and return a call to the station only when the status change from `Pending` to `Sent` succeeded.
- [x] Reject `push_result` unless the call belongs to that station and its status is `Sent`. A repeat push of `Completed` or `Failed` is a no-op success.

## POS Call fields

- [x] Add a `result` JSON field on `POS Call` and persist the terminal payload in `complete_pos_call`.
- [x] Write the invoice link to `invoice_doctype` / `invoice_name` (the fields that exist). After `submit_invoice` succeeds, store the created Sales Invoice name on that call.
- [x] Fix `POS Call` link filters: closing shift → `POS Closing Shift`, invoice → `Sales Invoice`. Opening shift stays `POS Opening Shift` / `POS Opening Entry`.
- [ ] Point the `POS Call` dashboard link at the child table `POS Station Log Call Link.pos_call`, not a `pos_call` field on `POS Station Log`.

## Command names and compensation

- [x] Use one command key everywhere (`open_shift`, `close_shift`, `sale`). `handle_pos_call_result` looks up `open_shift`.
- [ ] On `open_shift` failure or timeout after an ERPNext opening document exists, cancel or delete that document and emit the shift-closed event.
- [ ] On `close_shift` failure or timeout, define the ERPNext rollback (do not leave a closed ERPNext shift against an open fiscal shift).
- [ ] On `sale` failure before the invoice is submitted, stop and do not call the original `submit_invoice`.
- [ ] If the fiscal sale succeeds and the ERPNext submit then fails, record the orphan fiscal receipt on the `POS Call` and add a reversal path.
- [ ] Run the same post-handler from `mark_timed_out_pos_calls` when a call becomes `Timeout`.
- [x] Send opening-shift balances (`mode_of_payment`, `amount` in currency units). `open_shift` does not name a device API.

## Fiscal sale payload

- [ ] Map each Item Tax Template rate to the device VAT code in the station adapter. The server now sends `tax_rates` as ERPNext percents and no longer hardcodes `taxCode: "A"`.
- [ ] Confirm each adapter's fixed-point or decimal scale. The server sends currency units and counts. SmartOne ×1000 / ×100 and MCR decimal lei both belong in the agent.
- [ ] Treat opening cash differently per device. SmartOne only opens the shift and does not deposit the leftover: the device keeps the drawer, and `opening_balances` is the ERPNext reconciliation. MCR has no open-shift operation and a Z-report leaves the drawer at 0. `open_shift` still reads device state, then deposits cash via `RegisterServiceReceipt`: every `opening_balances` row with mode of payment Cash, in lei, with no conversion to bani. Card and other modes are not deposited. A zero cash sum is not sent, because the device rejects it. Sale and close stay as they are; the next `open_shift` deposits the cash the cashier entered.
- [ ] Map every payment mode inside the station adapter. The server forwards each POSNext payment as `type`, `mode_of_payment`, and `amount`.

## POS Shift

- [ ] Either wire `POS Shift` into open/close (device, `shift_number`, `fiscal_id`, `shift_id`, links to the ERPNext opening/closing documents) or remove it from the module until that flow exists.
- [ ] If it stays: `closing_reference_doctype` / `closing_reference_name` must not be required while the shift is open. Rename the label `Closign Reference Type`.

## Auth and logs

- [ ] Include method, path, and body hash in the HMAC (`station:timestamp:nonce` is not enough).
- [ ] Store used nonces and reject replays inside the 60-second window.
- [ ] Change `shared_secret` from Data to Password and remove it from the list view.
- [ ] Stop writing `X-POS-Signature` and other secret headers into `POS Station Log`.

## Request lifetime

- [ ] Shorten the cashier wait. `submit_invoice` blocks a web worker for up to 300 seconds and commits on every poll.
- [ ] Commit only the new `POS Call` before waiting, so the station can see it without committing the rest of the request.
- [ ] Declare `pos_next` (and ERPNext) in `required_apps` in `hooks.py`.

## Architecture

Work these in order. Each item is done only when the target in its description is true.

### 1. Stop using the command queue as a synchronous RPC

- [ ] The cashier request no longer blocks a web worker for the life of the terminal call.

`wait_for_pos_call_result_short` polls up to 300 seconds and calls `frappe.db.commit()` every 0.5 seconds. The queue exists so a station behind NAT can pull commands. The cashier request then waits inside that queue and commits the Frappe transaction on every poll. The scheduler can mark the same call `Timeout` while the cashier is still waiting. Two processes decide the fate of one command.

Target: the HTTP handler inserts the `POS Call`, commits that document only, and returns. Waiting for the station happens outside the Frappe request transaction. One place owns completion: the station result, or the timeout job, not both at once.

Absorbs: "Request lifetime" (cashier wait, commit-only-the-call).

### 2. Give each command a saga across the fiscal terminal and ERPNext

- [ ] A fiscal success and an ERPNext document are reconciled by an explicit saga, including compensation.

The terminal is one source of truth and ERPNext is another. Today the terminal must return `Completed` before `submit_invoice` or `create_opening_shift` runs. If POSNext then fails, the fiscal receipt or shift already exists and ERPNext has no document. The post-handler only attempts a late rollback of an opening shift in status `Failed`. Sale and close-shift handlers are commented out. `Timeout` changes status and stops. A failed rollback is written to the Error Log and dropped.

Target: every command (`open_shift`, `close_shift`, `sale`) has ordered steps, allowed outcomes, and a compensation (cancel the ERPNext shift, void or reverse the fiscal receipt) that is retried until both sides match. Compensation runs for `Failed` and `Timeout`, not only for a late `Failed` on open shift.

Absorbs: "Command names and compensation".

### 3. Make POS Call status a single state machine

- [ ] Status changes go through one transition table, and the command key is one enum.

Three writers mutate `POS Call`, and the controller is empty (`class POSCall(Document): pass`):

- station delivery sets `Sent` with a raw `UPDATE`;
- `push_result` sets `Completed` or `Failed`;
- the scheduler sets `Timeout` on old `Pending` and `Sent` rows.

Transitions are not declared. A second `push_result` can complete an already completed call. Two overlapping `pull_calls` can both return the same command, because the affected row count is ignored. The command is a free string: the queue stores `open_shift`, the handler looks up `"Open Shift"`.

Target: one module owns `(status, command) -> next status`. Legal transitions are the only way to write status. A pull claims a row only when `Pending -> Sent` updates exactly one row. A push is accepted only from `Sent`. Command values are `open_shift`, `close_shift`, and `sale` everywhere.

Absorbs: claim-on-send and "reject `push_result` unless Sent" from "API and call delivery"; the single command key from "Command names and compensation".

### 4. Split the POSNext hook, the orchestrator, and the device protocol

- [ ] `submit_invoice` and the shift hooks only decide that a fiscal contour is required. Payload encoding lives in a device driver.

`submit_invoice` intercepts the POSNext API, decides whether a station is configured, builds the fiscal body (tax code, payment type, ×100 and ×1000 scale), and waits. The shift hooks do the same with less mapping. SmartOne cannot be replaced without editing the cashier API. A station with a separate fiscal device and payment terminal has roles in the catalog and a single hardcoded executor:

```python
ROLE_PRIORITY_BY_COMMAND = {
    "open_shift": ["All-in-One"],
    "close_shift": ["All-in-One"],
    "sale": ["All-in-One"],
}
```

Target: three layers. The POSNext hook decides that this profile uses the fiscal contour. The orchestrator creates the command and tracks it. A driver chosen from `POS Device App` turns the command into that terminal's payload. Adding a second protocol does not change the POSNext method signatures.

Absorbs: "Fiscal sale payload".

### 5. Make the fiscal shift the parent of its calls

- [ ] An open fiscal shift is a `POS Shift` row, and every call in that shift points at it.

`POS Shift` holds what identifies a shift on the terminal: number, `fiscal_id`, `shift_id`, device. The live path writes only `POS Opening Shift` / `POS Closing Shift` and dynamic links on `POS Call`. `POS Shift` is never created. Open shift is sent with `data=None`, so opening cash is not part of the command contract. `closing_reference_*` is required, so an open shift cannot be stored in that DocType. The label is `Closign Reference Type`.

Target: opening a shift creates `POS Shift` in `Open` and stores the fiscal identifiers returned by the terminal. Sale and close commands reference that row. Closing fills the closing ERPNext link and sets `Closed`. Closing references are optional while the shift is open.

Absorbs: "POS Shift", and "send opening-shift data" from "Command names and compensation".

### 6. Separate the station secret, the service user, and the audit log

- [ ] A station proves itself with a body-bound HMAC, then acts as its service user, without the secret or the signature landing in a business document.

The station calls guest methods and proves itself with HMAC. After the check, the code runs `frappe.set_user(service_user)`. The secret is a Data field shown in the list view. The signature covers `station:timestamp:nonce` only, not the body, and the nonce is not stored. Every DocType in the module is System Manager only. The guest request reads `POS Station` before the user switch, so a narrow service user cannot pass the current permission checks. `POS Station Log` stores the request headers, including the signature, on a normal document with no retention.

Target: the secret is a Password field and is not in the list view. The signature covers method, path, and body hash. Used nonces are rejected inside the 60-second window. Station reads for authentication use `ignore_permissions` and happen before `set_user`. The service user can read and write only the DocTypes the pull/push path needs. The log stores the exchange without `X-POS-Signature` or other secret headers.

Absorbs: "API and call delivery" (permission order and service-user rights) and "Auth and logs".

### 7. Keep the POSNext coupling to a thin method override

- [ ] Overridden POSNext methods delegate to this app and do not contain fiscal or lifecycle logic. `required_apps` declares `pos_next` and ERPNext.

`override_whitelisted_methods` replaces four `pos_next` functions. The rollback also imports `pos_next.realtime_events.emit_shift_closed_event`. The integration contract is those function signatures and their JSON shape. `required_apps` is empty, so the app installs on a site without POSNext and fails on the first call.

Target: each override is a thin adapter that calls the orchestrator. Fiscal payload and command lifecycle stay in this app (items 2–4). `hooks.py` lists `pos_next` and ERPNext in `required_apps`. A POSNext signature change breaks the adapter only, not the fiscal contour.

Absorbs: "Declare `pos_next` (and ERPNext) in `required_apps`" from "Request lifetime".
