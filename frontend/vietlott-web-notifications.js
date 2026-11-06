(() => {
  "use strict";
  const KEY="dvlf_financial_notifications_v1";
  const fields=["auditAfter","cardAfter","wheelAfter"];
  const identity=()=>typeof currentUser!=="undefined" && currentUser && currentAccountId ? `${currentAccountId}:${currentUser}` : "";
  let owner="", generation=0, timer=null, controller=null, loading=false, entries=[], cursor={};
  const validCursor=value=>value && fields.every(key=>typeof value[key]==="string" && /^(0|[1-9][0-9]{0,18})$/.test(value[key]));
  const validItem=item=>item && typeof item.id==="string" && ["finance","deposit"].includes(item.kind) && item.recipientAccountId===currentAccountId && item.audience==="user" && ["wallet-history","card-history","deposit-history"].includes(item.action);
  function reset(user) {
    generation++; controller?.abort(); controller=null; clearTimeout(timer); timer=null; loading=false;
    owner=user; entries=[]; cursor={auditAfter:"0",cardAfter:"0",wheelAfter:"0"};
    if (user) {
      const saved=readHeaderNotificationValue(KEY,{});
      if (saved.accountId===currentAccountId && validCursor(saved.cursor) && Array.isArray(saved.events)) {
        cursor=saved.cursor; entries=saved.events.filter(validItem);
      }
    }
  }
  function items() { return owner && owner===identity()?entries:[]; }
  function activate(item) {
    if (!owner || owner!==identity() || !validItem(item)) return;
    if (item.action==="deposit-history") { window.VietlottDepositNotifications?.activate(item); return; }
    window.VietlottAccountHistory?.open(item.action==="card-history"?"card":"wallet");
  }
  async function refresh() {
    const user=identity();
    if (owner!==user) reset(user);
    if (!user || document.hidden || loading) return;
    clearTimeout(timer); loading=true;
    const epoch=generation, accountId=currentAccountId, username=currentUser;
    const request=new AbortController(); controller=request;
    try {
      let more=true;
      while (more) {
        const timeout=setTimeout(()=>request.abort(),10000);
        let response, report;
        try {
          response=await fetch(`/api/account/financial-notifications?${new URLSearchParams(cursor)}`,{credentials:"same-origin",cache:"no-store",signal:request.signal});
          report=await response.json();
        } finally { clearTimeout(timeout); }
        if (epoch!==generation || user!==identity() || document.hidden) return;
        if (!response.ok || report.ok!==true || report.owner!==username || report.accountId!==accountId || !validCursor(report.cursor) || !Array.isArray(report.events) || !report.events.every(validItem)) throw new Error("Thông báo không khớp tài khoản.");
        if (fields.some(key=>BigInt(report.cursor[key])<BigInt(cursor[key])) || (report.hasMore && fields.every(key=>report.cursor[key]===cursor[key]))) throw new Error("Mốc thông báo không tiến lên.");
        const merged=new Map(entries.map(item=>[item.id,item]));
        for (const item of report.events) merged.set(item.id,{...item,timestamp:Date.parse(item.createdAt)||0});
        entries=[...merged.values()]; cursor=report.cursor;
        // Archive and cursor share one write: a failed storage write cannot persist a cursor past lost notices.
        writeHeaderNotificationValue(KEY,{accountId,cursor,events:entries});
        renderHeaderNotifications(); more=report.hasMore===true;
        if (more) await new Promise(resolve=>setTimeout(resolve,0));
      }
    } catch (_) { /* Keep prior notices and retry this cursor; never infer a successful transaction. */ }
    finally {
      if (epoch===generation && owner===user) {
        loading=false; controller=null;
        if (user && !document.hidden) timer=setTimeout(refresh,15000);
      }
    }
  }
  function sync() {
    const user=identity();
    if (owner!==user || document.hidden) reset(user);
    renderHeaderNotifications();
    if (!document.hidden) void refresh();
  }
  window.VietlottFinancialNotifications=Object.freeze({items,refresh,activate});
  window.addEventListener("dvlf:auth-changed",sync);
  document.addEventListener("visibilitychange",sync);
  sync();
})();
