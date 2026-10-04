import math
import unittest

from ai.evaluation.baselines import expected_random_hits, hypergeometric_match_distribution, random_number_probability
from ai.evaluation.metrics import brier_score, evaluate_ticket_predictions, lift, log_loss
from ai.evaluation.probability import capped_simplex_projection, scores_to_probabilities


class EvaluationPipelineTests(unittest.TestCase):
    def test_hypergeometric_baseline_distribution(self):
        distribution = hypergeometric_match_distribution(35, 5, 5)

        self.assertAlmostEqual(1.0, sum(distribution.values()), places=12)
        self.assertAlmostEqual(5 / 35, random_number_probability(35, 5))
        self.assertAlmostEqual(25 / 35, expected_random_hits(35, 5, 5))
        self.assertAlmostEqual(math.comb(5, 0) * math.comb(30, 5) / math.comb(35, 5), distribution[0])

    def test_brier_score(self):
        probabilities = [{1: 0.8, 2: 0.2, 3: 0.2, 4: 0.8}]
        labels = [[1, 4]]

        self.assertAlmostEqual(0.04, brier_score(probabilities, labels, 4))

    def test_log_loss_clips_probabilities(self):
        probabilities = [{1: 1.0, 2: 0.0}]
        labels = [[1]]

        self.assertLess(log_loss(probabilities, labels, 2), 1e-4)

    def test_lift(self):
        self.assertAlmostEqual(0.4, lift(1.0, 35, 5, 5))

    def test_capped_simplex_projection_bounds_and_sum(self):
        projected = capped_simplex_projection([-10.0, 0.2, 0.3, 8.0], 2.0)

        self.assertAlmostEqual(2.0, sum(projected), places=10)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in projected))

    def test_scores_to_probabilities_sum_to_draw_size(self):
        probabilities = scores_to_probabilities({1: 10.0, 2: 8.0, 3: 1.0}, 2, 1, 5)

        self.assertAlmostEqual(2.0, sum(probabilities.values()), places=10)
        self.assertEqual(set(range(1, 6)), set(probabilities))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities.values()))

    def test_random_like_data_does_not_claim_fake_advantage(self):
        predictions = [
            [1, 2, 3, 4, 5],
            [6, 7, 8, 9, 10],
            [11, 12, 13, 14, 15],
            [16, 17, 18, 19, 20],
            [21, 22, 23, 24, 25],
            [26, 27, 28, 29, 30],
            [31, 32, 33, 34, 35],
        ]
        actuals = [
            [6, 7, 8, 9, 10],
            [11, 12, 13, 14, 15],
            [16, 17, 18, 19, 20],
            [21, 22, 23, 24, 25],
            [26, 27, 28, 29, 30],
            [31, 32, 33, 34, 35],
            [1, 2, 3, 4, 5],
        ]

        metrics = evaluate_ticket_predictions(predictions, actuals, 35, 5, 5)
        self.assertLessEqual(metrics["lift"], 0.0)


if __name__ == "__main__":
    unittest.main()
