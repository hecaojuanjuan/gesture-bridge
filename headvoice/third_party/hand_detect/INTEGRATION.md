# HeadVoice integration boundary

The eight files recorded in `UPSTREAM.json` are unmodified Espressif MIT
sources and the ESP32-S3 model, pinned to commit
`c39b5bb08e957dc675efa29f86a642ba79cb82d7`. ESP32-P4 model data is intentionally
not vendored. Model size is 497,136 bytes; this is not its runtime RAM use.

The upstream component is `espressif/hand_detect` 0.1.0 and requires ESP-DL
`~3.2.0`. The local SDK currently supplies 3.2.4. When the component is copied
to `apps/main/pose/private/hand_detect`, adjust its copied
`idf_component.yml` dependency `override_path` from `../../esp-dl` to
`../esp-dl`; do not change the pinned source files.

Use `CONFIG_HAND_DETECT_MODEL_IN_FLASH_RODATA=y` and
`CONFIG_FLASH_ESPDET_PICO_224_224_HAND=y`. The HeadVoice adapter rejects a
non-rodata build. No model partition or SD card is required.

`hv_hand_detect` is detection only. It returns no palm/fist classification.
The model's proposal threshold stays at its upstream default 0.25; the
adapter accepts a crop only when exactly one returned hand has score >= 0.5,
category 0 and a nonempty box wholly within the input image. Two returned
hands invalidate the crop even if one is below 0.5.

Pixel boxes are passed through without adding one to right/bottom endpoints.
This matches the upstream recognizer, which passes `hand.box` directly into
`ImagePreprocessor::preprocess`: ESP-DL 3.2.4 computes crop width as `x2-x1`
and samples at most `x2-1`. Its detector postprocessor may already clip the
right/bottom endpoint to `width-1`/`height-1`; the adapter does not silently
change this upstream edge behavior. Crop expansion and classification belong
to the caller and must use the same RGB frame that produced the detection.

Initialization is eager and must precede camera inference. Subsequent calls
belong to one inference task; the detector owns mutable resident buffers.
The adapter rejects missing model input/output maps after construction.
This does not replace device heap measurements or hardware inference tests.
