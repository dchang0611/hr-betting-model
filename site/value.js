const valueView = document.querySelector("#value-view");
const valueRows = document.querySelector("#value-rows");
const oddsStatus = document.querySelector("#odds-status");
let valuePayload = { rows: [], oddsStatus: {} };

function valueAmerican(value) {
  if (value == null) return "--";
  const number = Number(value);
  return number > 0 ? `+${number}` : `${number}`;
}

function valueEscape(value) {
  return String(value ?? "--").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function valueNumber(value) {
  return value == null || Number.isNaN(Number(value)) ? "--" : Number(value).toFixed(1);
}

function renderValueBoard() {
  const status = valuePayload.oddsStatus || {};
  oddsStatus.textContent = status.message || "Live HR odds were not available.";
  const picks = (valuePayload.rows || [])
    .filter(row => row.best_hr_odds != null && row.calibrated_hr_probability != null)
    .sort((a, b) => (Number(b.expected_value_pct) || -999) - (Number(a.expected_value_pct) || -999));
  valueRows.innerHTML = picks.map(row => {
    const positive = ["Strong value", "Value", "Watch"].includes(row.value_label);
    const className = positive ? "value-positive" : "value-pass";
    const edgePrefix = Number(row.value_edge_pct_points) > 0 ? "+" : "";
    const evPrefix = Number(row.expected_value_pct) > 0 ? "+" : "";
    return `<tr>
      <td><strong>${valueEscape(row.batter_name_hand)}</strong><br><small>${valueEscape(row.game_matchup)}</small></td>
      <td class="prob">${valueAmerican(row.best_hr_odds)}</td>
      <td>${valueEscape(row.best_hr_book)}</td>
      <td>${valueNumber(row.calibrated_hr_probability)}%</td>
      <td>${valueNumber(Number(row.market_implied_probability) * 100)}%</td>
      <td class="${className}">${edgePrefix}${valueNumber(row.value_edge_pct_points)} pts</td>
      <td class="${className}">${evPrefix}${valueNumber(row.expected_value_pct)}%</td>
      <td class="${className}">${valueEscape(row.value_label)}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="8" class="error">No current VegasInsider odds matched this slate. No value picks were issued.</td></tr>';
}

fetch("data/board.json", { cache: "no-store" })
  .then(response => response.ok ? response.json() : Promise.reject())
  .then(data => { valuePayload = data; renderValueBoard(); })
  .catch(() => { oddsStatus.textContent = "The value board is not available yet."; });

document.querySelectorAll('.tab[data-view="value"]').forEach(button => button.addEventListener("click", () => {
  document.querySelector("#players-view").hidden = true;
  document.querySelector("#games-view").hidden = true;
  document.querySelector("#performance-view").hidden = true;
  valueView.hidden = false;
  document.querySelector("#search").hidden = true;
  document.querySelector("#view-kicker").textContent = "LIVE MARKET";
  document.querySelector("#view-title").textContent = "Value home-run picks";
  renderValueBoard();
}));

document.querySelectorAll('.tab:not([data-view="value"])').forEach(button => button.addEventListener("click", () => {
  valueView.hidden = true;
}));
