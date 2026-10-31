import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from hand_readiness import summarize


class HandSummaryTests(unittest.TestCase):
    def test_detection_is_not_accuracy_and_partial_is_ignored(self):
        payload = {'v': 1, 'event': 'observation', 'hands': 1, 'valid': True,
                   'classifier_ready': False, 'gesture': 'untrained', 'infer_ms': 280, 'age_ms': 320}
        row = {'line': 'HG ' + json.dumps(payload)}
        summary = summarize([row, row | {'partial_line': True}, {'line': 'HV {"event":"pose"}'}])
        self.assertEqual(summary['observations'], 1)
        self.assertEqual(summary['recording_status'], 'observations_received')
        self.assertEqual(summary['valid_single_hand'], 1)
        self.assertEqual(summary['classifier_ready_values'], [False])
        self.assertEqual(summary['gesture_events'], 0)
        self.assertFalse(summary['gesture_accuracy_verified'])

    def test_only_completion_events_are_counted(self):
        def row(event, gesture):
            return {'line': 'HG ' + json.dumps({'v': 1, 'event': event, 'gesture': gesture})}
        summary = summarize([row('observation', 'open_palm'), row('observation', 'open_palm'),
                             row('gesture', 'open_palm'), row('gesture', 'closed_fist')])
        self.assertEqual(summary['gesture_events'], 2)
        self.assertEqual(summary['gestures'], {'open_palm': 1, 'closed_fist': 1})

    def test_native_raw_candidates_and_held_frames_are_not_extra_events(self):
        def row(event, **fields):
            return {'line': 'HG ' + json.dumps({'v': 1, 'event': event, **fields})}
        observation = row('observation', classifier='espdl_gesture11',
                          classifier_ready=True, gesture='two',
                          classification_valid=True, confirmed=True)
        summary = summarize([observation, observation,
                             row('gesture', classifier='espdl_gesture11', gesture='v_sign')])
        self.assertEqual(summary['classifier_names'], ['espdl_gesture11'])
        self.assertEqual(summary['classification_valid'], 2)
        self.assertEqual(summary['confirmed_observations'], 2)
        self.assertEqual(summary['raw_classes'], {'two': 2})
        self.assertEqual(summary['gestures'], {'v_sign': 1})
        self.assertEqual(summary['gesture_events'], 1)
        self.assertFalse(summary['gesture_accuracy_verified'])

    def test_absent_observations_are_not_a_no_hand_detection(self):
        for rows in ([], [{'line': 'ESP-ROM:esp32s3-20210327'}],
                     [{'line': 'HG {"v":1,"event":"ready"}'}],
                     [{'line': 'HG {"v":1,"event":"observation","hands":0}', 'partial_line': True}]):
            with self.subTest(rows=rows):
                summary = summarize(rows)
                self.assertEqual(summary['recording_status'], 'no_observations')
                self.assertEqual(summary['observations'], 0)
                self.assertIn('cannot evaluate', summary['note'])
        summary = summarize([{'line': 'HG {"v":1,"event":"observation","hands":0,"valid":false}'}])
        self.assertEqual(summary['recording_status'], 'observations_received')
        self.assertEqual(summary['hand_counts'], {'0': 1})

    def test_cli_status_distinguishes_missing_stream_and_no_hand_observation(self):
        script = Path(__file__).resolve().parents[1] / 'tools' / 'hand_readiness.py'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recording.jsonl'
            for rows, expected_status in (([], 'no_observations'),
                                         ([{'line': 'HG {"v":1,"event":"observation","hands":0}'}], 'observations_received')):
                with self.subTest(expected_status=expected_status):
                    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                    result = subprocess.run([sys.executable, str(script), str(path)], text=True,
                                            capture_output=True)
                    self.assertEqual(json.loads(result.stdout)['recording_status'], expected_status)
                    self.assertEqual(result.returncode == 0, expected_status == 'observations_received')
                    self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
