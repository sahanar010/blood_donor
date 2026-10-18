"""Run with:  python -m unittest discover -s tests -v   (from backend/)"""
import unittest
from datetime import datetime, time

from app.enums import Urgency
from app.matching import (DonorFeatures, RequestContext, Weights, effective_radius_km,
                          in_preferred_window, passes_travel_policy, rank, score_donor)

WEEKDAY_10AM = datetime(2026, 10, 7, 10, 0)    # Wednesday
SATURDAY_10AM = datetime(2026, 10, 10, 10, 0)  # Saturday


def ctx(urgency=Urgency.NORMAL, when=WEEKDAY_10AM, max_km=15.0):
    return RequestContext(max_distance_km=max_km, urgency=urgency, required_local=when)


def donor(i=1, d=2.0, radius=10.0, **kw):
    base = dict(rating_avg=4.5, response_rate=0.9, acceptance_rate=0.9, donation_count=4)
    base.update(kw)
    return DonorFeatures(donor_id=i, distance_km=d, travel_radius_km=radius, **base)


class ScoringTests(unittest.TestCase):
    def test_perfect_donor_scores_100(self):
        f = donor(d=0, rating_avg=5.0, response_rate=1.0, acceptance_rate=1.0)
        self.assertEqual(score_donor(f, ctx()).score, 100.0)

    def test_nearer_donor_ranks_higher_all_else_equal(self):
        ranked = rank([donor(1, d=8), donor(2, d=2)], ctx(), top_n=2)
        self.assertEqual([m.donor_id for m in ranked], [2, 1])

    def test_score_always_between_0_and_100(self):
        for d in (0, 5, 10, 14.9):
            s = score_donor(donor(d=d), ctx(Urgency.EMERGENCY)).score
            self.assertTrue(0 <= s <= 100)

    def test_new_donor_without_history_does_not_crash(self):
        f = DonorFeatures(donor_id=9, distance_km=3, travel_radius_km=10)
        m = score_donor(f, ctx())
        self.assertIsNotNone(m)
        self.assertGreater(m.score, 0)

    def test_ml_weight_redistributed_when_absent(self):
        f = donor(d=0, rating_avg=5.0, response_rate=1.0, acceptance_rate=1.0, ml_probability=None)
        self.assertEqual(score_donor(f, ctx()).score, 100.0)

    def test_ml_probability_moves_the_score(self):
        lo = score_donor(donor(ml_probability=0.1), ctx()).score
        hi = score_donor(donor(ml_probability=0.99), ctx()).score
        self.assertGreater(hi, lo)

    def test_reasons_are_explainable(self):
        m = score_donor(donor(d=2.4, rating_avg=4.8), ctx())
        self.assertIn("2.4 km away", m.reasons)
        self.assertIn("4.8★ experience rating", m.reasons)


class TravelPolicyTests(unittest.TestCase):
    def test_normal_respects_donor_radius(self):
        self.assertIsNone(score_donor(donor(d=12, radius=10), ctx(Urgency.NORMAL)))

    def test_urgent_allows_one_and_a_half_times(self):
        self.assertIsNotNone(score_donor(donor(d=14, radius=10), ctx(Urgency.URGENT)))
        self.assertIsNone(score_donor(donor(d=16, radius=10), ctx(Urgency.URGENT)))

    def test_emergency_ignores_radius(self):
        self.assertTrue(passes_travel_policy(40, 5, Urgency.EMERGENCY))

    def test_outside_radius_scores_lower_than_inside(self):
        inside = score_donor(donor(d=9, radius=10), ctx(Urgency.EMERGENCY)).score
        outside = score_donor(donor(d=9, radius=5), ctx(Urgency.EMERGENCY)).score
        self.assertGreater(inside, outside)

    def test_weekend_radius_used_on_saturday(self):
        self.assertEqual(effective_radius_km(10, 30, WEEKDAY_10AM), 10)
        self.assertEqual(effective_radius_km(10, 30, SATURDAY_10AM), 30)


class PreferredWindowTests(unittest.TestCase):
    def test_simple_window(self):
        self.assertTrue(in_preferred_window(time(9), time(17), time(10)))
        self.assertFalse(in_preferred_window(time(9), time(17), time(20)))

    def test_window_wrapping_midnight(self):
        self.assertTrue(in_preferred_window(time(22), time(6), time(23, 30)))
        self.assertTrue(in_preferred_window(time(22), time(6), time(2)))
        self.assertFalse(in_preferred_window(time(22), time(6), time(12)))

    def test_no_preference_means_always_ok(self):
        self.assertTrue(in_preferred_window(None, None, time(3)))

    def test_out_of_window_scores_lower(self):
        inside = score_donor(donor(preferred_start=time(9), preferred_end=time(17)), ctx()).score
        outside = score_donor(donor(preferred_start=time(18), preferred_end=time(21)), ctx()).score
        self.assertGreater(inside, outside)


class RankTests(unittest.TestCase):
    def test_top_n_and_deterministic_tiebreak(self):
        cands = [donor(i, d=3) for i in (5, 3, 4, 1, 2)]
        ranked = rank(cands, ctx(), top_n=3)
        self.assertEqual([m.donor_id for m in ranked], [1, 2, 3])

    def test_custom_weights_change_order(self):
        near_unreliable = donor(1, d=1, response_rate=0.2, acceptance_rate=0.2)
        far_reliable = donor(2, d=9, response_rate=1.0, acceptance_rate=1.0)
        default = rank([near_unreliable, far_reliable], ctx(), Weights(), 2)
        reliab = rank([near_unreliable, far_reliable], ctx(),
                      Weights(distance=0.05, reliability=0.70, availability=0.05,
                              travel=0.05, ml=0.05, rating=0.10), 2)
        self.assertEqual(default[0].donor_id, 1)
        self.assertEqual(reliab[0].donor_id, 2)


if __name__ == "__main__":
    unittest.main()
