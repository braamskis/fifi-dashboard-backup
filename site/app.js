(() => {
  const $ = s => document.querySelector(s);
  const state = { data:null, sizer:new Set(), sizeIn:{}, view:'prime', sort:'grade', filters:new Map(), industry:null, open:new Set(), alerts:null };
  const SETUPS = ['VCP','FLAG','HTF','WBO','WPV','WVCP','WFLAG','3WT'];
  const WEEKLY = ['WBO','WPV','WVCP','WFLAG'];
  const GRADE_COLOR = g => g==='A+'||g==='A' ? 'var(--gold)' : g==='B' ? 'var(--up)' : g==='C' ? 'var(--text)' : 'var(--down)';
  const pct = (x,d=1) => x==null||!isFinite(x) ? '–' : (x>=0?'+':'') + (x*100).toFixed(d) + '%';
  const money = x => x==null ? '–' : '$' + Number(x).toFixed(2);
  const cap = x => !x ? '' : x>=1e12 ? '$'+(x/1e12).toFixed(2)+'T' : x>=1e9 ? '$'+(x/1e9).toFixed(1)+'B' : '$'+(x/1e6).toFixed(0)+'M';
  const big = x => x==null ? '–' : x>=1e6 ? (x/1e6).toFixed(1)+'M' : x>=1e3 ? (x/1e3).toFixed(1)+'K' : String(Math.round(x));
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const tvSym = s => (s.x ? s.x+':' : '') + s.t.replace('-','.');

  async function getJSON(url){ const r = await fetch(url, {cache:'no-store'}); if(!r.ok) throw new Error(r.status); return r.json(); }
  async function load(){
    try{ state.data = await getJSON('scan.json'); }
    catch{
      $('#meta').textContent = 'Waiting for the first scan';
      $('#notice').innerHTML = '<p class="notice">No scan yet. The nightly run writes scan.json after the close; results appear here automatically.</p>';
      return;
    }
    try{ state.rrg = await getJSON('rrg.json'); }catch{ state.rrg = null; }
    try{ state.alerts = await getJSON('api/alerts'); }
    catch{ try{ state.alerts = await getJSON('alerts.json'); }catch{ state.alerts = state.data.sample_alerts || null; } }
    const fired = (state.alerts && state.alerts.fired) || [];
    fired.forEach(a => { const r = rowsOf(a.side).find(x => x.t===a.t); if(r && !r.badges.includes('TRG')) r.badges.unshift('TRG'); });

    render();
  }
  const rowsOf = side => state.data[side] || [];

  // ---------------------------------------------------------------- header
  function header(){
    const d = state.data;
    const date = new Date(d.as_of+'T12:00:00').toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric',year:'numeric'});
    $('#meta').textContent = `${date} close · ${d.passed} long, ${d.passed_short} short of ${d.liquid.toLocaleString()} liquid stocks`;
    const R = d.regime || {level:'yellow', text:''};
    const fired = (state.alerts && state.alerts.fired) || [];
    $('#notice').innerHTML =
      (d.demo ? '<p class="notice">Sample data. The page switches to real results once the nightly scan writes scan.json.</p>' : '') +
      `<p class="regime r-${R.level}"><b>${R.level==='green'?'Green light':R.level==='red'?'Red light':'Yellow light'}</b> ${esc(R.text)}</p>` +
      (fired.length ? `<p class="fired"><b>Triggered today</b> ${fired.map(a => `<button class="lnk" data-jump="${esc(a.t)}" data-side="${a.side}">${esc(a.t)} ${a.side==='long'?'▲':'▼'} ${esc(a.time)}</button>`).join(' ')}</p>` : '');
    const mk = d.market.map(m => {
      const reg = m.above50 && m.above200 ? ['var(--up)','Above 50 & 200'] : m.above200 ? ['var(--gold)','Above 200 only'] : ['var(--down)','Below 200'];
      return `<div class="mk"><b>${m.t} <span style="color:${m.chg1d>=0?'var(--up)':'var(--down)'}">${pct(m.chg1d)}</span></b><span><i class="dot" style="background:${reg[0]}"></i>${reg[1]}</span></div>`;
    }).join('');
    const b = d.breadth;
    $('#market').innerHTML = mk + `<div class="mk breadth"><b>${Math.round(b.above50*100)}% <span>above 50-day</span></b><div class="bar"><i style="width:${b.above50*100}%"></i></div><span>${b.new_highs} new highs · ${b.new_lows} new lows</span></div>`;
    document.querySelectorAll('[data-view]').forEach(bt => {
      bt.setAttribute('aria-pressed', bt.dataset.view===state.view);
      const n = bt.dataset.view==='long' ? d.passed : bt.dataset.view==='short' ? d.passed_short
              : bt.dataset.view==='prime' ? (d.prime||[]).length : null;
      bt.querySelector('small') && (bt.querySelector('small').textContent = n ?? '');
    });
    const listView = state.view==='long' || state.view==='short';
    $('#listTools').hidden = !listView; $('#list').hidden = !listView; $('#panel').hidden = listView;
  }

  // ---------------------------------------------------------------- list
  const matches = (s, f) =>
    f==='A+/A' ? (s.grade==='A+'||s.grade==='A') :
    f==='Setups' ? s.badges.some(b => SETUPS.includes(b)) :
    f==='Weekly' ? s.badges.some(b => WEEKLY.includes(b)) : s.badges.includes(f);

  function visible(){
    const side = state.view;
    return rowsOf(side).filter(s =>
      (!state.industry || s.industry===state.industry) &&
      [...state.filters].every(([f, mode]) => mode==='out' ? !matches(s, f) : matches(s, f)));
  }
  function chips(){
    const list = rowsOf(state.view), counts = {};
    list.forEach(s => s.badges.forEach(b => counts[b]=(counts[b]||0)+1));
    const n = f => list.filter(s => f(s)).length;
    const items = [['Setups', n(s=>s.badges.some(b=>SETUPS.includes(b)))], ['Weekly', n(s=>s.badges.some(b=>WEEKLY.includes(b)))],
                   ['A+/A', n(s=>s.grade==='A+'||s.grade==='A')]]
      .concat(Object.keys(state.data.legend).filter(k => counts[k]).map(k => [k, counts[k]]));
    const any = state.filters.size || state.industry;
    $('#chips').innerHTML = (state.industry ? `<button class="chip on" data-ind="">${esc(state.industry)} ✕</button>` : '') +
      (any ? `<button class="chip clr" data-clear="1">Clear</button>` : '') +
      items.filter(([,c]) => c).map(([k,c]) => {
        const mode = state.filters.get(k) || '';
        return `<button class="chip ${mode}" data-f="${esc(k)}" aria-pressed="${!!mode}" title="${mode==='in'?'Required. Tap to exclude.':mode==='out'?'Excluded. Tap to clear.':'Tap to require, tap again to exclude.'}">${mode==='out'?'✕ ':''}${esc(k)}<small>${c}</small></button>`;
      }).join('');
  }
  function rows(){
    const d = state.data, side = state.view, long = side==='long';
    const list = visible();
    const key = { grade:s=>s.score*100+(long?s.rs:100-s.rs), rs:s=>(long?s.rs:100-s.rs)*1000+s.score, chg:s=>long?s.chg1d:-s.chg1d }[state.sort];
    list.sort((a,b) => key(b)-key(a));
    $('#count').textContent = `${list.length} shown`;
    if(!list.length){
      const why = state.industry ? `No ${long?'long':'short'} setups in ${esc(state.industry)} tonight.`
        : rowsOf(side).length ? 'No stock matches every filter you picked. Clear one to see more.'
        : `No ${long?'long':'short'} setups passed tonight.`;
      $('#list').innerHTML = `<div class="empty">${why}<br><button class="lnk" data-clear="1">Clear filters</button></div>`;
      return;
    }
    $('#list').innerHTML = list.map(s => {
      const c = GRADE_COLOR(s.grade), open = state.open.has(s.t+side), k = s.t+'-'+side;
      const badges = s.badges.map(b => `<span class="b g-${d.groups_of[b]||'method'}" title="${esc(d.legend[b]||b)}">${esc(b)}</span>`).join('');
      const sub = [cap(s.mcap), '5D '+pct(s.chg5d), 'ADR '+s.adr.toFixed(1)+'%'].filter(Boolean).join(' · ');
      const rsCol = long ? (s.rs>=90?'var(--up)':s.rs>=80?'var(--text)':'var(--muted)') : (s.rs<=10?'var(--down)':s.rs<=20?'var(--text)':'var(--muted)');
      return `<article class="row${open?' open':''}" style="--edge:${c}">
        <button aria-expanded="${open}" data-t="${esc(s.t)}">
          <div><span class="tk">${esc(s.t)}</span><span class="chg" style="color:${s.chg1d>=0?'var(--up)':'var(--down)'}">${pct(s.chg1d)}</span></div>
          <div class="sub">${sub}</div>
          <div class="badges">${badges}</div>
          <div class="right">
            <span class="stage" title="Weinstein stage">${esc(s.stage)}</span>
            <span class="rs" title="Relative strength rank, 1-99" style="color:${rsCol}">${s.rs}</span>
            <span class="seal" style="--c:${c}" title="TQE grade, score ${s.score}/100"><span>${esc(s.grade)}<small>${s.score}</small></span></span>
          </div>
        </button>
        ${open ? detail(s, side, k) : ''}
      </article>`;
    }).join('');
    mountOpen();
  }

  function detail(s, side, k){
    const L = s.levels, lv = s.keylv || {}, long = side==='long', o = s.options;
    const tab = state.tabs[k] || 'd';
    const setup = (s.setup||[]).length ? `<div class="setup">${s.setup.map(x=>`<p>${esc(x)}</p>`).join('')}</div>` : '';
    const grp = s.grp ? `<p class="grp">${esc(s.industry)} · group RS ${s.grp.rank} of 99 (${s.grp.n} stocks)</p>` : (s.industry ? `<p class="grp">${esc(s.industry)}</p>` : '');
    const gaps = (lv.gaps||[]).map(g => `${g.dir==='up'?'Up':'Down'} gap ${money(g.lo)}–${money(g.hi)}`).join('<br>') || 'None in 60 days';
    const lvl = `
      <dl class="levels">
        <dt>${long?'Pivot':'Trigger'}</dt><dd>${money(L.pivot)}</dd>
        <dt>To ${long?'pivot':'trigger'}</dt><dd>${pct(L.pivot/s.price-1)}</dd>
        <dt>Stop (${esc(L.stop_note)})</dt><dd>${money(L.stop)}</dd>
        <dt>Risk to stop</dt><dd>${(L.risk*100).toFixed(1)}%</dd>
        <dt>21 EMA · 50 SMA</dt><dd>${money(L.ema21)} · ${money(L.sma50)}</dd>
      </dl>
      <dl class="levels">
        <dt>Weekly open</dt><dd>${money(lv.wo)}</dd>
        <dt>Prior month H · L</dt><dd>${money(lv.pm_h)} · ${money(lv.pm_l)}</dd>
        <dt>Open daily gaps</dt><dd>${gaps}</dd>
      </dl>`;
    let opts = '';
    if(o && o.has){
      const ivr = o.ivr!=null ? `IV rank ${o.ivr}` : `IV rank building (${o.ivr_n||0}/20 scans)`;
      const u = (o.unusual||[]).map(x => `<li><b>${big(x.vol)}</b> ${x.strike}${x.k} ${new Date(x.exp+'T12:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric'})} · OI ${big(x.oi)} · $${big(x.prem)} · ${x.otm>0?'+':''}${x.otm}%</li>`).join('');
      opts = `<div class="opts"><p><b>Options</b> IV ${o.iv ?? '–'}% · ${ivr} · IV/HV ${o.ivhv ?? '–'} · OI ${big(o.oi)} · ATM spread ${o.spread ?? '–'}% · ${o.weekly?'weeklies':'monthlies only'}${o.call_share!=null?` · ${Math.round(o.call_share*100)}% of premium in calls`:''}</p>
        ${u ? `<p class="muted">Unusual activity (volume well over open interest; buy or sell side unknown)</p><ul>${u}</ul>` : ''}</div>`;
    } else if(o){ opts = `<div class="opts"><p><b>Options</b> No listed options found.</p></div>`; }
    const checks = (s.checks||[]).map(c => `<span class="chk ${c.ok?'ok':'no'}" title="${esc(c.v)}">${c.ok?'✓':'✕'} ${esc(c.k)}</span>`).join('');
    return `<div class="detail">
      ${setup}${grp}
      ${checks ? `<div class="checks">${checks}</div>` : ''}
      <div class="chartwrap">
        <div class="tabs" role="tablist">
          ${[['d','Daily'],['w','Weekly'],['tv','TradingView']].map(([v,l]) => `<button role="tab" data-tab="${v}" data-k="${esc(k)}" aria-selected="${tab===v}">${l}</button>`).join('')}
        </div>
        <div class="chart" id="cb-${esc(k)}">${s.ohlc ? candles(s) : '<div class="loading">Loading chart…</div>'}${KEY(tab)}</div>
      </div>
      ${lvl}${opts}
      <div class="links"><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSym(s))}" target="_blank" rel="noopener">Open in TradingView</a></div>
    </div>`;
  }

  const KEY = tab => tab==='w'
    ? `<div class="keyline"><span><i style="background:#26c6da"></i>10 wk</span><span><i style="background:#e57373"></i>20 wk</span><span><i style="background:#9e9e9e"></i>40 wk</span><span><i style="background:#66bb6a"></i>RS line</span><span><i style="background:#b8962e"></i>Pivot</span><span><i style="background:#ff5252"></i>Stop</span></div>`
    : tab==='d' ? `<div class="keyline"><span><i style="background:#FFD54F"></i>8</span><span><i style="background:#4DB6FF"></i>21</span><span><i style="background:#BA68FF"></i>50 EMA</span><span><i style="background:#66bb6a"></i>RS line</span><span><i style="background:#b8962e"></i>Pivot</span><span><i style="background:#ff5252"></i>Stop</span><span><i style="background:#9aa7b8"></i>W open</span></div>` : '';

  // static fallback for the offline sample
  function candles(s){
    const W=360,H=150,P=4, bars=s.ohlc||[], n=bars.length;
    if(!n) return '';
    const emas=(s.ema||[]).map(e=>e.slice(-n)), vals=bars.flat().concat(...emas,[s.levels.pivot]);
    const lo=Math.min(...vals), hi=Math.max(...vals), y=v=>P+(H-2*P)*(1-(v-lo)/((hi-lo)||1)), step=(W-2*P)/n, x=i=>P+step*(i+.5), bw=Math.max(1.5,step*.62);
    const body=bars.map(([o,h,l,c],i)=>{ const up=c>=o, f=up?'#00c853':'#ff5252', e=f;
      return `<line x1="${x(i)}" x2="${x(i)}" y1="${y(h)}" y2="${y(l)}" stroke="${e}"/><rect x="${x(i)-bw/2}" y="${y(Math.max(o,c))}" width="${bw}" height="${Math.max(1,Math.abs(y(o)-y(c)))}" fill="${f}" stroke="${e}" stroke-width=".6"/>`; }).join('');
    const line=(a,col)=>`<path d="${a.map((v,i)=>(i?'L':'M')+x(i).toFixed(1)+' '+y(v).toFixed(1)).join('')}" fill="none" stroke="${col}" stroke-width="1.3"/>`;
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.t)} daily candles">${emas[2]?line(emas[2],'#BA68FF'):''}${emas[1]?line(emas[1],'#4DB6FF'):''}${emas[0]?line(emas[0],'#FFD54F'):''}<line x1="0" x2="${W}" y1="${y(s.levels.pivot)}" y2="${y(s.levels.pivot)}" stroke="#b8962e" stroke-dasharray="4 3"/>${body}</svg>`;
  }

  // ---------------------------------------------------------------- live charts
  state.tabs = {};
  const cache = {};
  let lwLib;
  const loadLW = () => lwLib ||= new Promise((res, rej) => {
    const el = document.createElement('script');
    el.src = 'https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js';
    el.onload = () => window.LightweightCharts ? res(window.LightweightCharts) : rej(new Error('no lib'));
    el.onerror = rej; document.head.appendChild(el);
  });
  async function chartData(s, k){
    if(cache[k]) return cache[k];
    try{ return cache[k] = await getJSON(`charts/${encodeURIComponent(k)}.json`); }
    catch{
      if(!s.ohlc) throw new Error('no chart');
      const n = s.ohlc.length, days = [];
      for(let d = new Date(state.data.as_of+'T12:00:00'); days.length < n; d.setDate(d.getDate()-1)) if(d.getDay()%6) days.unshift(d.toISOString().slice(0,10));
      return cache[k] = { bars:s.ohlc.map((b,i)=>[days[i],...b,0]), ema:{'8':s.ema[0],'21':s.ema[1],'50':s.ema[2]}, marks:[],
        lines:[{p:s.levels.pivot,t:'Pivot',c:'#b8962e',s:2},{p:s.levels.stop,t:'Stop',c:'#ff5252',s:2}] };
    }
  }
  async function mount(s, side){
    const k = s.t+'-'+side, box = document.getElementById('cb-'+k);
    if(!box) return;
    const tab = state.tabs[k] || 'd';
    if(tab === 'tv'){
      box.className = 'tv';
      box.innerHTML = '<div class="tradingview-widget-container" style="height:100%;width:100%"><div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div></div>';
      const sc = document.createElement('script');
      sc.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'; sc.async = true;
      sc.textContent = JSON.stringify({ autosize:true, symbol:tvSym(s), interval:'D', timezone:'America/New_York', theme:'dark', backgroundColor:'#000000', gridColor:'rgba(40,40,40,0.6)',
        style:'1', locale:'en', allow_symbol_change:false, support_host:'https://www.tradingview.com' });
      box.firstChild.appendChild(sc);
      return;
    }
    let LW, ch;
    try{ [LW, ch] = await Promise.all([loadLW(), chartData(s, k)]); }catch{ return; }
    if(!document.getElementById('cb-'+k) || (state.tabs[k]||'d') !== tab) return;
    const weekly = tab === 'w';
    if(weekly && !ch.wbars) return;
    box.className = 'chart';
    box.innerHTML = `<div class="lw"></div>${KEY(tab)}`;
    const chart = LW.createChart(box.firstChild, {
      autoSize:true, localization:{ locale:'en-US' },
      layout:{ background:{type:'solid', color:'#000000'}, textColor:'#9a9a9a', fontFamily:'Inter, system-ui, sans-serif', fontSize:11 },
      grid:{ vertLines:{visible:false}, horzLines:{color:'#1f1f1f', style:1} },
      rightPriceScale:{ borderColor:'#262626', scaleMargins:{ top:.22, bottom:.12 } }, timeScale:{ borderColor:'#262626', rightOffset:4 },
      crosshair:{ mode:0 },
    });
    const bars = weekly ? ch.wbars : ch.bars;
    const cs = chart.addCandlestickSeries({ upColor:'#00c853', downColor:'#ff5252', borderUpColor:'#00c853',
      borderDownColor:'#ff5252', wickUpColor:'#00c853', wickDownColor:'#ff5252' });
    cs.setData(bars.map(b => ({ time:b[0], open:b[1], high:b[2], low:b[3], close:b[4] })));
    if(bars.some(b => b[5])){
      const vol = chart.addHistogramSeries({ priceFormat:{type:'volume'}, priceScaleId:'vol', lastValueVisible:false, priceLineVisible:false });
      chart.priceScale('vol').applyOptions({ scaleMargins:{ top:.88, bottom:0 } });
      vol.setData(bars.map(b => ({ time:b[0], value:b[5], color: b[4]>=b[1] ? 'rgba(0,200,83,.35)' : 'rgba(255,82,82,.3)' })));
    }
    const rs = weekly ? ch.wrs : ch.rs;
    if(rs){   // RS line in its own band across the top, like the reference chart
      const rl = chart.addLineSeries({ color:'#66bb6a', lineWidth:1.5, priceScaleId:'rs', priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false });
      chart.priceScale('rs').applyOptions({ scaleMargins:{ top:.02, bottom:.8 }, visible:false });
      rl.setData(bars.map((b,i) => ({ time:b[0], value:rs[i] })).filter(p => p.value!=null));
    }
    const mas = weekly ? [['40','#9e9e9e',ch.wma],['20','#e57373',ch.wma],['10','#26c6da',ch.wma]]
                       : [['50','#BA68FF',ch.ema],['21','#4DB6FF',ch.ema],['8','#FFD54F',ch.ema]];
    mas.forEach(([n,col,src]) => {
      if(!src || !src[n]) return;
      const ls = chart.addLineSeries({ color:col, lineWidth:1.5, priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false });
      ls.setData(bars.map((b,i) => ({ time:b[0], value:src[n][i] })).filter(p => p.value!=null));
    });
    (ch.lines||[]).filter(l => l.p && (!weekly || l.t==='Pivot' || l.t==='Trigger' || l.t==='Stop'))
      .forEach(l => cs.createPriceLine({ price:l.p, color:l.c, lineWidth:1, lineStyle:l.s, axisLabelVisible: l.s===2, title:l.t }));
    if(!weekly) cs.setMarkers([...(ch.marks||[])].sort((a,b) => a.time < b.time ? -1 : 1).map(m => ({ ...m, color: m.shape==='arrowDown' ? '#d4af37' : '#00e676' })));
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length-(weekly?80:100)), to: bars.length+4 });
  }
  function mountOpen(){ rowsOf(state.view).filter(s => state.open.has(s.t+state.view)).forEach(s => mount(s, state.view)); }

  // ---------------------------------------------------------------- groups + scorecard
  function groupsView(){
    const g = state.data.groups || {top:[],bottom:[]};
    const tally = side => rowsOf(side).reduce((m,r)=>(m[r.industry]=(m[r.industry]||0)+1,m),{});
    const counts = { long: tally('long'), short: tally('short') };
    const tbl = (list, side) => `<table><thead><tr><th>Industry</th><th>RS</th><th>Stocks</th><th>${side==='long'?'Longs':'Shorts'}</th></tr></thead><tbody>${
      list.map(x => { const c = counts[side][x.name] || 0;
        return `<tr><td>${c ? `<button class="lnk" data-ind="${esc(x.name)}" data-side="${side}">${esc(x.name)}</button>` : `<span class="muted">${esc(x.name)}</span>`}</td><td>${x.rank}</td><td>${x.n}</td><td>${c||'–'}</td></tr>`; }).join('')}</tbody></table>`;
    $('#panel').innerHTML = `<h2>Strongest groups</h2><p class="muted">Median RS of each industry's liquid stocks, ranked 1-99. Tap one to see its long setups.</p>${tbl(g.top,'long')}
      <h2>Weakest groups</h2><p class="muted">Where the short setups tend to work best. Tap one to see its short setups.</p>${tbl(g.bottom,'short')}`;
  }
  function scoreView(){
    const S = state.data.scorecard;
    if(!S || !S.scans){ $('#panel').innerHTML = `<div class="empty">No scan history yet. Run the scan with backfill once (see the README), or give it a few nights.</div>`; return; }
    const cell = (v, suf='') => v==null ? '–' : v + suf;
    const tbl = rows => `<table><thead><tr><th></th><th>Setups</th><th>Triggered</th><th>Win</th><th>Avg R</th><th>Hit 2R</th><th>10-day</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${esc(r.key)}</td><td>${r.n}</td><td>${cell(r.trig,'%')}</td><td>${cell(r.win,'%')}</td><td class="${r.avg_r>0?'pos':r.avg_r<0?'neg':''}">${cell(r.avg_r)}</td><td>${cell(r.hit2,'%')}</td><td class="${r.ret10>0?'pos':r.ret10<0?'neg':''}">${cell(r.ret10,'%')}</td></tr>`).join('')}</tbody></table>`;
    const side = (k, label) => S[k] && S[k].all.n ? `<h2>${label}</h2>${tbl([{key:'All',...S[k].all}])}<h3>By grade</h3>${tbl(S[k].by_grade)}<h3>By pattern</h3>${tbl(S[k].by_pattern)}` : '';
    const recent = (S.recent||[]).map(r => `<tr><td>${esc(r.date.slice(5))}</td><td>${esc(r.t)} ${r.side==='long'?'▲':'▼'}</td><td>${esc(r.grade)}</td><td>${esc(r.pats.join(' '))}</td><td class="${r.r>0?'pos':r.r<0?'neg':''}">${cell(r.r)}R${r.done?'':' *'}</td></tr>`).join('');
    $('#panel').innerHTML = `<p class="muted">${S.scans} scans since ${esc(S.since)}. Triggered = reached the pivot within 10 sessions. R = result in multiples of the entry-to-stop risk: stopped out, or the close 20 sessions after entry. 10-day = move from the scan-day close, in the setup's direction. Small samples mislead, so give it a few months before trusting a row.</p>
      ${side('long','Longs')}${side('short','Shorts')}
      ${recent ? `<h2>Recent triggers</h2><table><thead><tr><th>Scan</th><th>Stock</th><th>Grade</th><th>Pattern</th><th>Result</th></tr></thead><tbody>${recent}</tbody></table><p class="muted">* still open</p>` : ''}`;
  }

  // ---------------------------------------------------------------- Confluence
  const acct = () => { try{ return Number(localStorage.getItem('fifi_acct')) || 100000; }catch{ return 100000; } };
  const riskPct = () => { try{ return Number(localStorage.getItem('fifi_riskpct')) || 1; }catch{ return 1; } };
  const rvolFloor = () => { try{ const v = localStorage.getItem('fifi_rvol'); return v === null ? 1.0 : Math.max(0, Number(v) || 0); }catch{ return 1.0; } };
  const BUCKETS = {
    leading:['In leading sectors','var(--up)'], improving:['Rotation candidates (improving)','#4DB6FF'],
    lagging:['In lagging sectors','var(--down)'], weakening:['Rotation candidates (weakening)','var(--gold)'],
    earnings:['Earnings nearby — higher risk','#c77dff'], other:['Everything else','var(--muted)'],
  };
  // Position sizer: entry and stop are editable, everything else follows
  function sizer(r){
    const key = r.t+'-'+r.side, L = r.levels || {}, s = state.sizeIn[key] || {};
    const entry = Number(s.entry ?? r.plan.entry), long = r.plan.t2 >= r.plan.entry;
    const opts = [['setup', `Setup stop (${esc(L.stop_note||'pattern')})`, L.stop],
                  ['ema21', '21 EMA', L.ema21], ['sma50', '50 SMA', L.sma50],
                  ['custom', 'Custom', null]].filter(o => o[2] != null || o[0]==='custom');
    const pick = s.pick || 'setup';
    const stop = Number(s.stop ?? (opts.find(o => o[0]===pick)||[])[2] ?? r.plan.stop);
    const per = Math.abs(entry - stop);
    const A = acct(), budget = Math.round(A * riskPct() / 100);
    const shares = per > 0 ? Math.floor(budget / per) : 0;
    const pos = shares * entry, toStop = entry ? (per / entry) * 100 : 0;
    return `<div class="sizer" data-keep="1">
      <div class="srow"><label>Entry <input type="number" step="0.01" data-sz="entry" data-key="${esc(key)}" value="${entry.toFixed(2)}"></label>
        <span class="muted">close ${money(r.price)}</span>
        <label>Stop <select data-sz="pick" data-key="${esc(key)}">${opts.map(o=>`<option value="${o[0]}"${o[0]===pick?' selected':''}>${o[1]}${o[2]!=null?` ${money(o[2])}`:''}</option>`).join('')}</select></label>
        <input type="number" step="0.01" data-sz="stop" data-key="${esc(key)}" value="${stop.toFixed(2)}"></div>
      <dl class="sgrid">
        <div><dt>Shares</dt><dd>${shares.toLocaleString()}</dd></div>
        <div><dt>$ risk</dt><dd>${money(shares*per)}</dd></div>
        <div><dt>% to stop</dt><dd>${toStop.toFixed(2)}%</dd></div>
        <div><dt>$ position</dt><dd>${money(pos).replace('.00','')}</dd></div>
        <div><dt>% of account</dt><dd>${A ? (pos/A*100).toFixed(2) : '–'}%</dd></div>
        <div><dt>Risk budget</dt><dd>$${budget.toLocaleString()} <span class="muted">(${riskPct()}% of $${A.toLocaleString()})</span></dd></div>
      </dl>
      <p class="thesis">Thesis broken if it closes ${long?'below':'above'} <b>${money(stop)}</b>${pick!=='custom'?` (${esc((opts.find(o=>o[0]===pick)||[])[1]||'')})`:''}.</p>
    </div>`;
  }

  const hidden = () => { try{ return new Set(JSON.parse(localStorage.getItem('fifi_hide') || '["THIN"]')); }catch{ return new Set(['THIN']); } };
  function primeView(){
    const d = state.data, C = d.confluence, hide = hidden();
    if(!C){ $('#panel').innerHTML = `<div class="empty">Confluence data arrives with the next scan.</div>`; return; }
    const A = acct(), rp = riskPct(), floor = rvolFloor(), dollars = Math.round(A * rp / 100);
    const row = (r, i) => {
      const long = r.plan && r.plan.t2 >= r.plan.entry, P = r.plan;
      const shares = P && P.r > 0 ? Math.floor(dollars / P.r) : 0;
      const col = r.conf >= 14 ? 'var(--up)' : r.conf >= 11 ? 'var(--gold)' : 'var(--muted)';
      const emas = (r.ema_dist||[]).map(x => `${x>=0?'+':''}${x}`).join(' · ');
      return `<article class="crow" data-jump="${esc(r.t)}" data-side="${esc(r.side)}">
        <span class="cnum">${i+1}</span>
        <div class="cmain">
          <div class="chead"><span class="tk">${esc(r.t)}</span>
            <button class="sizebtn" data-size="${esc(r.t)}-${esc(r.side)}">$ size · ${shares.toLocaleString()} sh</button>
            <span class="muted">${esc(r.industry||r.sector||'')}${r.etf?` · ${esc(r.etf)}`:''}</span></div>
          <div class="cmeta">RVOL ${r.rvol ?? '–'}× on ${pct(r.chg1d)} · EMA ${emas||'–'} · ADR ${r.adr??'–'}% · risk ${(P.risk*100).toFixed(1)}% · stop ${money(P.stop)} · 2R ${money(P.t2)}</div>
          <div class="badges">${r.badges.map(x=>`<span class="b g-${d.groups_of[x]||'method'}">${esc(x)}</span>`).join('')}</div>
        </div>
        <span class="conf" style="--c:${col}">${r.conf}</span>
        ${state.sizer.has(r.t+'-'+r.side) ? sizer(r) : ''}
      </article>`;
    };
    const section = (side, keys) => keys.map(k => {
      const rows = (C[side][k]||[]).map(r => ({...r, side}))
        .filter(r => (!r.rvol || r.rvol >= floor) && !r.badges.some(b => hide.has(b)));
      if(!rows.length) return '';
      return `<h3 style="color:${BUCKETS[k][1]}">${BUCKETS[k][0]}</h3>${rows.map(row).join('')}`;
    }).join('');
    const longs = section('long', ['leading','improving','earnings','other']);
    const shorts = section('short', ['lagging','weakening','earnings','other']);
    const R = d.regime || {};
    const b = d.breadth || {};
    $('#panel').innerHTML = `<h2>Confluence today</h2>
      <div class="ctrls">
        <label>Acct $<input id="acctin" type="number" min="1000" step="1000" value="${A}"></label>
        <label>Risk <input id="riskpctin" type="number" min="0.1" max="5" step="0.1" value="${rp}">%</label>
        <label>RVOL floor <input id="rvolin" type="range" min="0" max="3" step="0.1" value="${floor}"><b>${floor.toFixed(1)}×</b></label>
        <button class="btn" id="tvcopy" title="Watchlist for the FiFi Pivot Watch TradingView script">Copy TradingView list (A/A+)</button>
      </div>
      <div class="chips hides">${['THIN','EXT','ER+','ER-1','9M','UOA'].map(b =>
        `<button class="chip ${hide.has(b)?'out':''}" data-hide="${esc(b)}" title="${hide.has(b)?'Hidden. Tap to show.':'Tap to hide these.'}">${hide.has(b)?'✕ ':''}hide ${esc(b)}</button>`).join('')}</div>
      <p class="regime r-${R.level||'yellow'}"><b>${esc((R.level||'').toUpperCase()||'TAPE')}</b> ${esc(R.text||'')} Breadth ${Math.round((b.above50||0)*100)}% above the 50-day · ${b.new_highs||0} new highs / ${b.new_lows||0} new lows. Sizing ${dollars.toLocaleString()} risk per trade.</p>
      ${longs ? `<h2 class="side up">▲ Long setups</h2>${longs}` : ''}
      ${shorts ? `<h2 class="side down">▼ Short setups</h2>${shorts}` : ''}
      ${(!longs && !shorts) ? `<div class="empty">Nothing cleared the filters tonight. Lower the RVOL floor or check the Longs and Shorts tabs.</div>` : ''}
      ${(d.themes||[]).length ? `<h2>Themes tonight</h2><ul class="themes">${d.themes.map(t=>`<li><b>${esc(t.industry)}</b> · ${t.n} ${t.side==='long'?'longs':'shorts'} · ${t.tickers.map(esc).join(' ')}</li>`).join('')}</ul>` : ''}
      <p class="muted">Score is out of 20: setup quality, relative volume, sector rotation, group strength, whether it is part of a theme, and how tight the stop is. Share counts use your account and risk above. ${(d.prime||[]).length} of these also pass every low-risk test (marked PRIME below the score).</p>`;
  }

  // ---------------------------------------------------------------- RRG
  const QUAD = { Leading:['#00e676','Leading'], Weakening:['#d4af37','Weakening'],
                 Lagging:['#ff5252','Lagging'], Improving:['#4DB6FF','Improving'] };
  function rrgView(){
    const R = state.rrg;
    if(!R || !R.items || !R.items.length){
      $('#panel').innerHTML = `<div class="empty">No rotation data yet. It is written by the nightly scan.</div>`;
      return;
    }
    const pts = R.items.flatMap(i => i.tail);
    const pad = 0.6;
    const lo = Math.min(95, ...pts.map(p=>Math.min(p.x,p.y))) - pad;
    const hi = Math.max(105, ...pts.map(p=>Math.max(p.x,p.y))) + pad;
    const W = 1000, P = 46, S = W - P*2;
    const sx = v => P + (v-lo)/(hi-lo)*S, sy = v => P + (1-(v-lo)/(hi-lo))*S;
    const c100x = sx(100), c100y = sy(100);
    const quadBox = (x,y,w,h,col) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${col}" opacity=".05"/>`;
    const dots = R.items.map(i => {
      const col = QUAD[i.quadrant][0];
      const tail = i.tail.map((p,k) => ({...p, r: 1.6 + 3.2*k/(i.tail.length-1), o: .25 + .75*k/(i.tail.length-1)}));
      const path = tail.map((p,k)=>(k?'L':'M')+sx(p.x).toFixed(1)+' '+sy(p.y).toFixed(1)).join('');
      const last = tail[tail.length-1];
      return `<g class="rrg-item" data-rrg="${esc(i.t)}">
        <path d="${path}" fill="none" stroke="${col}" stroke-width="1.6" opacity=".5"/>
        ${tail.slice(0,-1).map(p=>`<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${p.r.toFixed(1)}" fill="${col}" opacity="${p.o.toFixed(2)}"/>`).join('')}
        <circle cx="${sx(last.x).toFixed(1)}" cy="${sy(last.y).toFixed(1)}" r="7" fill="${col}"/>
        <text x="${(sx(last.x)+11).toFixed(1)}" y="${(sy(last.y)+4).toFixed(1)}" fill="${col}" font-size="15" font-weight="600">${esc(i.t)}</text>
      </g>`;
    }).join('');
    const rows = R.items.map(i => { const l=i.tail[i.tail.length-1], p=i.tail[i.tail.length-2]||l;
      const dir = l.x>=p.x && l.y>=p.y ? 'strengthening' : l.x<p.x && l.y<p.y ? 'weakening' : 'turning';
      return `<tr><td>${esc(i.t)}</td><td>${esc(i.name)}</td><td style="color:${QUAD[i.quadrant][0]}">${i.quadrant}</td><td>${l.x.toFixed(1)}</td><td>${l.y.toFixed(1)}</td><td>${dir}</td></tr>`;
    }).join('');
    $('#panel').innerHTML = `<h2>US sector rotation</h2>
      <p class="muted">The 11 US sectors versus ${esc(R.bench)}, weekly, with a ${R.weeks}-week tail. Right of centre = outperforming; above centre = relative strength still improving. Sectors usually rotate clockwise: Improving to Leading to Weakening to Lagging.</p>
      <div class="rrg"><svg viewBox="0 0 ${W} ${W}" role="img" aria-label="Relative rotation graph">
        ${quadBox(c100x,P,S/2,c100y-P,'#00e676')}${quadBox(c100x,c100y,S/2,S/2,'#d4af37')}
        ${quadBox(P,c100y,c100x-P,S/2,'#ff5252')}${quadBox(P,P,c100x-P,c100y-P,'#4DB6FF')}
        <rect x="${P}" y="${P}" width="${S}" height="${S}" fill="none" stroke="#262626"/>
        <line x1="${c100x}" y1="${P}" x2="${c100x}" y2="${P+S}" stroke="#3a3a3a" stroke-dasharray="4 4"/>
        <line x1="${P}" y1="${c100y}" x2="${P+S}" y2="${c100y}" stroke="#3a3a3a" stroke-dasharray="4 4"/>
        <text x="${P+S-8}" y="${P+16}" fill="#00e676" font-size="14" text-anchor="end">Leading</text>
        <text x="${P+S-8}" y="${P+S-8}" fill="#d4af37" font-size="14" text-anchor="end">Weakening</text>
        <text x="${P+8}" y="${P+S-8}" fill="#ff5252" font-size="14">Lagging</text>
        <text x="${P+8}" y="${P+16}" fill="#4DB6FF" font-size="14">Improving</text>
        <text x="${P+S/2}" y="${P+S+30}" fill="#968f7c" font-size="13" text-anchor="middle">RS-Ratio</text>
        <text x="${P-30}" y="${P+S/2}" fill="#968f7c" font-size="13" text-anchor="middle" transform="rotate(-90 ${P-30} ${P+S/2})">RS-Momentum</text>
        ${dots}
      </svg></div>
      <table><thead><tr><th>ETF</th><th>Sector</th><th>Quadrant</th><th>RS-Ratio</th><th>RS-Mom</th><th>Last week</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="muted">As of ${esc(R.as_of)} weekly close. Longs tend to work best in Leading and Improving sectors; shorts in Lagging and Weakening ones.</p>`;
  }

  function legend(){
    const d = state.data;
    const extra = [['<span class="stage">2A</span>','Stage: 2A/2B early/late uptrend (longs), 4A/4B early/late downtrend (shorts)'],
                   ['<span class="rs">95</span>','RS rank vs every liquid US stock, 1-99. High is good for longs, low for shorts'],
                   ['<span class="seal" style="--c:var(--gold)"><span>A</span></span>','TQE grade: leadership, distance to pivot, tightness, volume dry-up, extension, EMA stack, group strength']];
    $('#legend').innerHTML = Object.entries(d.legend).map(([k,v]) => `<span class="b g-${d.groups_of[k]}">${esc(k)}</span><span>${esc(v)}</span>`).join('')
      + extra.map(([a,b]) => `${a}<span>${b}</span>`).join('');
  }

  function render(){
    header();
    if(state.view==='prime') primeView();
    else if(state.view==='rrg') rrgView();
    else if(state.view==='groups') groupsView();
    else if(state.view==='score') scoreView();
    else { chips(); rows(); }
    legend();
  }

  // ---------------------------------------------------------------- events
  document.addEventListener('click', e => {
    const t = e.target;
    const v = t.closest('[data-view]');
    if(v){ state.view = v.dataset.view; state.filters.clear(); state.industry = null; render(); return; }
    const clr = t.closest('[data-clear]');
    if(clr){ state.filters.clear(); state.industry = null; render(); return; }
    const ind = t.closest('[data-ind]');
    if(ind){ state.industry = ind.dataset.ind || null; if(ind.dataset.side) state.view = ind.dataset.side; state.filters.clear(); render(); return; }
    if(t.closest('#tvcopy')){
      const rows = ['long','short'].flatMap(side => rowsOf(side).filter(r => r.grade==='A+'||r.grade==='A').map(r => ({...r, side})))
        .sort((a,b) => b.score - a.score).slice(0, 40);
      const txt = rows.map(r => `${r.x ? r.x+':' : ''}${r.t.replace('-','.')}:${r.levels.pivot}:${r.side==='long'?'L':'S'}`).join(',');
      const done = () => { t.closest('#tvcopy').textContent = `Copied ${rows.length} names`; setTimeout(()=>{ const b=$('#tvcopy'); if(b) b.textContent='Copy TradingView list (A/A+)'; }, 1800); };
      navigator.clipboard.writeText(txt).then(done, () => prompt('Copy this into FiFi Pivot Watch:', txt));
      return;
    }
    const hd = t.closest('[data-hide]');
    if(hd){
      const set = hidden(), b = hd.dataset.hide;
      set.has(b) ? set.delete(b) : set.add(b);
      try{ localStorage.setItem('fifi_hide', JSON.stringify([...set])); }catch{}
      primeView(); return;
    }
    const sz = t.closest('[data-size]');
    if(sz){ const k = sz.dataset.size; state.sizer.has(k) ? state.sizer.delete(k) : state.sizer.add(k); primeView(); return; }
    if(t.closest('[data-keep]')) return;
    const j = t.closest('[data-jump]');
    if(j){ state.view = j.dataset.side; state.filters.clear(); state.industry = null; state.open.add(j.dataset.jump+j.dataset.side); render();
      requestAnimationFrame(() => document.getElementById('cb-'+j.dataset.jump+'-'+j.dataset.side)?.scrollIntoView({block:'center'})); return; }
    const tab = t.closest('[data-tab]');
    if(tab){ state.tabs[tab.dataset.k] = tab.dataset.tab; rows(); return; }
    const sortBtn = t.closest('[data-sort]');
    if(sortBtn){ state.sort = sortBtn.dataset.sort; document.querySelectorAll('[data-sort]').forEach(b => b.setAttribute('aria-pressed', b===sortBtn)); rows(); return; }
    const chip = t.closest('[data-f]');
    if(chip){                       // off -> require -> exclude -> off
      const f = chip.dataset.f, mode = state.filters.get(f);
      if(!mode) state.filters.set(f, 'in');
      else if(mode === 'in') state.filters.set(f, 'out');
      else state.filters.delete(f);
      chips(); rows(); return;
    }
    const row = t.closest('[data-t]');
    if(row){ const k = row.dataset.t+state.view; state.open.has(k) ? state.open.delete(k) : state.open.add(k); rows(); }
  });

  document.addEventListener('input', e => {
    const f = e.target.dataset && e.target.dataset.sz;
    if(f){
      const k = e.target.dataset.key, cur = state.sizeIn[k] || (state.sizeIn[k] = {});
      if(f === 'pick'){ cur.pick = e.target.value; delete cur.stop; }
      else cur[f] = e.target.value;
      primeView();
      const el = document.querySelector(`[data-sz="${f}"][data-key="${k}"]`);
      if(el){ el.focus(); if(el.setSelectionRange && el.type==='number'){ try{ el.setSelectionRange(el.value.length, el.value.length); }catch{} } }
      return;
    }
    const map = { acctin:'fifi_acct', riskpctin:'fifi_riskpct', rvolin:'fifi_rvol' };
    if(map[e.target.id]){
      try{ localStorage.setItem(map[e.target.id], String(Number(e.target.value) || 0)); }catch{}
      primeView();
    }
  });

  $('#export').addEventListener('click', () => {
    const d = state.data;
    const lists = state.view==='long'||state.view==='short' ? [[state.view, visible()]] : [['long', rowsOf('long')], ['short', rowsOf('short')]];
    const text = lists.map(([side, l]) => `###FiFi ${side==='long'?'Longs':'Shorts'} ${d.as_of}\n` +
      [...l].sort((a,b)=>b.score-a.score).map(tvSym).join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], {type:'text/plain'}));
    a.download = `fifi-${state.view==='long'||state.view==='short'?state.view+'-':''}${d.as_of}.txt`;
    document.body.appendChild(a); a.click(); a.remove();
    $('#export').textContent = 'Exported'; setTimeout(()=>$('#export').textContent='Export to TradingView', 1600);
  });

  $('#copy').addEventListener('click', async () => {
    const d = state.data, side = state.view==='short' ? 'short' : 'long';
    const s = [...rowsOf(side)].sort((a,b)=>b.score-a.score);
    const date = new Date(d.as_of+'T12:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric'});
    const top = s.filter(x=>x.grade==='A+'||x.grade==='A').slice(0,5).map(x=>`$${x.t} (${x.grade})`).join(' ');
    const text = `${side==='long'?'📈':'📉'} FiFi's Dashboard ${side==='long'?'longs':'shorts'}, ${date}\n\n${s.length} stocks passed\n${s.slice(0,20).map(x=>'$'+x.t).join(' ')}` +
      (top ? `\n\nHighest graded: ${top}` : '') + `\n\nOnly qualified trades pass. FiFi's TQE`;
    try{ await navigator.clipboard.writeText(text); $('#copy').textContent='Copied'; }catch{ prompt('Copy the post:', text); }
    setTimeout(()=>$('#copy').textContent='Copy X post', 1600);
  });

  load();
})();
