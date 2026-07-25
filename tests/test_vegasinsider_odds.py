import unittest

from vegasinsider_odds import (
    american_implied_probability,
    normalize_player_name,
    parse_vegasinsider_html,
)


HTML = """
<html><body>
<h1>Home Run Odds 07/25/2026</h1>
<table id="table-home-runs">
  <thead><tr><th></th><th><span class="hidden">Bet365</span></th>
  <th><span class="hidden">FanDuel</span></th><th></th></tr></thead>
  <tbody id="see-all-home-runs">
    <tr data-name="josé ramírez"><td>José Ramírez</td>
      <td><span>o0.5</span><span>+425</span></td>
      <td><span class="data-moneyline">+450</span></td><td></td>
    </tr>
    <tr data-name="no price"><td>No Price</td><td></td><td>0</td><td></td></tr>
  </tbody>
</table>
</body></html>
"""


class VegasInsiderOddsTests(unittest.TestCase):
    def test_parser_extracts_date_books_and_best_price(self):
        source_date, rows = parse_vegasinsider_html(HTML)
        self.assertEqual(source_date, "2026-07-25")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_key"], "jose ramirez")
        self.assertEqual(rows[0]["best_hr_book"], "FanDuel")
        self.assertEqual(rows[0]["best_hr_odds"], 450)
        self.assertEqual(rows[0]["fanduel_hr_odds"], 450)

    def test_name_normalization_removes_hand(self):
        self.assertEqual(normalize_player_name("José Ramírez (S)"), "jose ramirez")

    def test_implied_probability(self):
        self.assertAlmostEqual(american_implied_probability(500), 1 / 6)
        self.assertAlmostEqual(american_implied_probability(-150), 0.6)


if __name__ == "__main__":
    unittest.main()
