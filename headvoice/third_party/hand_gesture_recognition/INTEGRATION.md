# Native hand classifier candidate

This directory pins `espressif/hand_gesture_recognition` 0.1.0 from commit
`c39b5bb08e957dc675efa29f86a642ba79cb82d7`. The eight upstream files listed in
`UPSTREAM.json` are unmodified, including the MIT license. Only the ESP32-S3
model is included. The manifest records SHA-256 and Git blob SHA-1 per file.

The model is `models/s3/mobilenetv2_0_5_128_128_gesture.espdl` (788,608 bytes):

```text
52e18ceb0845121b4c0fa63aa06d69d17068c8c8135f43a7943a11812ac595d0
```

## Build boundary

Do **not** add the upstream `CMakeLists.txt` as a component for this integration.
Its default embeds the model in application rodata, and its partition option
also registers a model flash target. Neither behavior is wanted implicitly.

Instead, compile `../../firmware/hv_hand_native_classifier.cpp` into the owning
application component and expose its header. It uses the existing ESP-DL 3.2.4
implementation directly, with these dependencies:

- `esp-dl`: `dl::Model`, `ImagePreprocessor`, `HandGestureClsPostprocessor`.
- `esp_partition`: read-only lookup, model reads and owned model-prefix mapping.
- `mbedtls`: incremental SHA-256 verification.
- `esp_timer`: separate preprocessing, model and postprocessing durations.

The adapter does not compile or link the upstream wrapper class. This also
avoids the old `ClsWrapper` lazy initialization and setter behavior in the SDK.
The official README's `"????"` constructor and `dl::recognition::result_t`
example are not the actual 0.1.0 API; the original header uses
`dl::cls::result_t` (`cat_name`, `score`).

The 788,608-byte model does not fit in the approximately 533 KB left by the
current application. Build tooling may copy/verify the asset for a separately
reviewed deployment, but must not silently embed it, change the partition
table or write a partition.

## Storage and initialization

`hv_hand_native_classifier_init(partition_label, expected_sha256)` requires an
explicit existing **data** partition label (maximum 16 characters). There is no
default label. `coco_pose` is only a potential storage choice because it is
currently a 3200 KiB data partition; this module does not authorize replacing
its content. Check ownership, back up needed content, and verify the final
deployment manifest before any separate flash operation.

The chosen partition must start with the exact raw EDL2 file above. Only its
first 788,608 bytes are hashed; padding after it is ignored. No PDL multi-model
wrapper or offset within a partition is accepted. `expected_sha256` must equal
`HV_HAND_NATIVE_MODEL_SHA256`. The adapter rejects missing/small partitions,
read errors and hash mismatches before constructing an ESP-DL model. It never
calls write or erase APIs.

Initialization also checks one input of shape `[1,128,128,3]` and one 11-value
output, both int8 with allocated storage. It reports ready only after the
preprocessor and postprocessor exist. Same-label repeated initialization is
idempotent; changing labels requires deinitialization. Stop other users before
initialization, deinitialization or model flash; the singleton is not reentrant.

After SHA verification, the adapter explicitly maps only the 788,608-byte model
prefix with `esp_partition_mmap`. Its error is returned as `no_memory` for
`ESP_ERR_NO_MEM`, otherwise `io_error`. The adjusted mapped pointer is supplied
to ESP-DL's `MODEL_LOCATION_IN_FLASH_RODATA` path; this does not embed the model
in application rodata. It bypasses ESP-DL 3.2.4's partition loader, which maps
the entire partition and aborts on mapping failure. The adapter retains the
handle, including a valid zero handle, until the postprocessor, preprocessor
and model have all been destroyed, then calls `esp_partition_munmap`.

ESP-DL has internal allocation/assert paths without recoverable public error
returns. Parameter copies, preprocessing LUTs and the first softmax LUT include
unchecked allocations. A failed model root allocation may also leave parameter
objects outside the SDK's cleanup path. The adapter checks its own allocations
and boundaries, but cannot promise recovery or complete resource reclamation
after these internal failures. Default `param_copy=true` is unchanged. Actual
internal memory, PSRAM, stack use and concurrent voice operation still require
device testing.

## Inference contract

Call `hv_hand_native_classifier_analyze_rgb888` with the original RGB888 buffer,
its exact byte length, dimensions, and the accepted `hv_hand_detection_t` from
the **same frame**. Do not run the hand detector again for classification.
The adapter rejects non-single-hand detections, invalid/low scores, malformed
boxes, buffer-size mismatches and unsupported dimensions before inference.

Direct parsing of this pinned model's actual EDL2 FlatBuffer confirmed input
`input.1`, int8 `[1,128,128,3]`, and output `466`, int8 `[1,11]`. The graph has
68 nodes and ends at `/classifier/classifier.1/Gemm`; there is no Softmax node.
The adapter's postprocessor therefore performs the required single softmax.

The official pipeline crops that box, stretches to RGB 128×128, applies mean
`[123.675,116.28,103.53]` and std `[58.395,57.12,57.375]`, quantizes through
ESP-DL and applies its softmax postprocessor. It does not use the custom
gray64 CNN's padding or preprocessing.

All 11 scores are returned in the immutable upstream order:

| Index | Raw name |
| --- | --- |
| 0 | one |
| 1 | two |
| 2 | three |
| 3 | four |
| 4 | five |
| 5 | like |
| 6 | ok |
| 7 | no_gesture |
| 8 | call |
| 9 | dislike |
| 10 | no_hand |

Each name must occur exactly once. Nonfinite/out-of-range values, wrong counts,
unknown/duplicate names or a non-unit probability sum invalidate the result.
`top_index`, `top_score`, `second_score` and `margin` are computed independently
of the postprocessor's sort order. Failures clear all scores and set
`top_index=UNKNOWN`. Ties have zero margin and remain for the caller to reject.

`valid` means an accepted input and complete probability distribution, **not** a
confirmed gesture. The current user targets are open palm (`five`) and V sign
(`two`). Keep those native names in telemetry; never alias `two` to fist or
`no_gesture`/`no_hand` to a target gesture. A classifier `no_hand` result is also
not evidence that the preceding detector returned zero hands.

The official [gesture illustration](https://github.com/espressif/esp-dl/blob/c47ac966e0bc73ba8c1100a67ebef342eb2b6227/examples/hand_gesture_recognition/gestures.png)
shows `two` as the index and middle fingers raised, palm facing the camera,
with the other fingers folded: a V/two-finger gesture, not a thumb-index L.
That illustration was added by the 2026-03-04 documentation commit
`c47ac966e0bc73ba8c1100a67ebef342eb2b6227`. Its [S3 model](https://github.com/espressif/esp-dl/blob/c47ac966e0bc73ba8c1100a67ebef342eb2b6227/models/hand_gesture_recognition/models/s3/mobilenetv2_0_5_128_128_gesture.espdl)
has Git blob `9412ea051175c406c7a05807d500f1f78d4344e6` and size 788,608 bytes,
identical to this pinned asset; this is not an assumption based on a newer
model. The label definition does not establish camera-view recognition accuracy.

The owning application must recheck capture age and epoch before and after the
synchronous inference, apply confidence and margin thresholds, enforce stable
hold/release rules, clear stale candidates, and implement any light/output
actions. This adapter sends no commands and controls no actuator.

## Verification scope

`tests/test_hand_native_classifier.py` runs eight host tests against the
production adapter: partition/hash gating, model-prefix mapping failures and
release order, explicit allocation and layout failure cleanup, invalid input
rejection, all real class identities, malformed
outputs, C-header compatibility, upstream file provenance, and actual-model
FlatBuffer input/output/terminal-operator checks. SHA and ESP-DL
device APIs are stubbed in boundary tests; these tests do not measure the
pretrained model's accuracy or device flash verification.

On 2026-10-31 the adapter also passed a syntax-only compile using the existing
ESP32-S3 compiler flags and real ESP-DL 3.2.4 / ESP-IDF headers. A final integrated
firmware link, model deployment, latency/heap measurements, and real two-gesture
acceptance remain separate work. No USB or flash operation was performed while
preparing this candidate.
