const pct=v=>v==null?"—":`${(Number(v)*100).toFixed(1)}%`;
const num=(v,d=3)=>v==null?"—":Number(v).toFixed(d);
let payload, filtered=[];
function matchupLabel(r){if(!r.batting_team||!r.fielding_team)return r.game_matchup||"Matchup TBD";const home=Number(r.is_home_batter)===1?r.batting_team:r.fielding_team,away=Number(r.is_home_batter)===1?r.fielding_team:r.batting_team;return `${away} @ ${home}`}

function playerRow(r){
  return `<tr><td>${r.ranking}</td><td><strong>${r.batter_name_hand||"Unknown"}</strong><br><small>${r.batting_team||""}</small></td>
  <td>${matchupLabel(r)}</td><td>${r.pitcher_name_hand||"TBD"}</td>
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
  const top40=filtered.filter(r=>Number(r.ranking)<=40);
  const groups={};
  top40.forEach(r=>{
    const key=r.game_pk||r.game_matchup;
    (groups[key]??=[]).push(r);
  });
  const gameTime=value=>{
    if(!value)return"TBD";
    const date=new Date(value);
    if(Number.isNaN(date.getTime()))return"TBD";
    return new Intl.DateTimeFormat("en-US",{
      timeZone:"America/Los_Angeles",hour:"numeric",minute:"2-digit",timeZoneName:"short"
    }).format(date);
  };
  const cardinal=deg=>{
    if(deg==null)return"unknown direction";
    const points=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
    return points[Math.round((Number(deg)%360)/22.5)%16];
  };
  document.querySelector("#games-view").innerHTML=Object.values(groups)
    .sort((a,b)=>{
      const aTime=Date.parse(a[0].commence_time||"");
      const bTime=Date.parse(b[0].commence_time||"");
      if(Number.isNaN(aTime)&&Number.isNaN(bTime))return Math.min(...a.map(r=>r.ranking))-Math.min(...b.map(r=>r.ranking));
      if(Number.isNaN(aTime))return 1;
      if(Number.isNaN(bTime))return-1;
      return aTime-bTime;
    })
    .map(rows=>{
      const first=rows[0];
      const roofed=Number(first.is_roofed_no_wind)===1;
      const wind=roofed?"Roofed venue · wind neutralized":`${num(first.wind_speed_mph,0)} mph from ${cardinal(first.wind_direction_deg)}${Number(first.weather_blowing_out)===1?" · blowing out":""}`;
      const teams=Object.values(rows.reduce((acc,row)=>{
        (acc[row.batting_team]??=[]).push(row);
        return acc;
      },{})).sort((a,b)=>Number(a[0].is_home_batter)-Number(b[0].is_home_batter));
      const teamPanels=teams.map(teamRows=>{
        const team=teamRows[0];
        const pitcherStats=[
          team.pitcher_name_hand||"TBD",
          team.pitcher_k_rate_prior!=null?`K ${pct(team.pitcher_k_rate_prior)}`:null,
          team.pitcher_tb_allowed_per_pa_prior!=null?`TB/PA ${num(team.pitcher_tb_allowed_per_pa_prior)}`:null
        ].filter(Boolean).join(" · ");
        return `<section class="game-team"><div class="game-team-head"><h3>${team.batting_team}</h3><small>vs ${pitcherStats}</small></div>
          <div class="game-list">${teamRows.sort((a,b)=>a.ranking-b.ranking).map(r=>`<span class="pill">#${r.ranking} ${r.batter_name_hand} <strong>${pct(r.final_tb_probability)}</strong></span>`).join("")}</div></section>`;
      }).join("");
      return `<article class="game matchup-game">
        <div class="matchup-head"><div><p class="eyebrow">${gameTime(first.commence_time)}</p><h3>${matchupLabel(first)}</h3></div>
          <span class="environment">${num(first.temp_f,0)}°F · ${wind}</span></div>
        <div class="matchup-teams">${teamPanels}</div>
      </article>`;
    }).join("");
}
function renderBacktest(){
  const summaries=payload.backtest?.summary||[];
  document.querySelector("#cards").innerHTML=summaries.map(s=>`<div class="card"><span>Top ${s.top_n}</span><h3>${pct(s.hit_rate)}</h3><small>${s.wins} wins / ${s.players} picks</small></div>`).join("");
  const n=Number(document.querySelector("#top-n").value);
  const start=document.querySelector("#backtest-start").value;
  const end=document.querySelector("#backtest-end").value;
  const chronological=(payload.backtest?.daily||[])
    .filter(r=>Number(r.top_n)===n&&(!start||r.game_date>=start)&&(!end||r.game_date<=end))
    .sort((a,b)=>a.game_date.localeCompare(b.game_date));
  let cumulativePlayers=0,cumulativeWins=0;
  chronological.forEach(r=>{
    cumulativePlayers+=Number(r.players);
    cumulativeWins+=Number(r.wins);
    r.filtered_cumulative_hit_rate=cumulativeWins/cumulativePlayers;
  });
  const daily=[...chronological].reverse();
  const available=payload.backtest?.dateRange;
  document.querySelector("#backtest-range").textContent=available?.min
    ?`Available backtest: ${available.min} through ${available.max} · Showing ${daily.length} game dates`
    :"No backtest dates are available.";
  document.querySelector("#backtest-rows").innerHTML=daily.map(r=>{
    const key=`bt-${n}-${r.game_date}`;
    const picks=(r.picks||[]).map(p=>`<div class="pick-row"><span>#${p.rank}</span><strong>${p.player}</strong><span>${p.team||"—"} vs ${p.opponent||"—"}</span><span>${pct(p.probability)}</span><span class="pick-result ${p.won?"win":"loss"}">${p.won?`Won · ${p.total_bases} TB`:`Lost · ${p.total_bases} TB`}</span></div>`).join("");
    return `<tr><td><button class="backtest-toggle" data-target="${key}">Names</button></td><td>${r.game_date}</td><td>${r.players}</td><td>${r.wins}</td><td>${pct(r.hit_rate)}</td><td>${pct(r.filtered_cumulative_hit_rate)}</td><td>${pct(r.avg_model_probability)}</td></tr>
    <tr id="${key}" class="detail" hidden><td colspan="7"><div class="pick-list">${picks}</div></td></tr>`;
  }).join("");
  document.querySelectorAll(".backtest-toggle").forEach(button=>button.onclick=()=>{
    const detail=document.querySelector(`#${button.dataset.target}`);
    detail.hidden=!detail.hidden;
    button.textContent=detail.hidden?"Names":"Hide";
  });
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
  const range=data.backtest?.dateRange;
  if(range?.min){
    for(const id of ["backtest-start","backtest-end"]){
      document.querySelector(`#${id}`).min=range.min;
      document.querySelector(`#${id}`).max=range.max;
    }
    document.querySelector("#backtest-start").value=range.min;
    document.querySelector("#backtest-end").value=range.max;
  }
  renderRows();renderGames();renderBacktest();
  document.querySelector("#search").oninput=e=>{const q=e.target.value.toLowerCase();filtered=data.rows.filter(r=>JSON.stringify(r).toLowerCase().includes(q));renderRows();renderGames()};
  document.querySelector("#top-n").onchange=renderBacktest;
  document.querySelector("#backtest-start").onchange=renderBacktest;
  document.querySelector("#backtest-end").onchange=renderBacktest;
  document.querySelector("#reset-dates").onclick=()=>{
    if(range?.min){
      document.querySelector("#backtest-start").value=range.min;
      document.querySelector("#backtest-end").value=range.max;
    }
    renderBacktest();
  };
  document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>show(b.dataset.view));
}).catch(()=>document.querySelector("#error").hidden=false);
