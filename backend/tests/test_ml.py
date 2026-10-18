"""Run: python -m unittest discover -s tests -v   (needs numpy + scikit-learn; xgboost NOT required)"""
import math
import tempfile
import unittest
from datetime import datetime, time

import numpy as np
from sklearn.metrics import roc_auc_score

from app.enums import Urgency
from app.matching import DonorFeatures, RequestContext, passes_travel_policy
from app.ml.features import FEATURES, MONOTONE, feature_matrix, feature_row
from app.ml.scorer import load_model
from app.ml.simulate import simulate

CTX = RequestContext(max_distance_km=15, urgency=Urgency.EMERGENCY, required_local=datetime(2026, 10, 10, 23, 0))  # Saturday 23:00


class FeatureTests(unittest.TestCase):
    def test_row_matches_feature_list(self):
        f = DonorFeatures(donor_id=1, distance_km=3, travel_radius_km=10, preferred_start=time(9), preferred_end=time(17),
                          rating_avg=4.5, response_rate=.9, acceptance_rate=.8, donation_count=3,
                          avg_response_seconds=120, days_since_last_donation=200)
        row = dict(zip(FEATURES, feature_row(f, CTX)))
        self.assertEqual(len(feature_row(f, CTX)), len(FEATURES))
        self.assertEqual(row["urgency"], 2.0)
        self.assertEqual(row["is_weekend"], 1.0)
        self.assertEqual(row["hour"], 23.0)
        self.assertEqual(row["in_preferred_window"], 0.0)       # 23:00 is outside 9-17
        self.assertAlmostEqual(row["distance_over_radius"], 0.3)

    def test_missing_values_become_nan(self):
        f = DonorFeatures(donor_id=1, distance_km=3, travel_radius_km=10)  # brand-new donor
        row = dict(zip(FEATURES, feature_row(f, CTX)))
        for k in ("rating_avg", "response_rate", "avg_response_seconds", "days_since_last_donation"):
            self.assertTrue(math.isnan(row[k]), k)

    def test_monotone_features_exist(self):
        self.assertTrue(set(MONOTONE) <= set(FEATURES))

    def test_matrix_shape(self):
        fs = [DonorFeatures(donor_id=i, distance_km=i, travel_radius_km=10) for i in range(4)]
        self.assertEqual(feature_matrix(fs, CTX).shape, (4, len(FEATURES)))
        self.assertEqual(feature_matrix([], CTX).shape, (0, len(FEATURES)))


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = simulate(300, seed=3, pool_size=600)

    def test_shapes_and_labels(self):
        n = len(self.ds.y)
        self.assertEqual(self.ds.X.shape, (n, len(FEATURES)))
        self.assertTrue(set(np.unique(self.ds.y)) <= {0, 1})
        self.assertTrue(((self.ds.true_p > 0) & (self.ds.true_p < 1)).all())

    def test_acceptance_rate_is_plausible(self):
        self.assertTrue(0.3 < self.ds.y.mean() < 0.7, self.ds.y.mean())

    def test_every_candidate_passes_the_travel_policy(self):
        for fl, ctx in zip(self.ds.feats, self.ds.ctxs):
            for f in fl:
                self.assertTrue(passes_travel_policy(f.distance_km, f.travel_radius_km, ctx.urgency))

    def test_no_donor_repeats_within_a_request(self):
        for fl in self.ds.feats:
            ids = [f.donor_id for f in fl]
            self.assertEqual(len(ids), len(set(ids)))

    def test_deterministic_for_a_seed(self):
        again = simulate(300, seed=3, pool_size=600)
        np.testing.assert_array_equal(self.ds.y, again.y)

    def test_signal_exists_and_labels_are_noisy(self):
        auc = roc_auc_score(self.ds.y, self.ds.true_p)
        self.assertTrue(0.65 < auc < 0.95, auc)   # learnable but not trivially perfect

    def test_distance_hurts_acceptance(self):
        d = self.ds.X[:, FEATURES.index("distance_km")]
        self.assertLess(np.corrcoef(d, self.ds.true_p)[0, 1], 0)


class ScorerFallbackTests(unittest.TestCase):
    def test_missing_model_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(load_model(f"{d}/nope.json"))

    def test_corrupt_model_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            open(f"{d}/acceptance_xgb.json", "w").write("not a model")
            self.assertIsNone(load_model(f"{d}/acceptance_xgb.json"))


if __name__ == "__main__":
    unittest.main()
