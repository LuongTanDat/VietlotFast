import math
import unittest

from ai import prediction_ledger as ledger
from ai.prizes import (
    PRIZE_SCOPE, RULE_VERSION, classify_ticket, classify_tickets,
    prize_counts, prize_statistics,
)


class PrizeClassificationTests(unittest.TestCase):
    def ticket(self, hits, size=5, special=2):
        return {"main": list(range(1, hits + 1)) + list(range(20, 20 + size - hits)),
                "special": special}

    def test_lotto_every_main_hit_and_special_combination_returns_highest_tier(self):
        actual = {"main": [1, 2, 3, 4, 5], "special": 2}
        expected = {
            (5, True): "LOTTO_JACKPOT", (5, False): "FIRST",
            (4, True): "SECOND", (4, False): "THIRD",
            (3, True): "FOURTH", (3, False): "FIFTH",
            (2, True): "CONSOLATION", (2, False): "NONE",
            (1, True): "CONSOLATION", (1, False): "NONE",
            (0, True): "CONSOLATION", (0, False): "NONE",
        }
        for (hits, matched), code in expected.items():
            with self.subTest(hits=hits, special_matched=matched):
                result = classify_ticket("LOTO_5_35", self.ticket(hits, special=2 if matched else 3), actual)
                self.assertEqual(result["prizeCode"], code)
                self.assertEqual(result["mainHits"], hits)
                self.assertIs(result["specialMatched"], matched)
                self.assertEqual(result["status"], "lost" if code == "NONE" else "won")
                self.assertEqual(result["ruleVersion"], RULE_VERSION)

    def test_mega_all_tiers(self):
        actual = {"main": [1, 2, 3, 4, 5, 6]}
        expected = {6: "MEGA_JACKPOT", 5: "FIRST", 4: "SECOND", 3: "THIRD"}
        for hits in range(7):
            with self.subTest(hits=hits):
                result = classify_ticket("LOTO_6_45", self.ticket(hits, 6, None), actual)
                self.assertEqual(result["prizeCode"], expected.get(hits, "NONE"))
                self.assertIsNone(result["specialMatched"])

    def test_power_all_tiers_and_both_five_main_outcomes(self):
        actual = {"main": [1, 2, 3, 4, 5, 6], "special": 20}
        for hits in range(7):
            with self.subTest(hits=hits):
                result = classify_ticket("LOTO_6_55", self.ticket(hits, 6, 55), actual)
                expected = {6: "POWER_JACKPOT_1", 5: "POWER_JACKPOT_2", 4: "SECOND", 3: "THIRD"}
                self.assertEqual(result["prizeCode"], expected.get(hits, "NONE"))
        result = classify_ticket("LOTO_6_55", {"main": [1, 2, 3, 4, 5, 21], "special": 20}, actual)
        self.assertEqual(result["prizeCode"], "FIRST")
        self.assertFalse(result["specialMatched"])

    def test_power_auxiliary_forecast_cannot_create_or_remove_jackpot_two(self):
        actual = {"main": [1, 2, 3, 4, 5, 6], "special": 20}
        for auxiliary in (None, 20, 55, "invalid", True):
            with self.subTest(auxiliary=auxiliary):
                hit = classify_ticket("LOTO_6_55", {"main": [1, 2, 3, 4, 5, 20], "special": auxiliary}, actual)
                miss = classify_ticket("LOTO_6_55", {"main": [1, 2, 3, 4, 5, 21], "special": auxiliary}, actual)
                self.assertEqual(hit["prizeCode"], "POWER_JACKPOT_2")
                self.assertEqual(miss["prizeCode"], "FIRST")

    def test_power_special_does_not_increase_main_hits(self):
        result = classify_ticket("LOTO_6_55", {"main": [1, 2, 3, 20, 21, 22]},
                                 {"main": [1, 2, 3, 4, 5, 6], "special": 20})
        self.assertEqual(result["mainHits"], 3)
        self.assertEqual(result["prizeCode"], "THIRD")

    def test_missing_lotto_special_is_unknown_for_every_tier(self):
        for hits in range(6):
            with self.subTest(hits=hits):
                result = classify_ticket("LOTO_5_35", self.ticket(hits), {"main": [1, 2, 3, 4, 5]})
                self.assertEqual(result["prizeCode"], "UNKNOWN")
                self.assertEqual(result["mainHits"], hits)
                self.assertIsNone(result["isWinning"])

    def test_missing_power_special_is_unknown_only_when_it_changes_tier(self):
        actual = {"main": [1, 2, 3, 4, 5, 6]}
        for hits in range(7):
            with self.subTest(hits=hits):
                expected = {6: "POWER_JACKPOT_1", 5: "UNKNOWN", 4: "SECOND", 3: "THIRD"}
                result = classify_ticket("LOTO_6_55", self.ticket(hits, 6, None), actual)
                self.assertEqual(result["prizeCode"], expected.get(hits, "NONE"))
                self.assertIsNone(result["specialMatched"])

    def test_pending_and_unknown_actual_are_distinct_from_zero_hits(self):
        ticket = self.ticket(5, 6, None)
        self.assertEqual(classify_ticket("LOTO_6_45", ticket, None)["status"], "pending")
        for actual in ({}, {"main": []}, [], {"main": [1, 2, 3, 4, 5]},
                       {"main": [1, 1, 2, 3, 4, 5]}, {"main": [1, 2, 3, 4, 5, 46]},
                       {"main": [True, 2, 3, 4, 5, 6]}, {"main": ["1", 2, 3, 4, 5, 6]}):
            with self.subTest(actual=actual):
                result = classify_ticket("LOTO_6_45", ticket, actual)
                self.assertEqual(result["status"], "unknown")
                self.assertIsNone(result["isWinning"])
        loss = classify_ticket("LOTO_6_45", {"main": [20, 21, 22, 23, 24, 25]},
                               {"main": [1, 2, 3, 4, 5, 6]})
        self.assertEqual(loss["mainHits"], 0)
        self.assertEqual(loss["status"], "lost")
        self.assertFalse(loss["isWinning"])

    def test_invalid_ticket_shape_domain_and_special_never_receive_a_prize(self):
        for main in (None, "12345", [1, 2, 3, 4], [1, 1, 2, 3, 4],
                     [0, 2, 3, 4, 5], [1, 2, 3, 4, 36], [True, 2, 3, 4, 5],
                     [1.0, 2, 3, 4, 5], ["1", 2, 3, 4, 5]):
            with self.subTest(main=main):
                self.assertEqual(classify_ticket("LOTO_5_35", {"main": main, "special": 2}, None)["status"], "invalid")
        for special in (None, 0, 13, True, 2.0, "2"):
            with self.subTest(special=special):
                self.assertEqual(classify_ticket("LOTO_5_35", self.ticket(5, special=special), None)["status"], "invalid")
        self.assertEqual(classify_ticket("LOTO_6_45", self.ticket(6, 6, 1), None)["status"], "invalid")

    def test_invalid_actual_special_remains_unknown_even_if_main_matches(self):
        for game, size, values in (("LOTO_5_35", 5, (0, 13, True, "2", 2.0)),
                                  ("LOTO_6_55", 6, (0, 56, 1, True, "20", 20.0)),
                                  ("LOTO_6_45", 6, (0, 7))):
            for special in values:
                with self.subTest(game=game, special=special):
                    result = classify_ticket(game, {"main": list(range(1, size + 1)), "special": 2 if size == 5 else None},
                                             {"main": list(range(1, size + 1)), "special": special})
                    self.assertEqual(result["status"], "unknown")

    def test_unsupported_game_and_bao_ticket_do_not_claim_standard_prizes(self):
        for game, ticket in (("MAX_3D_PRO", {"main": [1, 2, 3]}),
                             ("MAX_3D", {"main": [123]}),
                             ("LOTO_6_45", {"main": [1, 2, 3, 4, 5, 6, 7]})):
            with self.subTest(game=game):
                result = classify_ticket(game, ticket, None)
                self.assertEqual(result["status"], "unsupported")
                self.assertIsNone(result["isWinning"])

    def test_alias_actual_main_and_plain_mega_ticket_are_supported(self):
        result = classify_ticket(" loto_6_45 ", (1, 2, 3, 4, 5, 6), {"main_numbers": [1, 2, 3, 4, 5, 6]})
        self.assertEqual(result["prizeCode"], "MEGA_JACKPOT")

    def test_statistics_exclude_unclassified_tickets_from_win_rate(self):
        results = [classify_ticket("LOTO_6_45", self.ticket(3, 6, None), {"main": [1, 2, 3, 4, 5, 6]}),
                   classify_ticket("LOTO_6_45", self.ticket(0, 6, None), {"main": [1, 2, 3, 4, 5, 6]}),
                   classify_ticket("LOTO_6_45", self.ticket(3, 6, None), None),
                   classify_ticket("LOTO_6_45", self.ticket(3, 6, None), {}),
                   classify_ticket("LOTO_6_45", {"main": [1]}, None),
                   classify_ticket("MAX_3D", {"main": [1]}, None)]
        statistics = prize_statistics(results)
        self.assertEqual(statistics["ticketCount"], 6)
        self.assertEqual(statistics["classifiedTicketCount"], 2)
        self.assertEqual(statistics["winningTicketCount"], 1)
        self.assertEqual(statistics["winningTicketRate"], .5)
        self.assertEqual(statistics["pendingTicketCount"], 1)
        self.assertEqual(statistics["unknownTicketCount"], 1)
        self.assertEqual(statistics["invalidTicketCount"], 2)
        self.assertEqual(statistics["scope"], PRIZE_SCOPE)
        self.assertIsNone(prize_statistics([])["winningTicketRate"])
        self.assertEqual(sum(prize_counts(results).values()), 6)

    def test_ticket_results_keep_stable_one_based_indices(self):
        results = classify_tickets("LOTO_6_45", (self.ticket(n, 6, None) for n in (6, 0, 3)),
                                   {"main": [1, 2, 3, 4, 5, 6]})
        self.assertEqual([result["ticketIndex"] for result in results], [1, 2, 3])
        self.assertEqual([result["prizeCode"] for result in results], ["MEGA_JACKPOT", "NONE", "THIRD"])

    def test_ledger_prize_fields_are_additive_and_existing_metrics_stay_main_based(self):
        payload = {"type": "LOTO_6_55", "pickSize": 6,
                   "tickets": [{"main": [1, 2, 3, 4, 5, 20], "special": 21},
                               {"main": [1, 2, 3, 4, 5, 21], "special": 20}],
                   "probabilities": {str(number): 6 / 55 for number in range(1, 56)}}
        metrics = ledger.score_prediction_payload(payload, {"main": [1, 2, 3, 4, 5, 6], "special": 20}, 55, 6, 6)
        self.assertEqual(metrics["hit_count"], 5)
        self.assertEqual(metrics["mean_hits_per_ticket"], 5)
        self.assertEqual(metrics["special_hit"], 1)  # existing auxiliary-forecast metric is preserved
        self.assertEqual([ticket["special_hit"] for ticket in metrics["per_ticket"]], [0, 1])
        self.assertEqual([ticket["prize_code"] for ticket in metrics["per_ticket"]], ["POWER_JACKPOT_2", "FIRST"])
        self.assertEqual(metrics["prize_counts"], {"FIRST": 1, "POWER_JACKPOT_2": 1})
        self.assertEqual(metrics["prize_scope"], PRIZE_SCOPE)
        self.assertAlmostEqual(metrics["lift"], 5 / (36 / 55) - 1)
        prior = 6 / 55
        self.assertAlmostEqual(metrics["brier_score"], prior * (1 - prior))
        self.assertAlmostEqual(metrics["log_loss"], -prior * math.log(prior) - (1 - prior) * math.log(1 - prior))
        self.assertEqual(metrics["actual_main"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(metrics["actual_special"], 20)

    def test_ledger_keno_prize_classification_keeps_same_level_scoring_metrics(self):
        payload = {"type": "KENO", "pickSize": 5, "tickets": [{"main": [1, 2, 30, 31, 32]}],
                   "probabilities": {str(number): .25 for number in range(1, 81)}}
        metrics = ledger.score_prediction_payload(payload, {"main": list(range(1, 21))}, 80, 20, 10)
        self.assertEqual(metrics["prediction_size"], 5)
        self.assertEqual(metrics["hit_count"], 2)
        self.assertAlmostEqual(metrics["lift"], 2 / 1.25 - 1)
        self.assertEqual(metrics["prize_results"][0]["status"], "lost")
        self.assertFalse(metrics["prize_results"][0]["isWinning"])


if __name__ == "__main__":
    unittest.main()
