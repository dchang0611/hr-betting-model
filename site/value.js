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

function valueMatchupLabel(row) {
  if (!row.batting_team || !row.fielding_team) return row.game_matchup || "Matchup TBD";
  const home = Number(row.is_home_batter) === 1 ? row.batting_team : row.fielding_team;
  const away = Number(row.is_home_batter) === 1 ? row.fielding_team : row.batting_team;
  return `${away} @ ${home}`;
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

function valueQualitativeSummary(row) {
  const strengths = [];
  const cautions = [];
  const grade = (value, strong, favorable, caution) => {
    const score = Number(value);
    if (!Number.isFinite(score)) return;
    if (score >= 80) strengths.push(strong);
    else if (score >= 65) strengths.push(favorable);
    else if (score < 30) cautions.push(caution);
  };
  grade(row.batter_power, "elite power", "a strong power profile", "limited underlying power");
  grade(row.recent_form, "excellent recent form", "solid recent form", "cold recent form");
  grade(row.pitcher_vulnerability, "a highly vulnerable opposing pitcher", "a favorable pitcher matchup", "a pitcher who has limited damage");
  grade(row.handedness_splits, "an excellent handedness matchup", "a favorable handedness matchup", "an unfavorable handedness split");
  grade(row.pitch_type_matchup, "an excellent broad pitch-mix fit", "a favorable broad pitch-mix fit", "a weaker broad pitch-mix fit");
  const environment = Number(row.environment);
  if (Number.isFinite(environment)) {
    if (environment >= 70) strengths.push("a very favorable hitting environment");
    else if (environment >= 60) strengths.push("a favorable hitting environment");
    else if (environment < 30) cautions.push("a difficult hitting environment");
  }
  const lead = strengths.length
    ? `The baseball case is led by ${valueList(strengths.slice(0, 3))}.`
    : "The Strong Value signal is driven mainly by the gap between the model probability and the available price, rather than an across-the-board matchup advantage.";
  const context = cautions.length
    ? `The main caution is ${valueList(cautions.slice(0, 2))}.`
    : "No major supporting category grades as a significant weakness.";
  return `${lead} ${context}`;
}

function valueList(items) {
  if (items.length < 2) return items[0] || "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
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
    const qualitativeSummary = valueQualitativeSummary(row);
    return `<tr>
      <td><strong>${valueEscape(row.batter_name_hand)}</strong><br><small>${valueEscape(valueMatchupLabel(row))} vs ${valueEscape(row.pitcher_name_hand)}</small></td>
      <td class="prob">${valueAmerican(row.best_hr_odds)}</td>
      <td>${valueEscape(row.best_hr_book)}</td>
      <td>${valueNumber(row.calibrated_hr_probability)}%</td>
      <td>${valueNumber(Number(row.market_implied_probability) * 100)}%</td>
      <td class="${className}">${edgePrefix}${valueNumber(row.value_edge_pct_points)} pts</td>
      <td class="${className}">${evPrefix}${valueNumber(row.expected_value_pct)}%</td>
      <td class="${className}">${valueEscape(row.value_label)}</td>
    </tr>
    <tr class="value-explanation-row"><td colspan="8"><div class="value-explanation"><p class="value-read"><strong>Why it is strong:</strong> ${valueEscape(qualitativeSummary)}</p>${matchupFactors ? `<div class="value-factors"><small>TOP SUPPORTING MODEL FACTORS</small>${matchupFactors}</div>` : ""}</div></td></tr>`;
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
