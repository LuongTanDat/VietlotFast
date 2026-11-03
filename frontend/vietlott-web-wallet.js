(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const dialog = el("walletHistoryDialog");
  if (!dialog) return;
  const state = {view:"wallet",kind:"all", page:1, pages:1, controller:null, serial:0};
  const cardState = {kind:"all",page:1,pages:1,history:false};
  const cardKinds = {transfer:"Chuyển",topup:"Nạp",withdraw:"Rút",reward:"Thưởng"};
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
  el("walletHistoryOpen").addEventListener("click",()=>{
    if (!currentUser) return;
    if (typeof closeHeaderPopovers==="function") closeHeaderPopovers();
    state.kind="all"; state.page=1;
    el("walletHistoryFilters").querySelectorAll("button").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.walletKind==="all")));
    cardState.kind="all";cardState.page=1;cardState.history=false;
    el("accountCardHistory").hidden=true;el("accountCardHistoryToggle").setAttribute("aria-expanded","false");
    el("cardHistoryFilters").querySelectorAll("button").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.cardKind==="all")));
    dialog.showModal(); selectView("wallet");
  });
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
    ["accountCardBalance","accountCardId","accountCardHolder"].forEach(id=>el(id).textContent="—");
    el("cardHistoryRows").replaceChildren();el("cardHistoryCount").textContent="";el("cardHistoryPage").textContent="—";
    el("cardHistoryPrev").disabled=el("cardHistoryNext").disabled=true;
    el("accountCardStatus").textContent=el("cardHistoryStatus").textContent="";
    el("cardHistoryTable").setAttribute("aria-busy","false");
  }
  async function loadCard() {
    if (!dialog.open || !currentUser || state.view!=="card") return;
    stop();
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
    } catch(error) {
      if(serial!==state.serial || !dialog.open || currentUser!==owner) return;
      clearCard();el("accountCardStatus").textContent=error.name==="AbortError"?"Tải quá thời gian chờ. Hãy thử lại.":error.message;
    } finally {
      clearTimeout(timeout);
      if(serial===state.serial){state.controller=null;el("cardHistoryTable").setAttribute("aria-busy","false");}
    }
  }
  function selectView(view) {
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
  el("accountCardHistoryToggle").addEventListener("click",()=>{cardState.history=!cardState.history;el("accountCardHistory").hidden=!cardState.history;el("accountCardHistoryToggle").setAttribute("aria-expanded",String(cardState.history));void loadCard();});
  el("cardHistoryFilters").addEventListener("click",event=>{const button=event.target.closest("[data-card-kind]");if(!button) return;cardState.kind=button.dataset.cardKind;cardState.page=1;el("cardHistoryFilters").querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));void loadCard();});
  el("cardHistoryRefresh").addEventListener("click",()=>void loadCard());
  el("cardHistoryPrev").addEventListener("click",()=>{if(cardState.page>1){cardState.page--;void loadCard();}});
  el("cardHistoryNext").addEventListener("click",()=>{if(cardState.page<cardState.pages){cardState.page++;void loadCard();}});
  window.addEventListener("dvlf:auth-changed",()=>{stop();if(dialog.open) dialog.close();clear();clearCard();});
})();
