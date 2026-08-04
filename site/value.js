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

function valueFactorReasons(row) {
  const factors = [
    ["Power", row.batter_power, 70],
    ["Recent form", row.recent_form, 70],
    ["Pitcher vulnerability", row.pitcher_vulnerability, 70],
    ["Handedness matchup", row.handedness_splits, 70],
    ["Pitch-type matchup", row.pitch_type_matchup, 70],
    ["Matchup history", row.matchup_history, 70],
    ["Environment", row.environment, 60]
  ];
  return factors
    .filter(([, value, threshold]) => value != null && Number(value) >= threshold)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3)
    .map(([label, value]) => `<span class="value-factor">${valueEscape(label)} ${valueNumber(value)}/100</span>`)
    .join("");
}

function renderValueBoard() {
  const status = valuePayload.oddsStatus || {};
  oddsStatus.textContent = status.message || "Live HR odds were not available.";
  const picks = (valuePayload.rows || [])
    .filter(row => row.best_hr_odds != null && row.calibrated_hr_probability != null && row.value_label === "Strong value")
    .sort((a, b) => (Number(b.expected_value_pct) || -999) - (Number(a.expected_value_pct) || -999));
  valueRows.innerHTML = picks.map(row => {
    const positive = ["Strong value", "Value", "Watch"].includes(row.value_label);
    const className = positive ? "value-positive" : "value-pass";
    const edgePrefix = Number(row.value_edge_pct_points) > 0 ? "+" : "";
    const evPrefix = Number(row.expected_value_pct) > 0 ? "+" : "";
    const matchupFactors = valueFactorReasons(row);
    return `<tr>
      <td><strong>${valueEscape(row.batter_name_hand)}</strong><br><small>${valueEscape(row.game_matchup)} vs ${valueEscape(row.pitcher_name_hand)}</small></td>
      <td class="prob">${valueAmerican(row.best_hr_odds)}</td>
      <td>${valueEscape(row.best_hr_book)}</td>
      <td>${valueNumber(row.calibrated_hr_probability)}%</td>
      <td>${valueNumber(Number(row.market_implied_probability) * 100)}%</td>
      <td class="${className}">${edgePrefix}${valueNumber(row.value_edge_pct_points)} pts</td>
      <td class="${className}">${evPrefix}${valueNumber(row.expected_value_pct)}%</td>
      <td class="${className}">${valueEscape(row.value_label)}</td>
    </tr>
    <tr class="value-explanation-row"><td colspan="8"><div class="value-explanation"><strong>Why it is strong:</strong> The model gives ${valueEscape(row.batter_name_hand)} a ${valueNumber(row.calibrated_hr_probability)}% HR probability versus ${valueNumber(Number(row.market_implied_probability) * 100)}% implied by the market—an edge of ${edgePrefix}${valueNumber(row.value_edge_pct_points)} points and ${evPrefix}${valueNumber(row.expected_value_pct)}% expected value at ${valueAmerican(row.best_hr_odds)}. Strong Value requires at least a +5-point edge and +20% expected value, so this pick clears both thresholds. <strong>Pitcher:</strong> ${valueEscape(row.pitcher_name_hand)}.${matchupFactors ? `<div class="value-factors"><small>TOP SUPPORTING MODEL FACTORS</small>${matchupFactors}</div>` : ""}</div></td></tr>`;
  }).join("") || '<tr><td colspan="8" class="error">No current VegasInsider odds matched this slate. No value picks were issued.</td></tr>';
}

function loadValuePayload(date = "") {
  const url = date ? `data/history/${encodeURIComponent(date)}.json` : "data/board.json";
  return fetch(url, { cache: "no-store" })
    .then(response => response.ok ? response.json() : Promise.reject())
    .then(data => { valuePayload = data; renderValueBoard(); })
    .catch(() => {
      valuePayload = { rows: [], oddsStatus: {} };
      oddsStatus.textContent = "The value board is not available for this slate.";
      renderValueBoard();
    });
}

loadValuePayload();
document.querySelector("#date-select").addEventListener("change", event => {
  loadValuePayload(event.target.value);
});

document.querySelectorAll('.tab[data-view="value"]').forEach(button => button.addEventListener("click", () => {
  document.querySelector("#players-view").hidden = true;
  document.querySelector("#games-view").hidden = true;
  document.querySelector("#performance-view").hidden = true;
  valueView.hidden = false;
  document.querySelector("#search").hidden = true;
  document.querySelector("#view-kicker").textContent = "LIVE MARKET";
  document.querySelector("#view-title").textContent = "Value home-run picks";
  loadValuePayload(document.querySelector("#date-select").value);
}));

document.querySelectorAll('.tab:not([data-view="value"])').forEach(button => button.addEventListener("click", () => {
  valueView.hidden = true;
}));
