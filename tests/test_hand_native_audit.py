import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from hand_native_audit import MODEL_SHA256, audit


def hg(event, **fields):
    return {'line': 'HG ' + json.dumps({'v': 1, 'event': event, **fields})}


def classified(seq=1, **fields):
    payload = dict(classifier='espdl_gesture11', seq=seq, classification_valid=True,
                   classifier_status=0, gesture='two', scores=[.02, .8] + [.02] * 9,
                   confirmed=True, conversion_ms=2, detect_ms=280, classifier_ms=160,
                   infer_ms=442, age_ms=460)
    payload.update(fields)
    return hg('observation', **payload)


class NativeAuditTests(unittest.TestCase):
    def test_raw_held_scores_are_separate_from_completed_gestures(self):
        result = audit([hg('ready', classifier='espdl_gesture11', classifier_ready=True,
                           model_sha256=MODEL_SHA256, servo_control=False),
                        classified(), classified(2), hg('gesture', gesture='v_sign')])
        self.assertEqual(result['ready_model_sha256_matches_pin'], [True])
        self.assertEqual(result['confirmed_observations'], 2)
        self.assertEqual(result['completed_gestures'], {'v_sign': 1})
        self.assertEqual(result['raw_classes_valid_classification'], {'two': 2})
        self.assertEqual(result['valid_classification_bad_scores'], 0)
        self.assertAlmostEqual(result['margin']['median'], .78)
        self.assertFalse(result['gesture_accuracy_verified'])

    def test_zero_skipped_scores_are_not_reported_as_broken_classifier_output(self):
        skipped = classified(classification_valid=False, classifier_status=1,
                             scores=[0] * 11, classifier_ms=0, confirmed=False, gesture='no_hand')
        result = audit([skipped, classified(2, scores=[0] * 11),
                        classified(3, gesture='five')])
        self.assertEqual(result['classification_valid'], 2)
        self.assertEqual(result['valid_classification_bad_scores'], 1)
        self.assertEqual(result['valid_classification_label_mismatches'], 1)
        self.assertEqual(result['timing_valid_classification_ms']['classifier_ms']['min'], 160)
        self.assertEqual(result['timing_all_observations_ms']['classifier_ms']['min'], 0)

    def test_reset_markers_and_counter_reset_do_not_create_negative_deltas(self):
        rows = [{'line': 'ESP-ROM:esp32s3'}, {'line': 'rst:0x1 (POWERON),boot:0x8'},
                {'line': 'ELF file SHA256: d14fa905...'},
                hg('metrics', internal_free=1000, internal_largest=800, psram_free=2000,
                   captured=100, dropped=80), classified(10), classified(1),
                hg('metrics', internal_free=900, internal_largest=700, psram_free=1800,
                   captured=20, dropped=10), {'line': 'Guru Meditation Error: core panic'}]
        result = audit(rows)
        self.assertEqual(result['rom_banner_lines'], 1)
        self.assertEqual(len(result['reset_reason_lines']), 1)
        self.assertEqual(result['sequence_regressions'], 1)
        self.assertEqual(result['firmware_elf_sha256_values'], ['d14fa905...'])
        self.assertIsNone(result['metric_counter_deltas_same_boot']['captured'])
        self.assertEqual(result['memory_bytes']['internal_largest']['min'], 700)
        self.assertEqual(result['fault_pattern_line_counts']['panic'], 1)

    def test_partial_lines_and_unrelated_sensitive_output_are_not_copied(self):
        result = audit([classified() | {'partial_line': True}, {'line': 'HG {oops'},
                        {'line': 'wifi password=this-must-not-appear'}])
        self.assertEqual(result['native_observations'], 0)
        self.assertEqual(result['partial_lines_ignored'], 1)
        self.assertEqual(result['malformed_rows_or_hg_messages'], 1)
        self.assertNotIn('this-must-not-appear', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
