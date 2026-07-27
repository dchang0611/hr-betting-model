const pct=v=>v==null?"—":`${(Number(v)*100).toFixed(1)}%`;
const num=(v,d=3)=>v==null?"—":Number(v).toFixed(d);
let payload, filtered=[];

function playerRow(r){
  return `<tr><td>${r.ranking}</td><td><strong>${r.batter_name_hand||"Unknown"}</strong><br><small>${r.batting_team||""}</small></td>
  <td>${r.game_matchup||`${r.batting_team} vs ${r.fielding_team}`}</td><td>${r.pitcher_name_hand||"TBD"}</td>
  <td class="prob">${pct(r.final_tb_probability)}</td><td class="signal-${r.tb_signal}">${r.tb_signal||"—"}</td>
  <td>${num(r.batter_recent_tb_per_pa_10)}</td><td><button class="more" data-rank="${r.ranking}">Details</button></td></tr>
  <tr id="detail-${r.ranking}" class="detail" hidden><td colspan="8"><div class="detail-grid">
  <div class="metric"><span>Career-season TB / PA</span><strong>${num(r.batter_tb_per_pa_prior)}</strong></div>
  <div class="metric"><span>Recent hit rate</span><strong>${pct(r.batter_recent_hit_rate_10)}</strong></div>
  <div class="metric"><span>Extra-base-hit rate</span><strong>${pct(r.batter_xbh_rate_prior)}</strong></div>
  <div class="metric"><span>Pitcher TB allowed / PA</span><strong>${num(r.pitcher_tb_allowed_per_pa_prior)}</strong></div>
  <div class="metric"><span>Barrel rate</span><strong>${pct(r.batter_barrel_rate_prior)}</strong></div>
  <div class="metric"><span>Park factor</span><strong>${num(r.park_factor,2)}</strong></div>
  </div></td></tr>`;
}
function renderRows(){
  document.querySelector("#rows").innerHTML=filtered.map(playerRow).join("");
  document.querySelectorAll(".more").forEach(b=>b.onclick=()=>{
    const el=document.querySelector(`#detail-${b.dataset.rank}`);el.hidden=!el.hidden;
  });
}
function renderGames(){
  const groups={};filtered.forEach(r=>(groups[r.game_matchup||`${r.batting_team} vs ${r.fielding_team}`]??=[]).push(r));
  document.querySelector("#games-view").innerHTML=Object.entries(groups).map(([g,rows])=>
    `<article class="game"><h3>${g}</h3><div class="game-list">${rows.slice(0,12).map(r=>
    `<span class="pill">${r.batter_name_hand}: <strong>${pct(r.final_tb_probability)}</strong></span>`).join("")}</div></article>`).join("");
}
function renderBacktest(){
  const summaries=payload.backtest?.summary||[];
  document.querySelector("#cards").innerHTML=summaries.map(s=>`<div class="card"><span>Top ${s.top_n}</span><h3>${pct(s.hit_rate)}</h3><small>${s.wins} wins / ${s.players} picks</small></div>`).join("");
  const n=Number(document.querySelector("#top-n").value);
  const daily=(payload.backtest?.daily||[]).filter(r=>Number(r.top_n)===n);
  document.querySelector("#backtest-rows").innerHTML=daily.map(r=>`<tr><td>${r.game_date}</td><td>${r.players}</td><td>${r.wins}</td><td>${pct(r.hit_rate)}</td><td>${pct(r.cumulative_hit_rate)}</td><td>${pct(r.avg_model_probability)}</td></tr>`).join("");
}
function show(view){
  ["board","games","performance"].forEach(v=>document.querySelector(`#${v}-view`).hidden=v!==view);
  document.querySelectorAll(".tabs button").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
  document.querySelector("#search").hidden=view==="performance";
}
fetch("data/board.json").then(r=>{if(!r.ok)throw Error();return r.json()}).then(data=>{
  payload=data;filtered=data.rows||[];
  document.querySelector("#date").textContent=data.targetDate;
  document.querySelector("#count").textContent=filtered.length;
  document.querySelector("#updated").textContent=new Date(data.updatedAt).toLocaleString();
  document.querySelector("#status").textContent=data.oddsStatus||"";
  renderRows();renderGames();renderBacktest();
  document.querySelector("#search").oninput=e=>{const q=e.target.value.toLowerCase();filtered=data.rows.filter(r=>JSON.stringify(r).toLowerCase().includes(q));renderRows();renderGames()};
  document.querySelector("#top-n").onchange=renderBacktest;
  document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>show(b.dataset.view));
}).catch(()=>document.querySelector("#error").hidden=false);
