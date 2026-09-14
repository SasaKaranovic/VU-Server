# Backlight retry-backoff + bounded read timeout

Date: 2026-07-20
Status: Approved

## Problem

When a dial stops acknowledging RGBW backlight writes (loose USB/hub cable,
power-starved dial, wedged firmware, dropped off the bus), the server logs:

```
serial_driver.py  158 ERROR   Timeout occured (...); lines received before timeout: []
serial_driver.py  243 WARNING serial_transaction: no valid response for '>130300050100640000'; received []
server_dial_handler.py 148 ERROR Failed to update backlight for dial 740069000650564139323920; will retry.
```

Root cause of the log/behaviour storm (the underlying non-response is a
hardware/serial-link condition, out of scope here):

1. `_periodic_update_dial_backlight` sees `backlight_changed=True`, calls
   `dial_driver.dial_set_backlight(...)`, which writes the command and then
   waits in `read_until_response(timeout=5)` for a line starting with `<`.
2. The dial answers nothing. After 5 s the read times out, returns `[]`,
   `_parseResponse([])` returns `False`, `dial_set_backlight` returns `False`.
3. Per PR #15, the flag is (correctly) left set so the change is retried. But
   there is **no backoff and no failure cap**, so:
   - The failing write is retried on every periodic tick, forever.
   - `periodic_dial_update` runs synchronously on the Tornado IOLoop every
     1000 ms (`server.py:688`). Each failed attempt holds the serial `Lock`
     and blocks the IOLoop for the full 5 s read timeout — the **entire REST
     API freezes for 5 s per retry**, and the logs fill with the trio above.

## Goals

- A single unresponsive dial must not freeze the API or spam the logs.
- Retries must throttle (exponential backoff) and eventually give up
  (mark the dial unresponsive) until the dial re-appears or a new value is
  requested.
- Keep the change tight and unit-testable; no concurrency-model change.

## Out of scope (deferred)

- Full executor offload of serial I/O (`IOLoop.run_in_executor`) so the loop
  is truly non-blocking. Tracked as a follow-up.
- Applying the same backoff/failure handling to the value and image loops
  (they do not currently check the driver's send result).

## Changes

### 1. Bound the read timeout for backlight writes

`serial_driver.py` and `dial_driver.py`. Thread an optional `read_timeout`
through the send path so a backlight write waits ~0.5 s (an ACK is a status
code returned immediately by the hub, not gated on the easing animation)
instead of the 5 s default. `None` preserves the existing 5 s for every other
command.

- `serial_driver.py`
  - `serial_transaction(self, payload, ignore_response=False, read_timeout=None)`
    → `rx_lines = self.read_until_response(timeout=read_timeout if read_timeout is not None else 5)`.
- `dial_driver.py`
  - Class constant `BACKLIGHT_READ_TIMEOUT = 0.5`.
  - `_sendCommand(self, cmd, dataType, dataLen=0, data=None, ignore_response=False, read_timeout=None)`
    passes `read_timeout` into `serial_transaction`.
  - `dial_set_backlight(...)` calls `_sendCommand(..., read_timeout=self.BACKLIGHT_READ_TIMEOUT)`.

### 2. Per-dial retry-backoff + unresponsive cap

`server_dial_handler.py`.

Class constants:

```
BACKLIGHT_MAX_FAILURES = 5      # consecutive fails before "unresponsive"
BACKLIGHT_BACKOFF_BASE = 1.0    # seconds
BACKLIGHT_BACKOFF_MAX  = 30.0   # cap
```

Per-dial fields, initialised in `_reload_dials` alongside the existing keys:

```
dial['backlight_fail_count'] = 0
dial['backlight_retry_after'] = 0
dial['backlight_unresponsive'] = False
```

`_periodic_update_dial_backlight`, per dial with `backlight_changed`:

- Skip if `backlight_unresponsive` (given up until it re-appears / is re-armed).
- Skip if `now < backlight_retry_after` (still cooling down).
- Call the driver. On failure:
  - `backlight_fail_count += 1`.
  - If `backlight_fail_count >= BACKLIGHT_MAX_FAILURES`: set
    `backlight_unresponsive = True` and log an error **once**.
  - Else: `backlight_retry_after = now + min(BASE * 2**(n-1), MAX)` and log the
    failure with the next-retry delay.
  - `continue` (leave `backlight_changed=True`).
- On success: reset `backlight_fail_count=0`, `backlight_retry_after=0`,
  `backlight_unresponsive=False`, clear `backlight_changed`, bump
  `update_deadline`, count as updated.

Backoff walk: fail1→1 s, fail2→2 s, fail3→4 s, fail4→8 s, fail5→unresponsive
(~15 s of throttled retries before giving up).

Reads of the new fields use `dial.get(key, default)` so a dial dict missing
them (constructed elsewhere / older path) can't raise `KeyError`.

### 3. Recovery / re-arm

Two recovery paths:

- **Rescan** — `_reload_dials(rescan=True)` rebuilds the dict fresh (already
  sets `backlight_changed=True`), so the new fields start clean and the dial is
  retried once it re-appears on the bus.
- **New API request** — in the `dial_set_backlight` *queue* method, when a
  colour is (re)queued, reset the three retry fields so a previously
  unresponsive dial gets a fresh attempt. Additionally, tighten the
  "already at value" short-circuit so it only returns early when the value is
  *actually delivered* — i.e. `backlight == new_value and not backlight_changed
  and not backlight_unresponsive`. Otherwise re-POSTing the same colour that is
  currently stuck/failing would be silently dropped.

## Testing (TDD)

Extends the `tests/test_bugfixes.py` pattern: `object.__new__(ServerDialHandler)`
wired to a stub driver, `monkeypatch` on `server_dial_handler.time` for a fake
clock.

1. Failure sets a backoff; a second poll *within* the cooldown does not call the
   driver again.
2. After the cooldown elapses, the next poll retries (driver called again).
3. After `BACKLIGHT_MAX_FAILURES` consecutive fails, `backlight_unresponsive`
   is `True` and the driver stops being called on subsequent polls.
4. A successful send resets `fail_count` / `retry_after` / `unresponsive` and
   clears `backlight_changed`.
5. Re-queueing a colour via `dial_set_backlight` clears `unresponsive` and
   re-arms (driver called again on next poll).
6. `dial_set_backlight` does **not** short-circuit a same-value request while a
   change is still pending or the dial is unresponsive.

Existing tests #8 (`test_backlight_flag_stays_set_when_send_fails`,
`test_backlight_flag_clears_when_send_succeeds`) must still pass: with the fake
clock at its default, `backlight_retry_after=0` never blocks the first attempt.
