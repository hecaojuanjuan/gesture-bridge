"""Offline audit of native 11-class startup/capture logs; never opens a device.

Reports telemetry integrity and observed runtime bounds, not gesture accuracy.
Output deliberately excludes raw serial lines, images and network identifiers.
"""
import argparse
import collections
import json
import math
import re
import statistics
from pathlib import Path

LABELS = ('one', 'two', 'three', 'four', 'five', 'like', 'ok',
          'no_gesture', 'call', 'dislike', 'no_hand')
TIMINGS = ('conversion_ms', 'detect_ms', 'classifier_ms', 'infer_ms', 'age_ms')
MEMORY = ('internal_free', 'internal_largest', 'psram_free')
MODEL_SHA256 = '52e18ceb0845121b4c0fa63aa06d69d17068c8c8135f43a7943a11812ac595d0'
FAULTS = {
    'panic': r'Guru Meditation|panic(?:ked)?|abort\(\)',
    'watchdog': r'watchdog|wdt timeout|WDT_SYS_RST|TG[01]WDT',
    'brownout': r'brownout',
    'assertion': r'assert failed|assertion.*failed',
    'allocation': r'Failed to alloc|out of memory|ESP_ERR_NO_MEM',
    'camera': r'Camera.*(?:failed|error)|empty frame|null frame|Failed to (?:capture|detect sensor)',
    'restarting': r'Restarting\.\.\.',
}


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def stats(values):
    values = sorted(v for v in values if numeric(v))
    if not values:
        return None
    return {'n': len(values), 'min': values[0], 'median': statistics.median(values),
            'p95': values[math.ceil(len(values) * .95) - 1], 'max': values[-1]}


def valid_scores(message):
    scores = message.get('scores')
    return (isinstance(scores, list) and len(scores) == len(LABELS) and
            all(numeric(v) and v <= 1 for v in scores) and abs(sum(scores) - 1) <= .001)


def audit(rows):
    messages, fingerprints, resets = [], [], []
    faults = collections.Counter()
    malformed = partial = rom_banners = sequence_regressions = 0
    boot = 0
    previous_seq = None
    for row in rows:
        if not isinstance(row, dict):
            malformed += 1
            continue
        if row.get('partial_line'):
            partial += 1
            continue
        line = row.get('line', '')
        if not isinstance(line, str):
            malformed += 1
            continue
        if 'ESP-ROM:' in line:
            rom_banners += 1
            boot += 1
            previous_seq = None
        match = re.search(r'ELF file SHA256:\s*([0-9a-fA-F.]+)', line)
        if match:
            fingerprints.append(match.group(1).lower())
        match = re.search(r'(?:^|\s)rst:(0x[0-9a-fA-F]+)(?:\s*\(([^)]*)\))?', line)
        if match:
            resets.append({'code': match.group(1), 'reason': match.group(2)})
        for name, pattern in FAULTS.items():
            if re.search(pattern, line, re.IGNORECASE):
                faults[name] += 1
        offset = line.find('HG {')
        if offset < 0:
            continue
        try:
            message = json.loads(line[offset + 3:])
        except ValueError:
            malformed += 1
            continue
        if not isinstance(message, dict) or message.get('v') != 1:
            malformed += 1
            continue
        if message.get('event') == 'observation':
            seq = message.get('seq')
            if type(seq) is int:
                if previous_seq is not None and seq <= previous_seq:
                    sequence_regressions += 1
                    boot += 1
                previous_seq = seq
        messages.append((boot, message))

    observations = [m for _, m in messages if m.get('event') == 'observation']
    native = [m for m in observations if m.get('classifier') == 'espdl_gesture11']
    classified = [m for m in native if m.get('classification_valid') is True]
    sound = [m for m in classified if valid_scores(m)]
    top_scores, margins = [], []
    mismatch = 0
    for message in sound:
        scores = message['scores']
        ranking = sorted(scores, reverse=True)
        top_scores.append(ranking[0])
        margins.append(ranking[0] - ranking[1])
        # Six-decimal telemetry can create a tie absent in the float result.
        label = message.get('gesture')
        if label not in LABELS or ranking[0] - scores[LABELS.index(label)] > .000001:
            mismatch += 1

    metrics = [(b, m) for b, m in messages if m.get('event') == 'metrics']
    memory = {}
    for field in MEMORY:
        values = [m[field] for _, m in metrics if numeric(m.get(field))]
        memory[field] = {'first': values[0], 'last': values[-1],
                         'min': min(values), 'max': max(values), 'n': len(values)} if values else None
    counter_deltas = {}
    for field in ('captured', 'dropped'):
        samples = [(b, m[field]) for b, m in metrics if numeric(m.get(field))]
        counter_deltas[field] = (samples[-1][1] - samples[0][1] if len(samples) >= 2 and
                                samples[-1][0] == samples[0][0] and
                                samples[-1][1] >= samples[0][1] else None)
    ready = [m for _, m in messages if m.get('event') == 'ready']
    completions = [m for _, m in messages if m.get('event') == 'gesture']
    return {
        'observations': len(observations), 'native_observations': len(native),
        'firmware_elf_sha256_values': sorted(set(fingerprints)),
        'rom_banner_lines': rom_banners, 'reset_reason_lines': resets,
        'sequence_regressions': sequence_regressions,
        'fault_pattern_line_counts': dict(faults),
        'partial_lines_ignored': partial, 'malformed_rows_or_hg_messages': malformed,
        'ready_events': [{key: m.get(key) for key in
                          ('classifier', 'classifier_ready', 'model_sha256', 'servo_control')}
                         for m in ready],
        'ready_model_sha256_matches_pin': [m.get('model_sha256') == MODEL_SHA256 for m in ready
                                           if m.get('classifier') == 'espdl_gesture11'],
        'classifier_init_statuses': [m.get('classifier_status') for _, m in messages
                                     if m.get('event') == 'classifier_init'],
        'observation_status_counts': dict(collections.Counter(str(m.get('classifier_status')) for m in native)),
        'classification_valid': len(classified),
        'valid_classification_bad_scores': len(classified) - len(sound),
        'valid_classification_label_mismatches': mismatch,
        'score_vector_lengths': dict(collections.Counter(str(len(m['scores'])) if isinstance(m.get('scores'), list)
                                                        else 'missing_or_invalid' for m in native)),
        'raw_classes_all_native': dict(collections.Counter(m.get('gesture', 'unknown') for m in native)),
        'raw_classes_valid_classification': dict(collections.Counter(m.get('gesture', 'unknown') for m in classified)),
        'confirmed_observations': sum(m.get('confirmed') is True for m in native),
        'completed_gestures': dict(collections.Counter(m.get('gesture', 'unknown') for m in completions)),
        'top_score': stats(top_scores), 'margin': stats(margins),
        'timing_all_observations_ms': {field: stats([m.get(field) for m in observations]) for field in TIMINGS},
        'timing_valid_classification_ms': {field: stats([m.get(field) for m in classified]) for field in TIMINGS},
        'memory_bytes': memory, 'metric_counter_deltas_same_boot': counter_deltas,
        'gesture_accuracy_verified': False,
        'limits': [
            'Startup markers are counted separately; two marker lines do not prove two reboots.',
            'No matching fault text is not proof of fault-free operation; the recording may start late or miss lines.',
            'Native status 1 also marks skipped inference; detector no-hand and classifier no_hand are distinct.',
            'Raw labels, valid scores and confirmed observations are not additional completed gesture events.',
            'Memory minima cover sampled metrics only, not heap low-water marks or fragmentation between samples.',
            'No classifier preprocess/model/postprocess split, PSRAM largest block or stack watermark is emitted by this firmware.',
            'Gesture correctness needs independently labelled trials; an unlabeled startup probe cannot verify accuracy.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.log.read_text(encoding='utf-8').splitlines() if line.strip()]
    result = audit(rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['native_observations'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
