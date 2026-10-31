"""Assess temporal eligibility from captured HV logs, not human gesture accuracy."""
import argparse
import json
import math
import re
import statistics
from pathlib import Path


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    return {'n': len(values), 'median': statistics.median(values),
            'p95': values[math.ceil(len(values)*.95)-1], 'max': max(values)}


def nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def summarize(groups):
    poses = [pose for group in groups for pose in group]
    tracking = [row for row in poses if row.get('tracking_valid') is True]
    ages = [r['age_ms'] for r in tracking if nonnegative(r.get('age_ms'))]
    timestamps_ok = all(nonnegative(r.get('captured_ms')) and
                        nonnegative(r.get('age_ms')) for r in poses)
    gaps, budgets, spans = [], [], []
    if timestamps_ok:
        for group in groups:
            if group:
                spans.append(group[-1]['captured_ms']-group[0]['captured_ms'])
            for previous, current in zip(group, group[1:]):
                gap = current['captured_ms']-previous['captured_ms']
                gaps.append(gap)
                # hv_observe calls hv_tick(now) BEFORE updating lastCapture.
                # now = current capture + current age: the previous sample
                # must still cover an active calibration/action window then.
                budgets.append(gap+current['age_ms'])
    span = max(spans, default=0)
    reasons = []
    if len(tracking)<30 or span<30000:
        reasons.append('Need at least 30 tracked observations over at least 30 seconds')
    if not timestamps_ok:
        reasons.append('Missing, negative, or non-finite capture/age timestamps')
    if not ages or len(ages)!=len(tracking) or max(ages)>400:
        reasons.append('Tracked result age exceeds 400 ms or no tracked result exists')
    if not gaps or min(gaps)<=0 or max(gaps)>400:
        reasons.append('Capture interval exceeds 400 ms, is non-monotonic, or is unknown')
    if not budgets or max(budgets)>400:
        reasons.append('Previous capture to next result exceeds 400 ms (capture gap + current age), or is unknown')
    if any(r.get('tracking_valid') is not True or r.get('valid') is False for r in poses):
        reasons.append('Untracked or rejected observations interrupt the production input window')
    def values(key, source=poses):
        return [r[key] for r in source if nonnegative(r.get(key))]
    return {'samples':len(poses), 'tracked_samples':len(tracking),
        'fresh_tracked_samples':sum(nonnegative(r.get('age_ms')) and r['age_ms']<=400 for r in tracking),
        'tracked_age_ms':distribution(ages), 'capture_gap_ms':distribution(gaps),
        'previous_capture_to_result_ms':distribution(budgets),
        'longest_segment_span_ms':span,
        'inference_ms':distribution(values('infer_ms')),
        'conversion_ms':distribution(values('conversion_ms')),
        'model_ms':distribution(values('model_ms')),
        'eye_span_px':distribution(values('eye_span_px', tracking)),
        'timing_gate_passed':not reasons, 'reasons':reasons}


def assess(rows):
    groups, boundaries = [], []
    ignored_partial_lines = 0
    previous, boot, pending_boundary = None, None, None
    for index, row in enumerate(rows, 1):
        # A JSON-shaped tail without a serial newline is still unfinished.
        # Do not let the raw-line fallback turn it into timing evidence.
        if row.get('partial_line') is True:
            ignored_partial_lines += 1
            continue
        line = row.get('line', '')
        payload = row.get('device', row)
        if payload is row and line:
            for prefix in ('HV {', 'HP {'):
                start = line.find(prefix)
                if start >= 0:
                    try:
                        payload = json.loads(line[start+len(prefix)-1:])
                    except (ValueError, TypeError):
                        pass
                    break
        reason = None
        if re.search(r'ESP-ROM:|(?:^|\s)rst:0x|Guru Meditation|HV reset reason=', line):
            reason = 'Device startup, crash, or explicit input invalidation'
        current_boot = payload.get('boot', row.get('boot'))
        if current_boot is not None:
            if boot is not None and current_boot != boot:
                reason = 'Device boot identifier changed'
            boot = current_boot
        if payload.get('event') == 'pose' and previous is not None:
            if all(nonnegative(r.get(key)) for r in (previous, payload)
                   for key in ('captured_ms', 'age_ms')):
                if payload['captured_ms'] <= previous['captured_ms']:
                    reason = 'Capture timestamp restarted or is non-monotonic'
                elif payload['captured_ms']+payload['age_ms'] < previous['captured_ms']+previous['age_ms']:
                    reason = 'Result processing timestamp is non-monotonic'
        if reason and groups:
            boundaries.append({'row':index, 'reason':reason})
            pending_boundary = reason
            previous = None
        if payload.get('event') != 'pose':
            continue
        if not groups or pending_boundary:
            groups.append({'start_row':index, 'end_row':index,
                           'start_reason':pending_boundary or 'Start of observed poses', 'poses':[]})
            pending_boundary = None
        groups[-1]['poses'].append(payload)
        groups[-1]['end_row'] = index
        previous = payload
    report = summarize([group['poses'] for group in groups])
    if boundaries:
        report['reasons'].append('Log contains discontinuities; assess segments separately, never pool their duration')
        report['timing_gate_passed'] = False
    report.update(segment_count=len(groups), boundaries=boundaries,
        ignored_partial_lines=ignored_partial_lines,
        segments=[{key:value for key,value in group.items() if key!='poses'} |
                  summarize([group['poses']]) for group in groups],
        gesture_accuracy_verified=False,
        note='Observed-frame timing only; unlogged invalidations remain unknown. No cross-segment intervals or pooled duration. Requires separate neutral stability, occlusion, multiple-person and independent gesture trials; this does not verify stage 3 actions.')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    args=parser.parse_args()
    rows=[json.loads(line) for line in args.log.read_text(encoding='utf-8').splitlines() if line.strip()]
    print(json.dumps(assess(rows),ensure_ascii=False,indent=2))
