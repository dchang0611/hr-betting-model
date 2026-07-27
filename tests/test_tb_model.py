import unittest

import pandas as pd

from tb_model import add_event_values, _pregame_rates, forward_rate_snapshot


class TotalBasesFeatureTests(unittest.TestCase):
    def test_event_values_follow_total_bases_rules(self):
        frame = pd.DataFrame(
            {"events": ["single", "double", "triple", "home_run", "walk", "field_out"]}
        )
        valued = add_event_values(frame)
        self.assertEqual(valued["total_bases"].tolist(), [1, 2, 3, 4, 0, 0])
        self.assertEqual(valued["hit"].tolist(), [1, 1, 1, 1, 0, 0])
        self.assertEqual(valued["extra_base_hit"].tolist(), [0, 1, 1, 1, 0, 0])

    def test_historical_rates_exclude_current_game(self):
        games = pd.DataFrame(
            {
                "game_date": pd.to_datetime(["2026-04-01", "2026-04-02"]),
                "game_pk": [1, 2],
                "batter": [10, 10],
                "pa": [4, 4],
                "total_bases": [4, 0],
                "hits": [1, 0],
                "extra_base_hits": [1, 0],
            }
        )
        rates = _pregame_rates(
            games, "batter", "batter", "pa", "total_bases", "hits", "extra_base_hits"
        )
        self.assertTrue(pd.isna(rates.loc[0, "batter_tb_per_pa_prior"]))
        self.assertEqual(rates.loc[1, "batter_tb_per_pa_prior"], 1.0)
        self.assertEqual(rates.loc[1, "batter_recent_hit_rate_10"], 0.25)

    def test_forward_snapshot_includes_latest_completed_game(self):
        games = pd.DataFrame(
            {
                "game_date": pd.to_datetime(["2026-04-01", "2026-04-02"]),
                "game_pk": [1, 2],
                "batter": [10, 10],
                "pa": [4, 4],
                "total_bases": [4, 0],
                "hits": [1, 0],
                "extra_base_hits": [1, 0],
            }
        )
        snapshot = forward_rate_snapshot(
            games, "batter", "batter", "pa", "total_bases", "hits", "extra_base_hits"
        )
        self.assertEqual(snapshot.loc[0, "batter_tb_per_pa_prior"], 0.5)
        self.assertEqual(snapshot.loc[0, "batter_recent_hit_rate_10"], 0.125)


if __name__ == "__main__":
    unittest.main()
