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

`python tools/servo_minimal_control.py --port COM3 --status-only` only sends
read-only status queries and fails if either output is active. Omitting all
action flags explicitly stops the outputs and verifies their status.
Use `--axis pan` or `--axis tilt` instead of `--status-only` to
perform the default small 1500→1525→1500→1475→1500 microsecond test, holding
each step for 0.8 seconds. `--span-us` accepts 25 (default), 50, 100, or 200;
the previous full 1300–1700 range now requires explicit `--span-us 200`.
Every transition is split into steps of at most 50 microseconds. Optional
`--hold-seconds` accepts 0.1–1.0 seconds. Set the actual port and select the
axis by its signal GPIO, not the bracket's physical orientation.

Startup tolerates USB-open resets and retries only read-only `status` for
up to 20 seconds. No motion is sent before a valid status is confirmed.
After that, a reboot, missing acknowledgment, or mismatched axis/pulse
aborts the test and attempts `stop`. Reads are buffered until a real newline.
The successful path verifies automatic `lease_expired` with axis -1/pulse 0,
then verifies both `stop` and `status`; failed shutdown verification is
reported separately rather than assumed successful.
Human observation of the servo horn is required: command acknowledgment
is not evidence of mechanical motion. The board camera is unavailable in
this diagnostic application.

After the comparison, restore the preserved full application at 0x20000
and verify its identity and stopped status. A failed minimal test does not
by itself distinguish the driver, electrical signal, supply and servo.
