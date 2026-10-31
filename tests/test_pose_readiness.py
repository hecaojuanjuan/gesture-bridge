import sys
import json
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from pose_readiness import assess

class PoseReadinessTests(unittest.TestCase):
    def sample(self,t,age=100):
        return {'device':{'event':'pose','captured_ms':t,'age_ms':age,
                         'tracking_valid':True,'valid':True,'infer_ms':age}}
    def test_sparse_slow_results_fail_even_with_valid_keypoints(self):
        report=assess([self.sample(t,2676) for t in range(1000,40000,2679)])
        self.assertFalse(report['timing_gate_passed'])
        self.assertEqual(report['fresh_tracked_samples'],0)
    def test_good_timing_is_not_claimed_as_gesture_accuracy(self):
        report=assess([self.sample(t) for t in range(1000,32000,100)])
        self.assertTrue(report['timing_gate_passed'])
        self.assertFalse(report['gesture_accuracy_verified'])
    def test_insufficient_or_non_monotonic_samples_fail(self):
        self.assertFalse(assess([])['timing_gate_passed'])
        self.assertFalse(assess([self.sample(1000)])['timing_gate_passed'])
        rows=[self.sample(t) for t in range(1000,32000,100)]
        rows[20]=self.sample(1000)
        self.assertFalse(assess(rows)['timing_gate_passed'])

    def test_fresh_results_can_still_expire_the_previous_action_window(self):
        # Every result and capture gap passes the old independent 400 ms
        # checks, but hv_tick runs 450 ms after the previous capture.
        report=assess([self.sample(t,150) for t in range(1000,34000,300)])
        self.assertEqual(report['fresh_tracked_samples'],report['samples'])
        self.assertEqual(report['capture_gap_ms']['max'],300)
        self.assertEqual(report['previous_capture_to_result_ms']['max'],450)
        self.assertFalse(report['timing_gate_passed'])

    def test_production_tick_boundary_is_inclusive_at_400_ms(self):
        rows=[self.sample(t,100) for t in range(1000,34000,300)]
        report=assess(rows)
        self.assertTrue(report['timing_gate_passed'])
        self.assertEqual(report['previous_capture_to_result_ms']['max'],400)
        rows[50]['device']['age_ms']=101
        self.assertFalse(assess(rows)['timing_gate_passed'])

    def test_restart_segments_cannot_pool_short_windows_into_a_pass(self):
        rows=[self.sample(t) for t in range(1000,21000,100)]
        rows.append({'line':'ESP-ROM:esp32s3-20210327'})
        # Even increasing timestamps are not evidence of the same boot.
        rows.extend(self.sample(t) for t in range(21000,41000,100))
        report=assess(rows)
        self.assertFalse(report['timing_gate_passed'])
        self.assertEqual(report['segment_count'],2)
        self.assertEqual(report['longest_segment_span_ms'],19900)
        self.assertTrue(all(not s['timing_gate_passed'] for s in report['segments']))
        self.assertEqual(report['capture_gap_ms']['n'],report['samples']-2)

    def test_boot_change_retains_separate_good_timing_without_claiming_whole_log_pass(self):
        rows=[{'line':'HP {"v":1,"boot":7}'}]
        rows.extend(self.sample(t) for t in range(1000,32000,100))
        rows.append({'line':'HP {"v":1,"boot":8}'})
        rows.extend(self.sample(t) for t in range(32000,63000,100))
        report=assess(rows)
        self.assertFalse(report['timing_gate_passed'])
        self.assertEqual(report['segment_count'],2)
        self.assertTrue(all(s['timing_gate_passed'] for s in report['segments']))
        self.assertIn('boot identifier',report['boundaries'][0]['reason'])

    def test_invalid_observation_or_explicit_invalidation_breaks_continuity(self):
        rows=[self.sample(t) for t in range(1000,32000,100)]
        rows[40]['device']['valid']=False
        self.assertFalse(assess(rows)['timing_gate_passed'])
        rows[40]['device']['valid']=True
        rows.append({'line':'HV reset reason=invalid_frame_or_pose epoch=2'})
        report=assess(rows)
        self.assertFalse(report['timing_gate_passed'])
        self.assertTrue(report['segments'][0]['timing_gate_passed'])

    def test_negative_age_cannot_manufacture_freshness_or_pipeline_budget(self):
        rows=[self.sample(t) for t in range(1000,32000,100)]
        rows[10]['device']['age_ms']=-1
        report=assess(rows)
        self.assertFalse(report['timing_gate_passed'])
        self.assertEqual(report['fresh_tracked_samples'],report['samples']-1)

    def test_unterminated_json_tail_cannot_complete_sample_count_or_duration(self):
        for count, gap in ((29,100),(100,300)):
            with self.subTest(confirmed_samples=count):
                rows=[self.sample(1000+i*gap) for i in range(count)]
                tail=self.sample(1000+count*gap)['device']
                rows.append({'line':'HV '+json.dumps(tail), 'partial_line':True})
                report=assess(rows)
                self.assertEqual(report['samples'],count)
                self.assertEqual(report['tracked_samples'],count)
                self.assertEqual(report['ignored_partial_lines'],1)
                self.assertFalse(report['timing_gate_passed'])
                if count==100:
                    self.assertEqual(report['longest_segment_span_ms'],29700)
                    # A real newline-complete observation would reach 30s.
                    rows[-1]={'line':'HV '+json.dumps(tail)}
                    self.assertTrue(assess(rows)['timing_gate_passed'])
