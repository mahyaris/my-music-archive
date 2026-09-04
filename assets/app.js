const state = { key: null, summary: null, manifest: null, yearCache: new Map(), charts: [], worldMapReady: false };
const $ = (q) => document.querySelector(q);
const fmt = new Intl.NumberFormat();
const pct = (v) => `${Number(v || 0).toFixed(1)}%`;

async function loadJSON(url){ const r=await fetch(url,{cache:'no-store'}); if(!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); }
function b64bytes(s){ return Uint8Array.from(atob(s), c=>c.charCodeAt(0)); }
async function deriveKey(password, cryptoCfg){
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({name:'PBKDF2', salt:b64bytes(cryptoCfg.salt), iterations:cryptoCfg.iterations, hash:'SHA-256'}, base, {name:'AES-GCM',length:256}, false, ['decrypt']);
}
async function decryptJSON(url){ const env=await loadJSON(url); const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64bytes(env.iv)}, state.key, b64bytes(env.ciphertext)); return JSON.parse(new TextDecoder().decode(plain)); }
function escapeHtml(s=''){ return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function pageShell(title, subtitle, body){ return `<section class="page"><div class="section-title page-heading"><div><p class="eyebrow">MY MUSIC ARCHIVE</p><h2>${title}</h2></div>${subtitle?`<p>${subtitle}</p>`:''}</div>${body}</section>`; }
function metric(v,l,sub=''){ return `<div class="metric"><strong>${v}</strong><span>${l}</span>${sub?`<small>${sub}</small>`:''}</div>`; }
function imageMarkup(row, cls='entity-art'){
  const src=row?.image, fallback=row?.fallbackImage;
  if(!src) return `<div class="${cls} art-fallback"><span>${escapeHtml((row?.name||'?').slice(0,1).toUpperCase())}</span></div>`;
  const fb=(fallback && fallback!==src) ? ` data-fallback="${escapeHtml(fallback)}" onerror="this.onerror=null;this.src=this.dataset.fallback"` : '';
  // Do not force no-referrer here. Some image CDNs treat an embedded request
  // differently from a direct navigation; the browser default is safer.
  return `<img class="${cls}" src="${escapeHtml(src)}" alt="" loading="lazy"${fb}>`;
}
function rankList(rows){ return `<div class="rank-list">${rows.map((r,i)=>`<div class="rank-row"><span class="rank-no">${String(i+1).padStart(2,'0')}</span>${r.image?imageMarkup(r,'rank-art'):''}<div class="rank-name"><strong>${escapeHtml(r.name)}</strong><span>${escapeHtml(r.artist||r.sub||'')}</span></div><span class="rank-count">${fmt.format(r.count)}</span></div>`).join('')}</div>`; }
function disposeCharts(){ state.charts.forEach(c=>{try{c.dispose()}catch{}}); state.charts=[]; }
function renderChart(el, option){ if(!el) return null; const c=echarts.init(el); c.setOption(option); state.charts.push(c); return c; }
addEventListener('resize',()=>state.charts.forEach(c=>c.resize()),{passive:true});
function chartTheme(){ const cs=getComputedStyle(document.documentElement); return { text:cs.getPropertyValue('--text').trim(), muted:cs.getPropertyValue('--muted').trim(), border:cs.getPropertyValue('--border').trim(), accent:cs.getPropertyValue('--accent').trim(), accent2:cs.getPropertyValue('--accent-2').trim(), surface:cs.getPropertyValue('--surface').trim(), mapBase:cs.getPropertyValue('--map-base').trim(), mapLow:cs.getPropertyValue('--map-low').trim(), mapMid:cs.getPropertyValue('--map-mid').trim(), mapHigh:cs.getPropertyValue('--map-high').trim(), mapTop:cs.getPropertyValue('--map-top').trim(), mapHover:cs.getPropertyValue('--map-hover').trim() }; }
function entityTags(row){ return row?.tags?.length ? `<div class="mini-tags">${row.tags.slice(0,3).map(t=>`<span>${escapeHtml(t)}</span>`).join('')}</div>` : ''; }
function celebrationGrid(rows,kind){ return `<div class="celebration-grid">${rows.slice(0,15).map((r,i)=>`<article class="celebration-card ${i===0?'champion':''}">${imageMarkup(r)}<div class="celebration-overlay"><span class="rank-chip">#${i+1}</span><div><h3>${escapeHtml(r.name)}</h3>${r.artist?`<p>${escapeHtml(r.artist)}</p>`:''}<strong>${fmt.format(r.count)} scrobbles</strong>${entityTags(r)}</div></div></article>`).join('')}</div>`; }

function topCountriesLine(countries){
  const names=(countries||[]).slice(0,3).map(x=>escapeHtml(x.name));
  if(!names.length) return '';
  return `<div class="meta-winner country-leaders"><span class="country-leaders-label">Top countries</span><div class="country-leaders-list">${names.join('&nbsp;&nbsp;·&nbsp;&nbsp;')}</div></div>`;
}

function renderOverview(){
  disposeCharts(); const s=state.summary, o=s.overview, i=s.insights;
  const hasMap=s.artistMap?.countries?.length, hasDecades=s.musicByDecade?.decades?.length;
  $('#content').innerHTML=`<section class="page"><div class="hero"><p class="eyebrow">YOUR LISTENING LIFE</p><h1>${fmt.format(o.totalScrobbles)} scrobbles.</h1><p>From ${o.firstYear} to ${o.latestYear}: the artists you lived with, the albums you returned to, and the phases that shaped your listening.</p></div>
  <div class="metric-grid">${metric(fmt.format(o.uniqueArtists),'artists')}${metric(fmt.format(o.uniqueAlbums),'known albums')}${metric(fmt.format(o.uniqueTracks),'unique tracks')}${metric(`${o.yearsTracked}`,'years tracked')}</div>
  <div class="section-title"><div><h2>Listening through time</h2><p>Annual scrobbles and breadth of listening.</p></div></div><div class="card chart-card"><div id="year-chart" class="chart tall"></div></div>
  <div class="section-title"><div><h2>All-time podium</h2><p>The seven artists that left the deepest footprint.</p></div></div>${celebrationGrid(s.topArtists.slice(0,7),'artists')}
  <div class="section-title"><div><h2>Archive leaders</h2><p>All-time albums and tracks.</p></div></div><div class="grid-2"><div class="card"><h3>Albums</h3>${rankList(s.topAlbums.slice(0,10))}</div><div class="card"><h3>Tracks</h3>${rankList(s.topTracks.slice(0,10))}</div></div>
  <div class="section-title compact"><div><h2>Archive insights</h2><p>Three signals that summarize the shape of your listening history.</p></div></div>
  <div class="grid-3"><div class="card insight-card"><small>Longest-running favorite</small><strong>${escapeHtml(i.longestRunning?.name||'—')}</strong><span class="muted">${i.longestRunning?.firstYear||''}–${i.longestRunning?.lastYear||''} · ${fmt.format(i.longestRunning?.count||0)} plays</span></div><div class="card insight-card"><small>Biggest single-year obsession</small><strong>${escapeHtml(i.biggestObsession?.name||'—')}</strong><span class="muted">${i.biggestObsession?.year||''} · ${fmt.format(i.biggestObsession?.count||0)} plays</span></div><div class="card insight-card"><small>Most diverse year</small><strong>${i.mostDiverseYear?.year||'—'}</strong><span class="muted">${i.mostDiverseYear?.diversityPer1000?.toFixed(0)||0} artists / 1,000 plays</span></div></div>
  <div class="section-title"><div><h2>Where and when your music comes from</h2><p>Artist geography and release-era profile across the full archive.</p></div></div>
  ${(hasMap||hasDecades)?`<div class="grid-2 overview-context-grid">${hasMap?`<div class="card"><div class="card-kicker">ARTIST MAP · ${s.artistMap.coverage}% of scrobbles mapped</div><div id="artist-map" class="chart map-chart"></div>${topCountriesLine(s.artistMap.countries)}</div>`:''}<div class="card"><div class="card-kicker">MUSIC BY DECADE${hasDecades?` · ${s.musicByDecade.coverage}% of scrobbles classified`:''}</div>${hasDecades?`<div id="decade-chart" class="chart map-chart"></div><div class="meta-winner">Largest era: <strong>${escapeHtml([...s.musicByDecade.decades].sort((a,b)=>b.count-a.count)[0]?.decade||'')}</strong></div>`:`<div class="decade-empty"><strong>Release-era data needs one enrichment pass.</strong><span>Run the metadata enrichment command again, then rebuild the archive. v2.6 fills missing album release years from MusicBrainz.</span></div>`}</div></div>`:`<div class="metadata-note card"><strong>Artist geography and music-by-decade need enrichment metadata.</strong><p>Run the metadata enrichment step, then rebuild the encrypted archive.</p></div>`}
  <div class="section-title"><div><h2>Rediscovered</h2><p>Artists you returned to after a gap of at least three years.</p></div></div><div class="card">${rankList(i.rediscovered.slice(0,20))}</div>
  <div class="section-title"><div><h2>Forgotten favorites</h2><p>Historically significant artists that have been absent from recent years.</p></div></div><div class="card">${rankList(i.forgotten.slice(0,20))}</div>
  </section>`;
  const t=chartTheme();
  renderChart($('#year-chart'),{backgroundColor:'transparent',tooltip:{trigger:'axis'},legend:{textStyle:{color:t.muted}},grid:{left:50,right:28,top:46,bottom:38},xAxis:{type:'category',data:s.yearly.map(x=>x.year),axisLabel:{color:t.muted},axisLine:{lineStyle:{color:t.border}}},yAxis:[{type:'value',axisLabel:{color:t.muted},splitLine:{lineStyle:{color:t.border}}},{type:'value',axisLabel:{color:t.muted},splitLine:{show:false}}],series:[{name:'Scrobbles',type:'line',smooth:true,symbolSize:6,data:s.yearly.map(x=>x.scrobbles),lineStyle:{width:4,color:t.accent},itemStyle:{color:t.accent},areaStyle:{opacity:.1,color:t.accent}},{name:'Artists',type:'line',smooth:true,yAxisIndex:1,data:s.yearly.map(x=>x.artists),lineStyle:{width:2,color:t.accent2},itemStyle:{color:t.accent2}}]});
  if(hasMap) renderArtistMap($('#artist-map'),s.artistMap,t);
  if(hasDecades) renderDecades($('#decade-chart'),s.musicByDecade,t);
}

function renderYears(){
  disposeCharts(); const s=state.summary;
  $('#content').innerHTML=pageShell('Years','Every year gets its own mini-Wrapped.',`<div class="pill-row year-pills" id="year-pills">${[...s.yearly].reverse().map(y=>`<button class="pill" data-year="${y.year}">${y.year}</button>`).join('')}</div><div id="year-detail" class="year-detail"></div>`);
  $('#year-pills').addEventListener('click',e=>{const b=e.target.closest('[data-year]'); if(b) showYear(+b.dataset.year,b);});
  const latest=s.yearly.at(-1).year; showYear(latest,$(`[data-year="${latest}"]`));
}
function discoveryCard(label,d){
  const delta=d.delta==null?'':`<span class="delta ${d.delta>=0?'up':'down'}">${d.delta>=0?'↑':'↓'} ${Math.abs(d.delta).toFixed(1)} pp</span>`;
  const item=d.topItem;
  return `<article class="discovery-card"><div class="discovery-head"><span>${label}</span><div><strong>${pct(d.percentage)}</strong>${delta}</div></div>${item?`<div class="discovery-winner">${imageMarkup(item,'winner-art')}<div><b>#1 ${escapeHtml(item.name)}</b><span>${escapeHtml(item.artist||'')} · ${fmt.format(item.count)} scrobbles</span></div></div>`:''}</article>`;
}
function factCard(icon,label,value,sub=''){ return `<article class="fact-card"><span class="fact-icon">${icon}</span><div><small>${label}</small><strong>${value}</strong>${sub?`<span>${sub}</span>`:''}</div></article>`; }
function showYear(year,button){
  disposeCharts(); document.querySelectorAll('.pill').forEach(x=>x.classList.remove('active')); button?.classList.add('active');
  const y=state.summary.yearDetails[String(year)]; const prev=state.summary.yearDetails[String(year-1)];
  const f=y.funFacts, first=f.firstScrobble;
  $('#year-detail').innerHTML=`
  <div class="year-hero"><div><p class="eyebrow">YEAR IN MUSIC</p><h2>${year}</h2><p>${fmt.format(y.scrobbles)} scrobbles · ${fmt.format(y.uniqueArtists)} artists · ${fmt.format(y.uniqueAlbums)} albums</p></div><div class="year-hero-stat"><span>Top-10 artist share</span><strong>${pct(y.top10Share)}</strong></div></div>
  <div class="section-title compact"><div><h2>Discovery</h2><p>How much of ${year} was genuinely new to your library.</p></div></div>
  <div class="discovery-grid">${discoveryCard('New Artists',y.discovery.artists)}${discoveryCard('New Albums',y.discovery.albums)}${discoveryCard('New Tracks',y.discovery.tracks)}</div>
  <div class="section-title compact"><div><h2>Little stories from ${year}</h2><p>The kind of details normal rankings miss.</p></div></div>
  <div class="facts-grid">
    ${factCard('▶','First scrobble',first?escapeHtml(first.track):'—',first?`${escapeHtml(first.artist)} · ${new Date(first.date).toLocaleDateString()}`:'')}
    ${factCard('⚡','Busiest day',f.busiestDate?.date||'—',f.busiestDate?`${fmt.format(f.busiestDate.count)} scrobbles`:'')}
    ${factCard('↻','Longest daily streak',`${f.longestDailyStreak} days`,'Consecutive days with at least one scrobble')}
    ${factCard('◎','Deepest rabbit hole',f.deepestRabbitHole?escapeHtml(f.deepestRabbitHole.artist):'—',f.deepestRabbitHole?`${f.deepestRabbitHole.count} plays on ${f.deepestRabbitHole.date}`:'')}
  </div>
  <div class="section-title compact"><div><h2>Your rhythm</h2><p>When music happened during ${year}.</p></div></div>
  <div class="grid-2 rhythm-grid"><div class="card"><div class="card-kicker">WEEKLY SCROBBLES</div><div class="chart" id="weekly-chart"></div><div class="chart-side-stat"><span>Busiest day</span><strong>${escapeHtml(y.busiestDay.label)}</strong><small>${fmt.format(y.busiestDay.count)} scrobbles</small></div></div><div class="card"><div class="card-kicker">LISTENING CLOCK</div><div class="clock-wrap"><div class="chart clock" id="clock-chart"></div><div class="chart-side-stat"><span>Busiest hour</span><strong>${String(y.busiestHour.label).padStart(2,'0')}:00</strong><small>${fmt.format(y.busiestHour.count)} scrobbles</small></div></div></div></div>
  <div class="section-title compact"><div><h2>The charts</h2><p>Who owned ${year}.</p></div></div>
  <div class="grid-3"><div class="card"><h3>Top artists</h3>${rankList(y.topArtists.slice(0,10))}</div><div class="card"><h3>Top albums</h3>${rankList(y.topAlbums.slice(0,10))}</div><div class="card"><h3>Top tracks</h3>${rankList(y.topTracks.slice(0,10))}</div></div>
  ${metadataYearPanels(y,year)}
  `;
  const t=chartTheme(); renderWeekly($('#weekly-chart'),y.activity.dayOfWeek,prev?.activity?.dayOfWeek,t,year); renderClock($('#clock-chart'),y.activity.hour,t);
  if(y.tagTimeline?.length && y.topTags?.length) renderTagTimeline($('#tag-chart'),y,t);
}
function metadataYearPanels(y,year){
  if(!y.topTags?.length) return `<div class="metadata-note card"><strong>Want year-specific genres and tags?</strong><p>That panel needs the optional metadata enrichment step. The core CSV does not contain genre/tag information.</p></div>`;
  return `<div class="section-title compact"><div><h2>Genres and tags</h2><p>How the character of your listening shifted through ${year}.</p></div></div>
  <div class="card wide-card"><div class="card-kicker">TOP TAGS · ${y.tagCoverage}% scrobble coverage</div><div id="tag-chart" class="chart tall"></div></div>`;
}
function renderWeekly(el,current,previous,t,year){
  renderChart(el,{tooltip:{trigger:'axis'},legend:{data:[String(year),String(year-1)],textStyle:{color:t.muted}},grid:{left:42,right:12,top:45,bottom:34},xAxis:{type:'category',data:current.map(x=>x.label),axisLabel:{color:t.muted},axisLine:{lineStyle:{color:t.border}}},yAxis:{type:'value',axisLabel:{color:t.muted},splitLine:{lineStyle:{color:t.border}}},series:[{name:String(year),type:'bar',barGap:'8%',data:current.map(x=>x.count),itemStyle:{color:t.accent,borderRadius:[6,6,0,0]}},{name:String(year-1),type:'bar',data:(previous||[]).map(x=>x.count),itemStyle:{color:t.accent2,opacity:.45,borderRadius:[6,6,0,0]}}]});
}
function renderClock(el,hours,t){
  const max=Math.max(...hours.map(x=>x.count),1);
  renderChart(el,{tooltip:{formatter:p=>`${p.name}:00 · ${fmt.format(p.value)} scrobbles`},polar:{radius:['25%','88%']},angleAxis:{type:'category',data:hours.map(x=>x.label),startAngle:90,clockwise:true,axisLabel:{color:t.muted,formatter:v=>['00','06','12','18'].includes(v)?v:''},axisLine:{show:false},axisTick:{show:false}},radiusAxis:{min:0,max:max,axisLine:{show:false},axisLabel:{show:false},splitLine:{show:false}},series:[{type:'bar',coordinateSystem:'polar',roundCap:false,barWidth:'78%',data:hours.map(x=>x.count),itemStyle:{color:t.accent2,borderColor:t.surface,borderWidth:2},showBackground:true,backgroundStyle:{color:t.border}}]});
}
function renderTagTimeline(el,y,t){ const tags=y.topTags.slice(0,6).map(x=>x.name); renderChart(el,{tooltip:{trigger:'axis'},legend:{data:tags,textStyle:{color:t.muted}},grid:{left:35,right:18,top:52,bottom:30},xAxis:{type:'category',boundaryGap:false,data:['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],axisLabel:{color:t.muted},axisLine:{lineStyle:{color:t.border}}},yAxis:{type:'value',show:false},series:tags.map(tag=>({name:tag,type:'line',stack:'tags',smooth:true,symbol:'none',lineStyle:{width:0},areaStyle:{opacity:.8},emphasis:{focus:'series'},data:y.tagTimeline.map(m=>m[tag]||0)}))}); }
function renderDecades(el,data,t){ const rows=data.decades; renderChart(el,{tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},grid:{left:80,right:18,top:18,bottom:22},xAxis:{type:'value',axisLabel:{show:false},splitLine:{show:false}},yAxis:{type:'category',data:rows.map(x=>x.decade),axisLabel:{color:t.muted},axisLine:{show:false},axisTick:{show:false}},series:[{type:'bar',data:rows.map(x=>x.count),itemStyle:{color:t.accent2,borderRadius:[0,5,5,0]},barWidth:'62%'}]}); }
async function renderArtistMap(el,data,t){
  try{
    if(!state.worldMapReady){
      const geo=await fetch('https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json').then(r=>r.json());
      echarts.registerMap('world-mma',geo);
      state.worldMapReady=true;
    }
    // v2.5 styling: top country gets maximum contrast; the next leaders and
    // remaining represented countries use two distinct blue tiers.
    const mapped=data.countries.map((x,idx)=>({
      name:x.name,
      value:x.count,
      itemStyle:{areaColor:idx===0?t.mapTop:(idx<4?t.mapHigh:t.mapLow)}
    }));
    renderChart(el,{
      tooltip:{formatter:p=>p.value?`${p.name}: ${fmt.format(p.value)} scrobbles`:p.name},
      series:[{
        type:'map',map:'world-mma',roam:false,selectedMode:false,
        itemStyle:{areaColor:t.mapBase,borderColor:t.surface,borderWidth:1},
        emphasis:{label:{show:false},itemStyle:{areaColor:t.mapHover||t.accent}},
        data:mapped
      }]
    });
  }catch(e){
    el.innerHTML=`<div class="map-fallback">${data.countries.slice(0,10).map((x,i)=>`<span class="${i===0?'top-country':''}"><b>${escapeHtml(x.name)}</b>${fmt.format(x.count)}</span>`).join('')}</div>`;
  }
}

function entityInsights(kind){ const s=state.summary, i=s.insights; if(kind==='artists') return [
  ['Longest-running favorite',i.longestRunning?.name||'—',`${i.longestRunning?.firstYear||''}–${i.longestRunning?.lastYear||''}`],
  ['Biggest single-year obsession',i.biggestObsession?.name||'—',`${i.biggestObsession?.year||''} · ${fmt.format(i.biggestObsession?.count||0)} plays`],
  ['Rediscoveries',fmt.format(i.rediscovered?.length||0),'Artists returning after a 3+ year gap']
];
 if(kind==='albums') return [
  ['All-time #1',s.topAlbums[0]?.name||'—',`${s.topAlbums[0]?.artist||''} · ${fmt.format(s.topAlbums[0]?.count||0)} plays`],
  ['Most enduring album',i.enduringAlbum?.name||'—',`${i.enduringAlbum?.artist||''} · heard across ${i.enduringAlbum?.years||0} years`],
  ['Known albums',fmt.format(s.overview.uniqueAlbums),'Distinct artist / album pairs']
 ];
 return [
  ['All-time #1',s.topTracks[0]?.name||'—',`${s.topTracks[0]?.artist||''} · ${fmt.format(s.topTracks[0]?.count||0)} plays`],
  ['Biggest one-day track binge',i.biggestTrackBinge?.name||'—',`${i.biggestTrackBinge?.artist||''} · ${i.biggestTrackBinge?.count||0} plays on ${i.biggestTrackBinge?.date||''}`],
  ['Unique tracks',fmt.format(s.overview.uniqueTracks),'Across the dated and legacy archive']
 ];
}
function renderEntityPage(kind){
  disposeCharts(); const map={artists:['Artists','topArtists','artists'],albums:['Albums','topAlbums','albums'],tracks:['Tracks','topTracks','tracks']}; const [title,key,label]=map[kind], rows=state.summary[key];
  const insights=entityInsights(kind);
  $('#content').innerHTML=pageShell(title,`Not just a leaderboard — a celebration of the ${label} that shaped your archive.`,`
    <div class="entity-intro"><p class="eyebrow">HALL OF FAME</p><h3>Your top 15</h3></div>${celebrationGrid(rows,kind)}
    <div class="section-title compact"><div><h2>Stories behind the ranking</h2><p>Small signals hidden inside nearly two decades of plays.</p></div></div>
    <div class="grid-3">${insights.map(x=>`<div class="card insight-card"><small>${escapeHtml(x[0])}</small><strong>${escapeHtml(x[1])}</strong><span class="muted">${escapeHtml(x[2])}</span></div>`).join('')}</div>
    <div class="section-title compact"><div><h2>Deep catalog</h2><p>Search and sort beyond the top 15.</p></div></div>
    <div class="search-row"><input id="entity-search" placeholder="Search ${kind}…"><select id="entity-sort"><option value="count">Most played</option><option value="name">A–Z</option></select></div><div id="entity-list" class="card"></div>`);
  const draw=()=>{let r=rows.filter(x=>JSON.stringify(x).toLowerCase().includes($('#entity-search').value.toLowerCase())); if($('#entity-sort').value==='name') r=[...r].sort((a,b)=>(a.name||'').localeCompare(b.name||'')); $('#entity-list').innerHTML=rankList(r.slice(0,100));}; $('#entity-search').oninput=draw; $('#entity-sort').onchange=draw; draw();
}

async function renderExplorer(){ disposeCharts(); const years=[...state.manifest.years].reverse(); $('#content').innerHTML=pageShell('Explorer','Search individual encrypted scrobbles by year',`<div class="search-row"><input id="explore-search" placeholder="Artist, album or track"><select id="explore-year">${years.map(y=>`<option>${y}</option>`).join('')}</select></div><p class="muted" id="explore-status"></p><div class="table-wrap"><table><thead><tr><th>Date</th><th>Artist</th><th>Album</th><th>Track</th></tr></thead><tbody id="explore-body"></tbody></table></div>`); const load=async()=>{const y=+$('#explore-year').value; $('#explore-status').textContent=`Decrypting ${y}…`; if(!state.yearCache.has(y)) state.yearCache.set(y,await decryptJSON(`data/year-${y}.enc.json`)); drawExplorer();}; const drawExplorer=()=>{const y=+$('#explore-year').value,q=$('#explore-search').value.toLowerCase(),rows=[...(state.yearCache.get(y)||[])].sort((a,b)=>(b.ts||0)-(a.ts||0)); const filtered=rows.filter(r=>!q||`${r.artist} ${r.album} ${r.track}`.toLowerCase().includes(q)).slice(0,1000); $('#explore-status').textContent=`${fmt.format(rows.length)} scrobbles in ${y}. Showing ${fmt.format(filtered.length)}${filtered.length===1000?' (latest 1,000)':''}.`; $('#explore-body').innerHTML=filtered.map(r=>`<tr><td>${escapeHtml(r.date)}</td><td>${escapeHtml(r.artist)}</td><td>${escapeHtml(r.album)}</td><td>${escapeHtml(r.track)}</td></tr>`).join('');}; $('#explore-year').onchange=load; $('#explore-search').oninput=drawExplorer; await load(); }

const routes={overview:renderOverview,years:renderYears,artists:()=>renderEntityPage('artists'),albums:()=>renderEntityPage('albums'),tracks:()=>renderEntityPage('tracks'),explorer:renderExplorer};
function route(){ const page=location.hash.replace('#','')||'overview'; document.querySelectorAll('#nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===page)); (routes[page]||renderOverview)(); document.querySelector('.sidebar')?.classList.remove('open'); scrollTo({top:0,behavior:'instant'}); }

async function unlock(password){ state.manifest=await loadJSON('data/manifest.json'); state.key=await deriveKey(password,state.manifest.crypto); state.summary=await decryptJSON('data/summary.enc.json'); $('#unlock').classList.add('hidden'); $('#app').classList.remove('hidden'); $('#updated-at').textContent=`${state.summary.overview.yearsTracked} years · encrypted`; route(); }
$('#unlock-form').addEventListener('submit',async e=>{e.preventDefault(); const btn=e.currentTarget.querySelector('button'); btn.disabled=true; $('#unlock-error').textContent=''; try{await unlock($('#password').value)}catch(err){console.error(err); $('#unlock-error').textContent='Could not unlock the archive. Check the password and confirm the data files were built with this version.'}finally{btn.disabled=false}});
$('#lock-button').onclick=()=>{state.key=null;state.summary=null;state.manifest=null;state.yearCache.clear();disposeCharts();$('#app').classList.add('hidden');$('#unlock').classList.remove('hidden');$('#password').value='';$('#password').focus();};
$('#menu-button').onclick=()=>document.querySelector('.sidebar').classList.toggle('open');
addEventListener('hashchange',route);
