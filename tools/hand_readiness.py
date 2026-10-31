"""Summarize on-board HG logs without treating detections as gesture accuracy."""
import argparse
import collections
import json
import math
import re
import statistics
from pathlib import Path

from collect_hand_samples import hand_message


def distribution(values):
    values = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v) and v >= 0)
    return ({'n': len(values), 'median': statistics.median(values),
             'p95': values[math.ceil(len(values) * .95) - 1], 'max': max(values)} if values else None)


def summarize(rows):
    messages, starts = [], 0
    for row in rows:
        if row.get('partial_line'):
            continue
        line = row.get('line', '')
        if re.search(r'ESP-ROM:|(?:^|\s)rst:0x|Guru Meditation', line):
            starts += 1
        message = hand_message(line)
        if message:
            messages.append(message)
    observations = [m for m in messages if m.get('event') == 'observation']
    gestures = [m for m in messages if m.get('event') == 'gesture']
    flags = sorted({m.get('classifier_ready') for m in messages if type(m.get('classifier_ready')) is bool})
    return {
        'recording_status': 'observations_received' if observations else 'no_observations',
        'observations': len(observations),
        'hand_counts': dict(collections.Counter(str(m.get('hands')) for m in observations)),
        'valid_single_hand': sum(m.get('hands') == 1 and m.get('valid') is True for m in observations),
        'classifier_ready_values': flags,
        'classifier_names': sorted({m['classifier'] for m in messages if isinstance(m.get('classifier'), str)}),
        'classification_valid': sum(m.get('classification_valid') is True for m in observations),
        'confirmed_observations': sum(m.get('confirmed') is True for m in observations),
        'gesture_events': len(gestures),
        'gestures': dict(collections.Counter(m.get('gesture', 'unknown') for m in gestures)),
        'raw_classes': dict(collections.Counter(m.get('gesture', 'unknown') for m in observations)),
        'inference_ms': distribution([m.get('infer_ms') for m in observations]),
        'result_age_ms': distribution([m.get('age_ms') for m in observations]),
        'startup_or_fault_lines': starts,
        'ready_events': sum(m.get('event') == 'ready' for m in messages),
        'latest_metrics': next((m for m in reversed(messages) if m.get('event') == 'metrics'), None),
        'gesture_accuracy_verified': False,
        'note': ('Counts and timing only; validate the configured target gestures, other gestures and no-hand trials against independent labels. Raw classes and held/confirmed observations are not completed gesture events. '
                 + ('The classifier is not ready.' if flags == [False] else
                    'Classifier readiness alone does not verify gesture accuracy.')
                 if observations else
                 'No HG observations received. This recording cannot evaluate hand detection or gestures; zero counts do not mean no hands were present.')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.log.read_text(encoding='utf-8').splitlines() if line.strip()]
    summary = summarize(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['observations'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
