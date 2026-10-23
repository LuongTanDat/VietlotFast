(() => {
  "use strict";
  const root = document.getElementById("accountStatsSection");
  if (!root) return;
  const el = id => document.getElementById(id);
  function setStatus(message) {
    el('accountStatsStatus').textContent=message;
    el('accountStatsStatus').hidden=!message;
  }
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const number = value => Number(value).toLocaleString("vi-VN", {maximumFractionDigits:0});
  const state = { active:false, period:"all", controller:null, serial:0, report:null, user:"", authenticated:!!currentUser,
    slide:0, rotation:null, paused:false, hovered:false,
    visible:new Set(["deposited","spent","reward","bought","won","previousSpent","previousReward","previousBought","previousWon"]) };
  const moneyLines = [{key:"deposited",label:"Tiền nạp",shortLabel:"Nạp",color:"#38bdf8"},{key:"spent",label:"Tiền Vé",shortLabel:"Vé",color:"#a78bfa"},{key:"reward",label:"Tiền Thưởng",shortLabel:"Thưởng",color:"#34d399"}];
  const ticketLines = [{key:"bought",label:"Vé mua",shortLabel:"Mua",color:"#38bdf8"},{key:"won",label:"Vé trúng",shortLabel:"Trúng",color:"#34d399"}];
  const methods = [{key:'web',label:'Pipeline web',color:'#38bdf8',winColor:'#fb923c'},{key:'random',label:'Ngẫu nhiên',color:'#a78bfa',winColor:'#f472b6'},{key:'bayesian',label:'Bayesian',color:'#fbbf24',winColor:'#fb7185'},{key:'ewma',label:'EWMA',color:'#34d399',winColor:'#a3e635'}];
  const carousel=el('accountStatsCarousel');
  function stopRotation() {clearInterval(state.rotation);state.rotation=null;}
  function startRotation() {
    stopRotation();
    if (!state.active || !state.authenticated || !state.report || state.paused || state.hovered || document.hidden || carousel.contains(document.activeElement)) return;
    state.rotation=setInterval(()=>showSlide(state.slide+1),10000);
  }
  function drawActiveChart() {
    drawChart(state.slide===0 ? 'accountStatsMoneyChart' : 'accountStatsTicketChart',state.slide===0 ? moneyLines : ticketLines);
  }
  function showSlide(index) {
    state.slide=(index+2)%2;
    el('accountStatsMoneyPanel').hidden=state.slide!==0;
    el('accountStatsTicketPanel').hidden=state.slide!==1;
    el('accountStatsSlideLabel').textContent=state.slide===0 ? '1 / 2 · Nguồn Tiền' : '2 / 2 · Nguồn Vé';
    if (state.report) drawActiveChart();
  }
  function drawMethods() {
    const counts=new Map((state.report?.methodDistribution || []).map(row=>[row.method,row.tickets]));
    const outcomes=new Map((state.report?.methodPurchaseOutcomes || []).map(row=>[row.method,row]));
    const rows=methods.map(method=>({...method,count:counts.get(method.key),won:outcomes.get(method.key)?.won,unknown:outcomes.get(method.key)?.unknownTickets,pending:outcomes.get(method.key)?.pending}));
    const total=rows.reduce((sum,row)=>sum+row.count,0);
    const totalWon=rows.reduce((sum,row)=>sum+row.won,0), unknown=rows.reduce((sum,row)=>sum+row.unknown,0);
    const combined=total+totalWon;
    const host=el('accountStatsMethodChart');
    if (![total,totalWon,unknown,combined].every(Number.isSafeInteger) || rows.some(row=>[row.count,row.won,row.unknown,row.pending].some(value=>!Number.isSafeInteger(value) || value<0) || row.won+row.unknown+row.pending>row.count || outcomes.get(row.key)?.tickets!==row.count)) {
      host.innerHTML='<div class="account-stats-empty"><strong>Chưa đọc được tỷ lệ vé</strong></div>';
      return;
    }
    if (!total && !totalWon && !unknown) {
      host.innerHTML='<div class="account-stats-empty"><span aria-hidden="true">◯</span><strong>Chưa có vé trong khoảng này</strong></div>';
      return;
    }
    const pending=rows.reduce((sum,row)=>sum+row.pending,0), incomplete=unknown+pending>0;
    const detail=row=>`${row.label} · Vé trúng: ${number(row.won)} · ${row.wonPercent} tổng Vé mua + Vé trúng · ${number(row.pending)} vé chờ kết quả · ${number(row.unknown)} vé chưa phân loại`;
    rows.forEach(row=>{
      row.countPercent=combined>0 ? (row.count/combined*100).toLocaleString('vi-VN',{maximumFractionDigits:2})+'%' : '—';
      row.wonPercent=combined>0 ? (row.won/combined*100).toLocaleString('vi-VN',{maximumFractionDigits:2})+'%' : '—';
    });
    let offset=0;
    const sectors=`<g data-ring="tickets" aria-label="8 phần: Vé mua và Vé trúng của bốn phương pháp"><circle class="account-stats-pie-track" cx="120" cy="120" r="90"/>${rows.flatMap(row=>['count','won'].map(key=>{
      const share=row[key]/combined*100, color=key==='count' ? row.color : row.winColor;
      const title=key==='won' ? detail(row) : `${row.label} · Vé mua: ${number(row.count)} · ${row.countPercent} tổng Vé mua + Vé trúng`;
      const markup=row[key]>0 ? `<circle class="account-stats-pie-sector" tabindex="0" data-method="${row.key}" data-kind="${key}" cx="120" cy="120" r="90" pathLength="100" stroke="${color}" stroke-dasharray="${share} ${100-share}" stroke-dashoffset="${-offset}" transform="rotate(-90 120 120)"><title>${title}</title></circle>` : '';
      offset+=share;
      return markup;
    })).join('')}</g>`;
    const totalSize=Math.min(18,105/Math.max(1,number(total).length)*1.65);
    const wonSize=Math.min(14,105/Math.max(1,number(totalWon).length)*1.65);
    host.innerHTML=`<div class="account-stats-donut"><svg viewBox="0 0 240 240" role="img" aria-label="Pie một vòng với tám màu: Vé mua và Vé trúng của từng phương pháp"><title>Tỷ trọng trên tổng giá trị 8 nhóm = Vé mua + Vé trúng. Vé trúng nằm trong vé mua. Vé mua: ${number(total)} · Vé trúng: ${number(totalWon)} · ${number(pending)} vé chờ · ${number(unknown)} vé chưa phân loại</title>${sectors}<text x="120" y="96" class="account-stats-donut-label" text-anchor="middle">Vé mua</text><text x="120" y="116" class="account-stats-donut-total" text-anchor="middle" style="font-size:${totalSize}px">${number(total)}</text><text x="120" y="137" class="account-stats-donut-label" text-anchor="middle">Vé trúng${incomplete ? ' *' : ''}</text><text x="120" y="155" class="account-stats-donut-won" text-anchor="middle" style="font-size:${wonSize}px">${number(totalWon)}</text></svg></div><div class="account-stats-method-breakdown"><div class="account-stats-method-columns"><span>Phương pháp</span><span>Vé mua</span><span>Vé trúng</span></div><ul class="account-stats-method-legend">${rows.map(row=>`<li data-method="${row.key}"><span class="account-stats-method-name">${row.label}</span><span class="account-stats-method-value" title="${row.label} · Vé mua: ${number(row.count)} · ${row.countPercent} tổng Vé mua + Vé trúng"><strong><i style="background:${row.color}"></i>${row.countPercent}</strong><small>${number(row.count)}</small></span><span class="account-stats-method-value" title="${detail(row)}"><strong><i style="background:${row.winColor}"></i>${row.wonPercent}${row.unknown+row.pending>0 ? ' *' : ''}</strong><small>${number(row.won)}</small></span></li>`).join('')}</ul></div>`;
  }
  function today() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {timeZone:"Asia/Ho_Chi_Minh",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date()).map(part=>[part.type,part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }
  function syncControls() {
    root.querySelectorAll("[data-account-period]").forEach(button=>button.setAttribute("aria-pressed", String(state.period===button.dataset.accountPeriod)));
    el("accountStatsDate").disabled = state.period === "all";
    el("accountStatsLevelLabel").hidden = el("accountStatsGame").value !== "KENO";
  }
  function label(key) {
    if (key.includes("T")) return `${key.slice(11,13)}h`;
    if (key.length===7) return `${key.slice(5,7)}/${key.slice(0,4)}`;
    return `${key.slice(8,10)}/${key.slice(5,7)}`;
  }
  function compact(value) {
    if (value>=1e9) return `${(value/1e9).toLocaleString("vi-VN",{maximumFractionDigits:1})} tỷ`;
    if (value>=1e6) return `${(value/1e6).toLocaleString("vi-VN",{maximumFractionDigits:1})} tr`;
    if (value>=1e3) return `${(value/1e3).toLocaleString("vi-VN",{maximumFractionDigits:1})}k`;
    return number(value);
  }
  function chartValue(row,key) {
    const value=row[key];
    if (!Number.isSafeInteger(value) || value<0) return null;
    return value;
  }
  function partialValue(row,key) {
    return ((key==='reward'||key==='won') && row.drawPending>0) || (key==='reward' && row.incomplete>0) || (key==='won' && row.unknownTickets>0);
  }
  function valueNote(row,key) {
    if (row.future && row[key]===0) return 'Chưa tới thời điểm này; hiển thị 0 theo dữ liệu hiện có';
    if ((key==='reward' || key==='won') && !row.scored) return row.drawPending ? `Chờ chấm kết quả ${number(row.drawPending)} vé` : 'Chưa có kết quả đã chấm';
    const pending=row.drawPending ? ` · Chờ chấm thêm ${number(row.drawPending)} vé` : '';
    if (key==='reward' && row.incomplete) return `Tạm tính: đã biết ${number(row.reward)} ₫; còn ${number(row.incomplete)} kỳ thiếu mức thưởng${pending}`;
    if (key==='won' && row.unknownTickets) return `Đã xác định ${number(row.won)} vé trúng; còn ${number(row.unknownTickets)} vé chưa phân loại${pending}`;
    if ((key==='reward'||key==='won') && row.drawPending) return `Tạm tính trên ${number(row.scored)} vé đã chấm${pending}`;
    return '';
  }
  function drawChart(hostId, lines) {
    const report=state.report, series=report?.series || [], host=el(hostId);
    if (Array.isArray(report?.comparison?.series)) {
      const previousLabel={day:'ngày trước',week:'tuần trước',month:'tháng trước',year:'năm trước'}[report.period];
      const previousLines=hostId==='accountStatsMoneyChart'
        ? [{key:'previousSpent',metric:'spent',label:`Tiền Vé · ${previousLabel}`,shortLabel:'Vé trước',color:'#818cf8',previous:true},
          {key:'previousReward',metric:'reward',label:`Tiền Thưởng · ${previousLabel}`,shortLabel:'Thưởng trước',color:'#2dd4bf',previous:true}]
        : [{key:'previousBought',metric:'bought',label:`Vé mua · ${previousLabel}`,shortLabel:'Mua trước',color:'#818cf8',previous:true},
          {key:'previousWon',metric:'won',label:`Vé trúng · ${previousLabel}`,shortLabel:'Trúng trước',color:'#2dd4bf',previous:true}];
      lines=[...lines,...previousLines];
    }
    const sourceRow=(item,index)=>item.previous ? report.comparison.series[index] : series[index];
    const lineValue=(item,index)=>{const row=sourceRow(item,index);return row ? chartValue(row,item.metric || item.key) : null;};
    const shown=lines.filter(item=>state.visible.has(item.key));
    const legendButton=item=>`<button type="button"${item.previous ? ' class="is-previous"' : ''} data-account-line="${item.key}" title="${escape(item.label)}" aria-label="${escape(item.label)}" aria-pressed="${state.visible.has(item.key)}"><i aria-hidden="true" style="${item.previous ? '--as-series-color:' : 'background:'}${item.color}"></i>${item.shortLabel || item.label}</button>`;
    el(hostId+'Legend').innerHTML=[false,true].map(previous=>{
      const group=lines.filter(item=>!!item.previous===previous);
      return group.length ? `<span class="account-stats-legend-group" role="group" aria-label="${previous ? 'Kỳ trước' : 'Hiện tại'}">${group.map(legendButton).join('')}</span>` : '';
    }).join('');
    if (!series.length || !series.some((row,index)=>lines.some(item=>lineValue(item,index)!==null))) {
      const message=series.length && series.every(row=>row.future) ? 'Chưa tới khoảng thời gian này' : series.some(row=>row.drawPending>0) ? 'Đang chờ kết quả chấm điểm' : 'Chưa có dữ liệu trong khoảng này';
      host.innerHTML=`<div class="account-stats-empty"><span aria-hidden="true">▥</span><strong>${message}</strong><p>Chọn khoảng thời gian khác hoặc làm mới sau khi có giao dịch/kết quả.</p></div>`;
      return;
    }
    const w=Math.max(1,host.clientWidth),h=240,fullWeek=report.period==='week',staggerWeek=fullWeek && w<450;
    const p={left:66,right:20,top:20,bottom:staggerWeek ? 52 : 36};
    let max=Math.max(4,...series.flatMap((row,index)=>shown.map(item=>lineValue(item,index) ?? 0)));
    const power=10**Math.floor(Math.log10(max)); max=Math.ceil(max/power)*power;
    const x=i=>p.left+(series.length===1 ? .5 : i/(series.length-1))*(w-p.left-p.right), y=value=>h-p.bottom-value/max*(h-p.top-p.bottom);
    const grid=Array.from({length:5},(_,i)=>{const value=max*i/4;return `<line x1="${p.left}" x2="${w-p.right}" y1="${y(value)}" y2="${y(value)}"/><text x="${p.left-12}" y="${y(value)+4}" text-anchor="end">${escape(compact(value))}</text>`;}).join("");
    const tickCount=fullWeek ? series.length : Math.min(series.length,w<450 ? 3 : 6);
    const ticks=[...new Set(Array.from({length:tickCount},(_,i)=>Math.round(i*(series.length-1)/Math.max(1,tickCount-1))))];
    const paths=shown.map(item=>{
      let path="",connected=false;
      const dots=series.map((currentRow,i)=>{
        const row=sourceRow(item,i),value=lineValue(item,i),metric=item.metric || item.key;
        if (value===null) {connected=false;return "";}
        const note=valueNote(row,metric), partial=partialValue(row,metric);
        path+=`${connected ? " L" : " M"}${x(i)},${y(value)}`;connected=true;
        return `<circle tabindex="0" data-key="${row.key}" data-metric="${item.key}" cx="${x(i)}" cy="${y(value)}" r="${item.previous ? 2.8 : 3.6}" fill="${item.color}"><title>${escape(`${row.key} · ${item.label}: ${number(value)}${hostId.includes("Money") ? ' ₫' : ' vé'}${partial ? ' *' : ''}${note ? ' · '+note : ''}`)}</title></circle>`;
      }).join("");
      return `<path data-line="${item.key}" d="${path}" stroke="${item.color}"${item.previous ? ' stroke-dasharray="6 4"' : ''}/>${dots}`;
    }).join("");
    const axis=ticks.map(i=>`<text class="${series[i].future ? 'is-future' : ''}"${series[i].future ? ` aria-label="${escape(label(series[i].key))} · Chưa tới thời điểm này"` : ''} x="${x(i)}" y="${staggerWeek ? h-25+(i%2)*16 : h-14}" text-anchor="middle">${escape(label(series[i].key))}</text>`).join("");
    host.innerHTML=`<div class="account-stats-svg"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${hostId.includes('Money') ? 'Biểu đồ tiền nạp thực và chi phí, thưởng mô phỏng' : 'Biểu đồ số vé mô phỏng đã khóa và số vé trúng'}"><g class="account-stats-grid">${grid}</g><g class="account-stats-lines">${paths}</g><g class="account-stats-axis">${axis}</g></svg></div>`;
  }
  function render(report) {
    const t=report.totals;
    const futureOnly=report.series.length>0 && report.series.every(row=>row.future) && !t.bought && !t.scored && !t.deposited;
    const cardValue=(key,money=false)=>number(t[key])+(money ? ' ₫' : '');
    const comparison=report.comparison;
    const compareLabel={day:report.anchor===today() ? 'hôm qua' : 'ngày trước',week:'tuần trước',month:'tháng trước',year:'năm trước'}[report.period];
    const changeMarkup=key=>{
      if (!comparison || !compareLabel || futureOnly || ((key==='reward'||key==='won') && cardValue(key)==='—')) return '';
      const value=comparison.changes[key], money=['deposited','spent','reward'].includes(key);
      const valid=Number.isSafeInteger(value);
      const estimated=valid && key==='reward' && comparison.estimated?.reward===true;
      const text=valid ? `${value>0 ? '+' : value<0 ? '−' : ''}${number(Math.abs(value))}${money ? ' ₫' : ' vé'}${estimated ? ' *' : ''}` : 'Chưa đủ dữ liệu';
      const tone=valid ? value>0 ? 'up' : value<0 ? 'down' : 'flat' : 'unavailable';
      const end=new Date(Date.parse(comparison.until+'T00:00:00Z')-86400000).toISOString().slice(0,10);
      const detail=estimated ? ` · Tạm tính theo tổng thưởng đã tính: kỳ đang xem ${number(t.reward)} ₫; kỳ trước ${number(comparison.totals.reward)} ₫. Còn ${number(t.incomplete)} / ${number(comparison.totals.incomplete)} kỳ thiếu mức thưởng, chưa cộng phần chưa xác định.` : valid ? '' : ' · Chưa đủ dữ liệu để so sánh';
      return `<div class="account-stats-change is-${tone}${estimated ? ' is-estimated' : ''}" style="--as-change-length:${text.length+compareLabel.length+2}" title="${escape(`${comparison.from} → ${end} · Giờ Việt Nam${detail}`)}"><b>${escape(text)}</b><span>${compareLabel}</span></div>`;
    };
    const cards=[
      ["Tiền nạp",cardValue('deposited',true),"blue","deposited"],
      ["Tiền Vé",cardValue('spent',true),"purple","spent"],
      ["Tiền Thưởng",cardValue('reward',true),"green","reward"],
      ["Vé mua",cardValue('bought'),'blue','bought'],
      ["Vé trúng",cardValue('won'),'green','won'],
    ];
    el("accountStatsCards").innerHTML=cards.map(([name,value,color,key])=>`<article class="account-stats-kpi is-${color}" style="--as-value-length:${value.length}"><span>${name}</span><strong>${escape(value)}</strong>${changeMarkup(key)}</article>`).join("");
    const classified=t.scored-t.unknownTickets;
    el("accountStatsWinRate").textContent=classified>0 ? `Tỉ Lệ: ${(100*t.won/classified).toLocaleString('vi-VN',{maximumFractionDigits:2})}%` : "Tỉ Lệ: —";
    drawActiveChart();drawMethods();startRotation();
    el("accountStatsRows").innerHTML=report.series.length ? report.series.map(row=>`<tr><th scope="row">${escape(row.key.replace('T',' '))}</th>${['deposited','spent','reward','bought','won'].map(key=>{const value=chartValue(row,key),note=valueNote(row,key),partial=partialValue(row,key);return `<td><span${note ? ` title="${escape(note)}"` : ''}>${value===null ? '—' : number(value)+(partial ? ' *' : '')}</span></td>`;}).join('')}</tr>`).join('') : '<tr><td colspan="6">Chưa có dữ liệu.</td></tr>';
    setStatus(report.warnings?.join(' ') || '');
  }
  function clear() {
    stopRotation();
    state.report=null;
    ['accountStatsCards','accountStatsMoneyChart','accountStatsTicketChart','accountStatsMethodChart','accountStatsMoneyChartLegend','accountStatsTicketChartLegend','accountStatsRows'].forEach(id=>el(id).innerHTML='');
    el("accountStatsWinRate").textContent='Tỉ Lệ: —';
  }
  async function refresh() {
    if (!state.active || !state.authenticated || !currentUser) return;
    state.controller?.abort();
    stopRotation();
    const controller=new AbortController(), serial=++state.serial, user=currentUser;
    state.controller=controller;state.user=user;
    const timeout=setTimeout(()=>controller.abort(),35000);
    root.setAttribute('aria-busy','true');
    setStatus("Đang tải thống kê…");
    const params=new URLSearchParams({type:el('accountStatsGame').value,method:el('accountStatsMethod').value,period:state.period,date:el('accountStatsDate').value,level:el('accountStatsLevel').value});
    try {
      const response=await fetch('/api/account/statistics?'+params,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      const report=await response.json();
      if (serial!==state.serial || !state.active || !state.authenticated || currentUser!==user) return;
      if (!response.ok || report.ok!==true) throw new Error(report.message || 'Chưa tải được thống kê.');
      if (report.owner!==user || report.type!==params.get('type') || report.method!==params.get('method') || report.period!==params.get('period') || String(report.level)!==params.get('level') || report.anchor!==params.get('date')) throw new Error('Dữ liệu thống kê không khớp lựa chọn. Hãy làm mới.');
      state.report=report;render(report);
    } catch(error) {
      if (serial!==state.serial || !state.active || currentUser!==user) return;
      clear();setStatus(error.name==='AbortError' ? 'Tải quá thời gian chờ. Bấm Làm mới để thử lại.' : error.message);
    } finally {
      clearTimeout(timeout);
      if (serial===state.serial) {state.controller=null;root.setAttribute('aria-busy','false');}
    }
  }
  function stop() {stopRotation();state.serial++;state.controller?.abort();state.controller=null;root.setAttribute('aria-busy','false');}
  el('accountStatsDate').value=today();syncControls();
  let chartResizeFrame=0;
  const chartWidths=new Map();
  const chartResize=new ResizeObserver(entries=>{
    let changed=false;
    for (const entry of entries) {
      const width=Math.round(entry.contentRect.width);
      if (width!==chartWidths.get(entry.target.id)) {chartWidths.set(entry.target.id,width);changed=true;}
    }
    if (!changed || !state.active || !state.report) return;
    cancelAnimationFrame(chartResizeFrame);
    chartResizeFrame=requestAnimationFrame(()=>{
      if (!state.active || !state.report) return;
      drawActiveChart();
    });
  });
  ['accountStatsMoneyChart','accountStatsTicketChart'].forEach(id=>chartResize.observe(el(id)));
  el('accountStatsPrevious').onclick=()=>{showSlide(state.slide-1);startRotation();};
  el('accountStatsNext').onclick=()=>{showSlide(state.slide+1);startRotation();};
  el('accountStatsRotation').onclick=()=>{
    state.paused=!state.paused;
    const button=el('accountStatsRotation');
    button.textContent=state.paused ? '▶' : 'Ⅱ';
    button.setAttribute('aria-pressed',String(state.paused));
    button.setAttribute('aria-label',state.paused ? 'Bật tự chuyển biểu đồ' : 'Tạm dừng tự chuyển biểu đồ');
    startRotation();
  };
  carousel.addEventListener('pointerenter',()=>{state.hovered=true;stopRotation();});
  carousel.addEventListener('pointerleave',()=>{state.hovered=false;startRotation();});
  carousel.addEventListener('focusin',stopRotation);
  carousel.addEventListener('focusout',()=>queueMicrotask(startRotation));
  document.addEventListener('visibilitychange',startRotation);
  el('accountStatsRefresh').onclick=refresh;
  ['accountStatsDate','accountStatsGame','accountStatsMethod','accountStatsLevel'].forEach(id=>el(id).addEventListener('change',()=>{syncControls();clear();void refresh();}));
  root.addEventListener('click',event=>{
    const period=event.target.closest('[data-account-period]');
    if (period) {state.period=period.dataset.accountPeriod;syncControls();clear();void refresh();return;}
    const line=event.target.closest('[data-account-line]');
    if (line && state.report) {const key=line.dataset.accountLine;state.visible.has(key) ? state.visible.delete(key) : state.visible.add(key);drawActiveChart();root.querySelector(`[data-account-line="${key}"]`)?.focus({preventScroll:true});}
  });
  window.VietlottAccountStats=Object.freeze({activate(active){const changed=state.active!==active;state.active=active;if(!active) stop();else if(changed) void refresh();}});
  window.addEventListener('dvlf:auth-changed',event=>{
    stop();clear();state.authenticated=event.detail?.authenticated===true;state.user=event.detail?.user || '';
    setStatus(state.authenticated ? '' : 'Đăng nhập để xem thống kê.');
    if(state.active&&state.authenticated) void refresh();
  });
  window.VietlottAccountStats.activate(location.pathname==='/bieu-do');
})();
