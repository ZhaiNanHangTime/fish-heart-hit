"""Trend rendering is independent of signal/baseline/burst algorithms."""
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hr_visual import trace_series
from hr_config import DEFAULT_PARAMS, merge_params


class TraceTests(unittest.TestCase):
    def test_long_running_history_keeps_visible_detail_and_latest_endpoint(self):
        samples=[[i,75+8*math.sin(i/10)] for i in range(8*3600)]
        short=trace_series(samples[-181:],180)
        long=trace_series(samples,180)
        self.assertEqual(short,long)
        self.assertEqual(long['samples'],181)
        self.assertEqual(len(long['points']),181)
        self.assertEqual(long['points'][-1][0],1)

    def test_old_outlier_does_not_flatten_current_trend(self):
        samples=[[0,240]]+[[i,70+(i%8)] for i in range(1000,1200)]
        self.assertEqual(trace_series(samples,90),trace_series(samples[1:],90))
        ys=[p[1] for p in trace_series(samples,90)['points']]
        self.assertAlmostEqual(max(ys)-min(ys),2)

    def test_dense_window_retains_both_extrema_and_ends(self):
        samples=[[i/20,70] for i in range(3601)]
        samples[1800][1]=130;samples[2000][1]=40
        result=trace_series(samples,180)
        self.assertLessEqual(len(result['points']),602)
        self.assertEqual(result['points'][0][0],0)
        self.assertEqual(result['points'][-1][0],1)
        self.assertAlmostEqual(max(y for x,y in result['points']),1)
        self.assertAlmostEqual(min(y for x,y in result['points']),-1)

    def test_short_history_zero_origin_flatline_and_missing_readings(self):
        self.assertEqual(trace_series([],180)['points'],[])
        self.assertEqual(trace_series([[0,72]],180)['points'],[])
        points=trace_series([[0,72],[1,72],[5,72]],180)['points']
        self.assertEqual(points,[[0,0],[1/15,0],[1/3,0]])
        # Gaps retain elapsed wall-clock spacing instead of point-index spacing.
        points=trace_series([[100,70],[110,72],[175,75]],90)['points']
        self.assertAlmostEqual(points[1][0]-points[0][0],10/90)

    def test_windows_change_visible_duration_only(self):
        data=[[i,70+i%7] for i in range(1000)]
        for seconds in [30,90,180,300,600]:
            result=trace_series(data,seconds)
            self.assertEqual(result['samples'],seconds+1)
            self.assertEqual(result['seconds'],seconds)
        self.assertEqual(DEFAULT_PARAMS['traceSeconds'],180)
        for invalid in [0,601,True,float('nan')]:
            with self.assertRaises(ValueError):merge_params(DEFAULT_PARAMS,{'traceSeconds':invalid})


if __name__=='__main__':unittest.main()
