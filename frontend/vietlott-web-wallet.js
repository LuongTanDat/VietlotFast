(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const dialog = el("walletHistoryDialog");
  if (!dialog) return;
  const state = {view:"wallet",kind:"all", page:1, pages:1, controller:null, serial:0};
  const cardState = {kind:"all",page:1,pages:1,history:false,loaded:false,accountId:"",balance:"0",walletBalance:"0",currency:"PayPal"};
  const transfer = {kind:"topup",busy:false,serial:0,attempt:null,percent:null};
  const cardKinds = {transfer:"Chuyển",topup:"Nạp",withdraw:"Rút",reward:"Thưởng",interest:"Lãi suất"};
  const kinds = {topup:"Nạp tiền", spend:"Chi tiêu", reward:"Trúng thưởng", refund:"Hoàn tiền", other:"Khác"};
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const number = value => BigInt(value).toLocaleString("vi-VN");
  const date = value => {
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return "—";
    return parsed.toLocaleString("vi-VN", {timeZone:"Asia/Ho_Chi_Minh",hour:"2-digit",minute:"2-digit",second:"2-digit",day:"2-digit",month:"2-digit",year:"numeric"});
  };
  function stop() { state.serial++; state.controller?.abort(); state.controller=null; }
  function clear() {
    el("walletHistoryRows").replaceChildren();
    el("walletHistoryBalance").textContent="—";
    el("walletHistoryCount").textContent="";
    el("walletHistoryPage").textContent="—";
    el("walletHistoryPrev").disabled=el("walletHistoryNext").disabled=true;
  }
  function render(report) {
    state.page=report.page; state.pages=report.pages;
    el("walletHistoryBalance").textContent=number(report.balance);
    window.dispatchEvent(new CustomEvent('dvlf:prediction-wallet', {detail:{owner:report.owner,balance:report.balance,walletVersion:report.walletVersion}}));
    el("walletHistoryRows").innerHTML=report.events.map(row=>{
      const delta=row.delta===null ? null : BigInt(row.delta), diamond=BigInt(row.diamondDelta);
      const amount=delta===null ? "—" : `${delta>0n ? "+" : delta<0n ? "−" : ""}${number(delta<0n ? -delta : delta)}`;
      const tone=delta>0n ? "is-credit" : delta<0n ? "is-debit" : "";
      return `<tr><td data-label="Thời gian"><time datetime="${escape(row.createdAt)}">${escape(date(row.createdAt))}</time></td><td class="wallet-history-detail"><strong>${escape(row.label)}</strong>${row.description ? `<small>${escape(row.description)}</small>` : ""}${row.reference ? `<small class="wallet-history-reference" title="${escape(row.reference)}">Mã: ${escape(row.reference)}</small>` : ""}</td><td data-label="Loại"><span class="wallet-history-kind is-${escape(row.kind)}">${escape(kinds[row.kind] || "Khác")}</span></td><td data-label="PayPal" class="wallet-history-amount ${tone}"${delta===null ? ' title="Giao dịch cũ chưa lưu mức thay đổi số dư"' : ""}><strong>${amount}</strong>${diamond!==0n ? `<small>${diamond>0n ? "+" : "−"}${number(diamond<0n ? -diamond : diamond)} kim cương</small>` : ""}</td></tr>`;
    }).join("");
    el("walletHistoryCount").textContent=`${number(report.total)} giao dịch`;
    el("walletHistoryPage").textContent=`${number(state.page)} / ${number(state.pages)}`;
    el("walletHistoryPrev").disabled=state.page<=1;
    el("walletHistoryNext").disabled=state.page>=state.pages;
    el("walletHistoryStatus").textContent=report.events.length ? "" : "Chưa có giao dịch trong mục này.";
  }
  async function load() {
    if (!dialog.open || !currentUser || state.view!=="wallet") return;
    stop(); clear();
    const serial=state.serial, owner=currentUser, kind=state.kind;
    const controller=new AbortController(); state.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),15000);
    el("walletHistoryTable").setAttribute("aria-busy","true");
    el("walletHistoryStatus").textContent="Đang tải lịch sử…";
    try {
      const response=await fetch(`/api/account/wallet-history?${new URLSearchParams({kind,page:state.page})}`, {credentials:"same-origin",cache:"no-store",signal:controller.signal});
      const report=await response.json();
      if (serial!==state.serial || !dialog.open || currentUser!==owner) return;
      if (!response.ok || report.ok!==true) throw new Error(report.message || "Chưa tải được lịch sử ví.");
      if (report.owner!==owner || report.kind!==kind || !Array.isArray(report.events)) throw new Error("Dữ liệu không khớp tài khoản. Hãy làm mới.");
      render(report);
    } catch(error) {
      if (serial!==state.serial || !dialog.open || currentUser!==owner) return;
      clear();
      el("walletHistoryStatus").textContent=error.name==="AbortError" ? "Tải quá thời gian chờ. Bấm Làm mới để thử lại." : error.message;
    } finally {
      clearTimeout(timeout);
      if (serial===state.serial) { state.controller=null; el("walletHistoryTable").setAttribute("aria-busy","false"); }
    }
  }
  function openHistory(view="wallet") {
    if (!currentUser || transfer.busy) return;
    if (typeof closeHeaderPopovers==="function") closeHeaderPopovers();
    state.kind="all"; state.page=1;
    el("walletHistoryFilters").querySelectorAll("button").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.walletKind==="all")));
    cardState.kind="all";cardState.page=1;cardState.history=view==="card";
    el("accountCardHistory").hidden=!cardState.history;el("accountCardHistoryToggle").setAttribute("aria-expanded",String(cardState.history));
    el("cardHistoryFilters").querySelectorAll("button").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.cardKind==="all")));
    if (!dialog.open) dialog.showModal(); selectView(view,view==="card");
  }
  el("walletHistoryOpen").addEventListener("click",()=>openHistory());
  window.VietlottAccountHistory=Object.freeze({open:openHistory});
  el("walletHistoryClose").addEventListener("click",()=>dialog.close());
  dialog.addEventListener("close",()=>{if(dialog.open) return;stop();clear();clearCard();el("walletHistoryStatus").textContent="";el("walletHistoryTable").setAttribute("aria-busy","false");});
  dialog.addEventListener("click",event=>{if(event.target===dialog) {const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left || event.clientX>rect.right || event.clientY<rect.top || event.clientY>rect.bottom) dialog.close();}});
  el("walletHistoryFilters").addEventListener("click",event=>{
    const button=event.target.closest("[data-wallet-kind]"); if(!button) return;
    state.kind=button.dataset.walletKind; state.page=1;
    el("walletHistoryFilters").querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));
    void load();
  });
  el("walletHistoryRefresh").addEventListener("click",()=>void load());
  el("walletHistoryPrev").addEventListener("click",()=>{if(state.page>1) {state.page--;void load();}});
  el("walletHistoryNext").addEventListener("click",()=>{if(state.page<state.pages) {state.page++;void load();}});
  function clearCard() {
    closeCardActions();cardState.loaded=false;cardState.accountId="";cardState.balance=cardState.walletBalance="0";updateTransfer();
    ["accountCardBalance","accountCardId","accountCardHolder"].forEach(id=>el(id).textContent="—");
    el("cardHistoryRows").replaceChildren();el("cardHistoryCount").textContent="";el("cardHistoryPage").textContent="—";
    el("cardHistoryPrev").disabled=el("cardHistoryNext").disabled=true;
    el("accountCardStatus").textContent=el("cardHistoryStatus").textContent="";
    el("cardHistoryTable").setAttribute("aria-busy","false");
  }
  async function loadCard() {
    if (!dialog.open || !currentUser || state.view!=="card") return;
    stop();
    cardState.loaded=false;updateTransfer();
    const serial=state.serial,owner=currentUser,controller=new AbortController();state.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),15000);
    el("accountCardStatus").textContent="Đang tải thẻ…";
    el("cardHistoryRows").replaceChildren();el("cardHistoryPrev").disabled=el("cardHistoryNext").disabled=true;
    el("cardHistoryTable").setAttribute("aria-busy","true");
    try {
      const response=await fetch(`/api/account/card?${new URLSearchParams({kind:cardState.kind,page:cardState.page,history:cardState.history?"1":"0"})}`,{credentials:"same-origin",cache:"no-store",signal:controller.signal});
      const report=await response.json();
      if (serial!==state.serial || !dialog.open || currentUser!==owner) return;
      if (!response.ok || report.ok!==true) throw new Error(report.message || "Chưa tải được thẻ.");
      if(report.owner!==owner || report.kind!==cardState.kind || report.card?.holder!==owner || !Array.isArray(report.events)) throw new Error("Thông tin thẻ không khớp tài khoản.");
      const card=report.card;
      Object.assign(cardState,{loaded:true,accountId:card.accountId,balance:card.balance,walletBalance:report.walletBalance,currency:card.currency});
      el("accountCardBalance").textContent=number(card.balance);el("accountCardCurrency").textContent=card.currency;
      el("accountCardId").textContent=card.accountId;el("accountCardHolder").textContent=card.holder;
      el("accountCardStatus").textContent="";el("cardHistoryAmountTitle").textContent=`Số tiền ${card.currency}`;
      cardState.page=report.page;cardState.pages=report.pages;
      el("cardHistoryRows").innerHTML=report.events.map(row=>{
        const amount=BigInt(row.delta),tone=amount>0n?"is-credit":amount<0n?"is-debit":"";
        return `<tr><td><time datetime="${escape(row.createdAt)}">${escape(date(row.createdAt))}</time></td><td class="wallet-history-detail"><strong>${escape(row.label)}</strong><small>${escape(row.description)}</small>${row.reference?`<small class="wallet-history-reference" title="${escape(row.reference)}">Mã: ${escape(row.reference)}</small>`:""}</td><td><span class="wallet-history-kind is-${escape(row.kind)}">${escape(cardKinds[row.kind]||row.kind)}</span></td><td class="wallet-history-amount ${tone}"><strong>${amount>0n?"+":amount<0n?"−":""}${number(amount<0n?-amount:amount)}</strong></td></tr>`;
      }).join("");
      el("cardHistoryCount").textContent=`${number(report.total)} giao dịch`;el("cardHistoryPage").textContent=`${number(report.page)} / ${number(report.pages)}`;
      el("cardHistoryPrev").disabled=report.page<=1;el("cardHistoryNext").disabled=report.page>=report.pages;
      el("cardHistoryStatus").textContent=cardState.history && !report.events.length?"Chưa có giao dịch thẻ trong mục này.":"";
      updateTransfer();
      window.dispatchEvent(new CustomEvent('dvlf:prediction-wallet',{detail:{owner,balance:Number(report.walletBalance),walletVersion:report.walletVersion}}));
    } catch(error) {
      if(serial!==state.serial || !dialog.open || currentUser!==owner) return;
      clearCard();el("accountCardStatus").textContent=error.name==="AbortError"?"Tải quá thời gian chờ. Hãy thử lại.":error.message;
    } finally {
      clearTimeout(timeout);
      if(serial===state.serial){state.controller=null;el("cardHistoryTable").setAttribute("aria-busy","false");}
    }
  }
  function transferStatus(message,tone="") {
    el("cardTransferStatus").textContent=message;
    el("cardTransferStatus").className=`card-transfer-status${tone?` is-${tone}`:""}`;
  }
  function pendingTransfer() {
    const id=cardState.accountId;
    if(transfer.attempt?.accountId===id) return transfer.attempt;
    try {
      const saved=JSON.parse(sessionStorage.getItem(`dvlf:card-transfer:${id}`));
      if(saved?.accountId===id && ["topup","withdraw"].includes(saved.kind) && /^[a-f0-9]{32}$/.test(saved.requestId) && /^[1-9][0-9]{0,15}$/.test(saved.amount) && BigInt(saved.amount)<=9007199254740991n) return saved;
    } catch(_) { /* Retry remains available in memory if browser storage is disabled. */ }
    return null;
  }
  function saveTransfer(attempt) {
    transfer.attempt=attempt;
    try { sessionStorage.setItem(`dvlf:card-transfer:${attempt.accountId}`,JSON.stringify(attempt)); } catch(_) {}
  }
  function forgetTransfer(attempt) {
    if(transfer.attempt?.requestId===attempt.requestId) transfer.attempt=null;
    try { sessionStorage.removeItem(`dvlf:card-transfer:${attempt.accountId}`); } catch(_) {}
  }
  function updateTransfer() {
    const disabled=!cardState.loaded || cardState.currency!=="PayPal" || transfer.busy;
    const pending=pendingTransfer();
    el("accountCardTopup").disabled=el("accountCardWithdraw").disabled=disabled;
    el("accountCardHistoryToggle").disabled=transfer.busy;
    el("cardTransferSubmit").disabled=disabled;
    el("cardTransferCancel").disabled=transfer.busy;
    el("cardTransferAmount").readOnly=transfer.busy || !!pending;
    normalizeTransferInput();
    const topup=transfer.kind==="topup";
    const available=cardState.loaded?BigInt(topup?cardState.walletBalance:cardState.balance):0n;
    el("cardTransferPresets").querySelectorAll("button").forEach(button=>{
      const percent=button.dataset.transferPercent,amount=available>0n?available*BigInt(percent)/100n:0n;
      button.disabled=disabled || !!pending || amount===0n;
      button.setAttribute("aria-pressed",String(transfer.percent===percent && amount>0n && el("cardTransferAmount").value===number(amount)));
      button.title=`${number(amount)} PayPal`;
      button.setAttribute("aria-label",`${percent}% số dư ${topup?"ví":"thẻ"}: ${number(amount)} PayPal`);
    });
    el("cardTransferTitle").textContent=topup?"Nạp thẻ từ ví":"Rút thẻ về ví";
    el("cardTransferDirection").textContent=topup?"Ví → Thẻ · 1:1 PayPal":"Thẻ → Ví · 1:1 PayPal";
    el("cardTransferAvailable").textContent=cardState.loaded?`${topup?"Số dư ví":"Số dư thẻ"}: ${number(topup?cardState.walletBalance:cardState.balance)} PayPal`:"Đang kiểm tra số dư…";
    el("cardTransferSubmit").textContent=transfer.busy?"Đang xử lý…":pendingTransfer()?"Kiểm tra giao dịch":topup?"Xác nhận nạp":"Xác nhận rút";
  }
  function closeTransfer() {
    transfer.serial++;transfer.busy=false;transfer.percent=null;
    el("accountCardTransfer").hidden=true;el("cardTransferAmount").value="";
    el("accountCardTopup").setAttribute("aria-expanded","false");el("accountCardWithdraw").setAttribute("aria-expanded","false");
    transferStatus("");
  }
  function closeCardActions() {
    closeTransfer();cardState.history=false;
    el("accountCardHistory").hidden=true;el("accountCardHistoryToggle").setAttribute("aria-expanded","false");
  }
  function openTransfer(kind) {
    if(!cardState.loaded || transfer.busy || cardState.currency!=="PayPal") return;
    const pending=pendingTransfer();
    cardState.history=false;el("accountCardHistory").hidden=true;el("accountCardHistoryToggle").setAttribute("aria-expanded","false");
    transfer.kind=pending?.kind || kind;transfer.percent=null;
    el("accountCardTransfer").hidden=false;
    el("accountCardTopup").setAttribute("aria-expanded",String(transfer.kind==="topup"));el("accountCardWithdraw").setAttribute("aria-expanded",String(transfer.kind==="withdraw"));
    el("cardTransferAmount").value=pending?number(pending.amount):"";
    transferStatus(pending?"Giao dịch trước chưa có kết quả. Bấm Kiểm tra giao dịch để xác nhận lại.":"");
    updateTransfer();el("cardTransferAmount").focus();
  }
  function transferAmount() {
    const raw=el("cardTransferAmount").value.trim();
    if(!/^(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)$/.test(raw)) throw new Error("Nhập số tiền PayPal nguyên hợp lệ.");
    const amount=BigInt(raw.replaceAll(".",""));
    if(amount<=0n || amount>9007199254740991n) throw new Error("Số tiền phải từ 1 đến 9.007.199.254.740.991 PayPal.");
    return amount.toString();
  }
  el("accountCardTopup").addEventListener("click",()=>openTransfer("topup"));
  el("accountCardWithdraw").addEventListener("click",()=>openTransfer("withdraw"));
  el("cardTransferCancel").addEventListener("click",()=>{const kind=transfer.kind;closeTransfer();updateTransfer();el(kind==="topup"?"accountCardTopup":"accountCardWithdraw").focus();});
  function normalizeTransferInput() {
    const input=el("cardTransferAmount"),raw=input.value;
    if(input.readOnly || pendingTransfer() || !/^[0-9.]*$/.test(raw)) return;
    const plain=raw.replaceAll(".","");
    if(!plain){input.value="";return;}
    const before=(raw.slice(0,input.selectionStart).match(/[0-9]/g)||[]).length;
    let max=9007199254740991n;
    if(cardState.loaded){const available=BigInt(transfer.kind==="topup"?cardState.walletBalance:cardState.balance);max=available<0n?0n:available<max?available:max;}
    const amount=BigInt(plain);
    input.value=number(amount>max?max:amount);
    let caret=0,digits=0;
    while(caret<input.value.length && digits<before){if(/[0-9]/.test(input.value[caret])) digits++;caret++;}
    input.setSelectionRange(caret,caret);
  }
  el("cardTransferAmount").addEventListener("input",()=>{transfer.percent=null;updateTransfer();transferStatus("");});
  el("cardTransferPresets").addEventListener("click",event=>{
    const button=event.target.closest("[data-transfer-percent]");
    if(!button || button.disabled || transfer.busy || !cardState.loaded || cardState.currency!=="PayPal" || pendingTransfer()) return;
    const percent=button.dataset.transferPercent;
    if(!["10","20","25","50","75","100"].includes(percent)) return;
    const available=BigInt(transfer.kind==="topup"?cardState.walletBalance:cardState.balance);
    el("cardTransferAmount").value=number(available*BigInt(percent)/100n);transfer.percent=percent;
    transferStatus("");updateTransfer();
    const input=el("cardTransferAmount");input.focus();input.setSelectionRange(input.value.length,input.value.length);
  });
  el("accountCardTransfer").addEventListener("submit",async event=>{
    event.preventDefault();
    if(transfer.busy || !cardState.loaded || !currentUser || state.view!=="card") return;
    let attempt=pendingTransfer();
    try {
      const amount=transferAmount();
      if(!attempt) {
        if(BigInt(amount)>BigInt(transfer.kind==="topup"?cardState.walletBalance:cardState.balance)) throw new Error(transfer.kind==="topup"?"Số dư ví không đủ để nạp thẻ.":"Số dư thẻ không đủ để rút.");
        const requestId=Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,"0")).join("");
        attempt={accountId:cardState.accountId,kind:transfer.kind,amount,requestId};saveTransfer(attempt);
      } else if(attempt.kind!==transfer.kind || attempt.amount!==amount) throw new Error("Hãy kiểm tra giao dịch trước khi chuyển khoản khác.");
    } catch(error) { transferStatus(error.message,"error");return; }
    const serial=++transfer.serial,owner=currentUser,controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),15000);
    transfer.busy=true;updateTransfer();transferStatus("Đang xử lý giao dịch…");
    try {
      const response=await fetch("/api/account/card-transfer",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({kind:attempt.kind,amount:attempt.amount,requestId:attempt.requestId}),signal:controller.signal});
      const report=await response.json();
      if(serial!==transfer.serial || currentUser!==owner || !dialog.open || state.view!=="card") return;
      if(!response.ok || report.ok!==true) {
        if(response.status>=400 && response.status<500) forgetTransfer(attempt);
        throw new Error(report.message || "Chưa nhận được kết quả. Bấm Kiểm tra giao dịch để thử lại.");
      }
      if(report.owner!==owner || report.accountId!==attempt.accountId || report.requestId!==attempt.requestId || report.kind!==attempt.kind || report.amount!==attempt.amount) throw new Error("Chưa xác nhận được thông tin giao dịch. Hãy kiểm tra lại.");
      forgetTransfer(attempt);el("cardTransferAmount").value="";transfer.percent=null;
      transferStatus(`Đã ${attempt.kind==="topup"?"nạp vào thẻ":"rút về ví"} ${number(attempt.amount)} PayPal.`,"success");
      cardState.balance=report.cardBalance;cardState.walletBalance=report.balance;
      el("accountCardBalance").textContent=number(report.cardBalance);
      window.dispatchEvent(new CustomEvent('dvlf:prediction-wallet',{detail:{owner,balance:Number(report.balance),walletVersion:report.walletVersion}}));
      void window.VietlottFinancialNotifications?.refresh();
      cardState.page=1;void loadCard();
    } catch(error) {
      if(serial===transfer.serial && currentUser===owner && dialog.open && state.view==="card") transferStatus(error.name==="AbortError"?"Chưa nhận được kết quả. Bấm Kiểm tra giao dịch để thử lại.":error.message,"error");
    } finally {
      clearTimeout(timeout);
      if(serial===transfer.serial){transfer.busy=false;updateTransfer();}
    }
  });
  function selectView(view,showHistory=false) {
    if(view!==state.view){closeCardActions();updateTransfer();}
    if(view==="card" && showHistory){cardState.history=true;el("accountCardHistory").hidden=false;el("accountCardHistoryToggle").setAttribute("aria-expanded","true");}
    stop();state.view=view;
    for(const [id,value] of [["walletTransactionsTab","wallet"],["walletCardTab","card"]]){el(id).setAttribute("aria-selected",String(view===value));el(id).tabIndex=view===value?0:-1;}
    el("walletTransactionsPanel").hidden=view!=="wallet";el("walletCardPanel").hidden=view!=="card";
    el(view==="wallet"?"walletTransactionsTab":"walletCardTab").focus({preventScroll:true});
    if(view==="wallet") void load();else void loadCard();
  }
  el("walletTransactionsTab").addEventListener("click",()=>selectView("wallet"));
  el("walletCardTab").addEventListener("click",()=>selectView("card"));
  dialog.querySelector(".wallet-finance-tabs").addEventListener("keydown",event=>{
    if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
    event.preventDefault();const view=event.key==="Home"?"wallet":event.key==="End"?"card":state.view==="wallet"?"card":"wallet";
    selectView(view);el(view==="wallet"?"walletTransactionsTab":"walletCardTab").focus();
  });
  el("accountCardHistoryToggle").addEventListener("click",()=>{
    if(transfer.busy) return;
    const show=!cardState.history;closeTransfer();cardState.history=show;
    el("accountCardHistory").hidden=!show;el("accountCardHistoryToggle").setAttribute("aria-expanded",String(show));
    void loadCard();
  });
  el("cardHistoryFilters").addEventListener("click",event=>{const button=event.target.closest("[data-card-kind]");if(!button) return;cardState.kind=button.dataset.cardKind;cardState.page=1;el("cardHistoryFilters").querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));void loadCard();});
  el("cardHistoryRefresh").addEventListener("click",()=>void loadCard());
  el("cardHistoryPrev").addEventListener("click",()=>{if(cardState.page>1){cardState.page--;void loadCard();}});
  el("cardHistoryNext").addEventListener("click",()=>{if(cardState.page<cardState.pages){cardState.page++;void loadCard();}});
  window.addEventListener("dvlf:auth-changed",()=>{stop();if(dialog.open) dialog.close();clear();clearCard();});
})();
