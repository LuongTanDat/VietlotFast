from backup_fixes import ROOT

file = ROOT / 'frontend/vietlott-web-core.js'
text = file.read_text(encoding='utf-8')
start = text.index('    document.getElementById("recoverAdminBtn").onclick')
end = text.index('\n    document.getElementById("logoutBtn")', start)
text = text[:start] + '''    document.getElementById("recoverAdminBtn").onclick = () => {
      setAuthMsg("Khôi phục admin bằng lệnh cục bộ --recover-admin trong terminal. Xem hướng dẫn chạy website.", "warn");
    };
''' + text[end:]
start = text.index('    async function setVipMembershipExpiry(')
end = text.index('    function startVipMembershipTimer(', start)
text = text[:start] + text[end:]
text = text.replace('const active = !!currentUser && Number.isFinite(expiresAtMs) && expiresAtMs > nowMs;', 'const active = !!currentUser && (currentRole === "admin" || (Number.isFinite(expiresAtMs) && expiresAtMs > nowMs));')
text = text.replace('const remainingMs = active ? Math.max(0, expiresAtMs - nowMs) : 0;', 'const remainingMs = active && Number.isFinite(expiresAtMs) ? Math.max(0, expiresAtMs - nowMs) : 0;')
text = text.replace('remainingText: active ? formatVipMembershipRemaining(remainingMs)', 'remainingText: currentRole === "admin" ? "Quyền quản trị" : active ? formatVipMembershipRemaining(remainingMs)')
text = text.replace('await api("/api/store", "POST", { store: request.snapshotText });', 'const saved = await api("/api/store", "POST", { store: request.snapshotText });\n          if (request.username === currentUser && request.generation === storeSaveGeneration) applyServerWallet(saved.store);')
start = text.index('    function confirmLuckyWheelTopupExchange()')
end = text.index('\n    function ', start + 15)
text = text[:start] + '''    async function confirmLuckyWheelTopupExchange() {
      if (luckyWheelSpinning) return;
      const state = getLuckyWheelTopupState(luckyWheelSelectedTopupSpins);
      if (!state.canExchange) return;
      luckyWheelSpinning = true;
      try {
        await saveStore();
        const response = await requestServerWheel("exchange", state.spins);
        applyServerWallet(response.store);
        renderCurrencyBar(); renderLuckyWheelPanel(); closeLuckyWheelTopup();
        setLuckyWheelResult(`Đã đổi <b>${formatLuckyWheelAmount(state.paypalCost)} điểm PP</b> lấy <b>${state.spins} lượt</b>.`, "ok");
      } catch (error) { setLuckyWheelResult(escapeHtml(error.message || String(error)), "warn"); }
      finally { luckyWheelSpinning = false; }
    }
''' + text[end:]
start = text.index('    function applyLuckyWheelReward(')
end = text.index('    function startLuckyWheelUiTimer()', start)
text = text[:start] + '''    let pendingWheelRequest = null;
    function applyServerWallet(serverStore) {
      if (!serverStore || typeof serverStore !== "object") return;
      if (Number(serverStore.walletVersion || 0) < Number(store.walletVersion || 0)) return;
      for (const [key, value] of Object.entries(serverStore)) {
        if (key === "diamondBalance" || key === "paypalBalance" || key.startsWith("vip") || key.startsWith("luckyWheel") || key === "walletVersion") store[key] = value;
      }
      renderCurrencyBar(); renderVipMembership();
    }

    async function requestServerWheel(action, count) {
      if (IS_LOCAL_MODE) throw new Error("Mở qua http://localhost:8080 để dùng vòng quay.");
      if (pendingWheelRequest && (pendingWheelRequest.action !== action || pendingWheelRequest.count !== count))
        throw new Error("Cần thử lại giao dịch trước để xác định kết quả.");
      if (!pendingWheelRequest) pendingWheelRequest = { action, count, requestId: crypto.randomUUID() };
      const response = await api("/api/wheel", "POST", pendingWheelRequest);
      pendingWheelRequest = null;
      return response;
    }

    async function spinLuckyWheel() {
      if (luckyWheelSpinning) return;
      const multiplier = getLuckyWheelSpinMultiplier();
      const disc = document.getElementById("luckyWheelDisc");
      if (!disc) return;
      luckyWheelSpinning = true;
      try {
        await saveStore();
        const response = await requestServerWheel("spin", multiplier);
        applyServerWallet(response.store);
        const picked = { index: response.segmentIndex, segment: LUCKY_WHEEL_SEGMENTS[response.segmentIndex] };
        if (!picked.segment) throw new Error("Kết quả vòng quay không hợp lệ.");
        const displaySegment = buildLuckyWheelDisplaySegment(picked.segment, multiplier);
        const segmentAngle = 360 / LUCKY_WHEEL_SEGMENTS.length;
        const segmentCenter = picked.index * segmentAngle + segmentAngle / 2;
        const normalizedCurrent = ((luckyWheelRotation % 360) + 360) % 360;
        const targetNormalized = (360 - segmentCenter) % 360;
        luckyWheelRotation += 6 * 360 + (targetNormalized - normalizedCurrent + 360) % 360;
        renderLuckyWheelMeta();
        setLuckyWheelResult(`Đang quay <b>x${multiplier}</b>...`, "muted");
        disc.style.transform = `rotate(${luckyWheelRotation}deg)`;
        window.setTimeout(() => {
          luckyWheelSpinning = false;
          renderCurrencyBar(); renderLuckyWheelPanel();
          setLuckyWheelResult(`Bạn nhận được <b>${escapeHtml(buildLuckyWheelRewardText(displaySegment.reward))}</b>.`, "ok");
          maybeTriggerLuckyWheelAutoSpin();
        }, 5300);
      } catch (error) {
        luckyWheelSpinning = false;
        stopLuckyWheelAutoMode(escapeHtml(error.message || String(error)), "warn");
        setLuckyWheelResult(escapeHtml(error.message || String(error)), "warn");
      }
    }

''' + text[end:]
start = text.index('    function resetLuckyWheelHistory()')
end = text.index('\n    function ', start + 15)
text = text[:start] + '''    async function resetLuckyWheelHistory() {
      try {
        const response = await requestServerWheel("clear", 1);
        applyServerWallet(response.store); renderLuckyWheelPanel();
      } catch (error) { setLuckyWheelResult(escapeHtml(error.message || String(error)), "warn"); }
    }
''' + text[end:]
file.write_text(text, encoding='utf-8')
print('Wallet UI now uses server transactions')
