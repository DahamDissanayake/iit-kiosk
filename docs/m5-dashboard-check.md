# M5 dashboard end-to-end check

Run `cd dashboard && npm run build && cd .. && uv run python -m core --dev`, then fill in the Result, Date, Tester and Device columns. A step is passed only when the tester has seen it pass. A failed step gets an `issue/IIT-<KEY>-<slug>` task, linked in the Notes column.

## Kiosk screen (http://localhost:8765/?dev=1 at 1080 x 1920)

| # | Step | Expected | Actual | Result | Date | Tester | Device | Notes |
|---|------|----------|--------|--------|------|--------|--------|-------|
| 2.1 | Tap the gear briefly | Nothing opens | | | | | | |
| 2.2 | Hold the gear for 3 s | The ring fills and the PIN pad opens at http://localhost:8080/ | | | | | | |
| 2.3 | Press "Back to kiosk" | Returns to the character page | | | | | | |
| 2.4 | Log in, then leave it untouched for 5 minutes | Back on the kiosk in Idle | | | | | | |
| 2.5 | Enter five wrong PINs | "Too many wrong tries. Try again in 5:00." | | | | | | |

## LAN laptop (http://\<ip\>:8080/)

| # | Step | Expected | Actual | Result | Date | Tester | Device | Notes |
|---|------|----------|--------|--------|------|--------|--------|-------|
| 3.1 | Log in with the PIN, then press Exit | Logs out and shows the PIN pad; does not navigate to localhost | | | | | | |
| 3.2 | Settings: cooldown 30 s, save; on the kiosk, after a visitor leaves, send a new Approach within 30 s | The Approach does nothing | | | | | | |
| 3.3 | Quiet mode on, then off | Music stops, then returns | | | | | | |
| 3.4 | Turn on "Keep unmatched questions"; ask an off-topic question | The kiosk privacy notice changes; the question appears on Unmatched questions | | | | | | |
| 3.5 | Health page | Restart and Shut down are disabled in dev | | | | | | |

## Result

All steps passed / failed steps: (fill in), with the issue tasks filed: (fill in).
