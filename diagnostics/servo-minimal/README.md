# Isolated servo diagnostic

This temporary diagnostic uses GPIO17 (pan) and GPIO18 (tilt), the same
50 Hz, 14-bit LEDC timer/channel settings as the full gimbal application.
It starts neither camera, Wi-Fi, cloud, audio nor recognition services.
Only one axis can be active. Boot, invalid commands and a 2.5-second command
lease expiration turn both outputs off. Commands are `status`, `stop`,
`pan 1500`, and `tilt 1500`. Subsequent commands may change the pulse by at
most 50 microseconds within 1300–1700 microseconds.

Build with the repository's `tools.build.environment()` and ESP-IDF, using
an external build and sdkconfig directory under `.work/servo-minimal`.
The partition CSV matches the existing board. Flash **only the app at
0x20000**; do not replace the bootloader, partition table, NVS or models.
Before flashing, preserve and hash the currently running application.

`python tools/servo_minimal_control.py --port COM3` verifies the diagnostic
command interface with outputs off. Add `--axis pan` or `--axis tilt` to
perform one bounded 1500→1700→1300→1500 microsecond sweep, followed by an
automatic lease-expiration check and explicit stop. Set the actual port.
Human observation of the servo horn is required: command acknowledgment
is not evidence of mechanical motion. The board camera is unavailable in
this diagnostic application.

After the comparison, restore the preserved full application at 0x20000
and verify its identity and stopped status. A failed minimal test does not
by itself distinguish the driver, electrical signal, supply and servo.
