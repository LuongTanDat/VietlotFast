(function () {
  "use strict";
  const audio = document.getElementById("backgroundMusic");
  const button = document.getElementById("backgroundMusicToggle");
  const slider = document.getElementById("backgroundMusicVolume");
  const status = document.getElementById("backgroundMusicStatus");
  if (!audio || !button || !slider || !status) return;

  function read(storage, key) { try { return storage.getItem(key); } catch { return null; } }
  function write(storage, key, value) { try { storage.setItem(key, String(value)); } catch {} }
  let enabled = read(localStorage, "dvlf.music.enabled") !== "off";
  const storedVolume = read(localStorage, "dvlf.music.volume");
  const volume = storedVolume === null ? 25 : Number(storedVolume);
  let authenticated = false;
  let generation = 0;
  let attempt = null;
  let needsGesture = false;
  let failed = false;
  let restored = false;
  let savedAt = 0;
  const position = Number(read(sessionStorage, "dvlf.music.position")) || 0;
  audio.volume = Number.isFinite(volume) ? Math.max(0, Math.min(100, volume)) / 100 : .25;
  slider.value = String(Math.round(audio.volume * 100));

  function update() {
    slider.style.setProperty("--music-volume", `${slider.value}%`);
    slider.setAttribute("aria-valuetext", `${slider.value}%`);
    const playing = authenticated && enabled && !audio.paused && !audio.ended;
    const label = !enabled ? "Bật nhạc nền" : failed ? "Thử phát lại nhạc nền" : playing ? "Tắt nhạc nền" : "Nhấn để phát nhạc nền";
    button.disabled = !authenticated;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-pressed", String(enabled));
    button.classList.toggle("is-playing", playing);
    button.classList.toggle("is-muted", !enabled);
    status.textContent = !authenticated ? "Phát sau khi đăng nhập" : !enabled ? "Đã tắt nhạc" : failed ? "Chưa tải được nhạc · bấm ♫ để thử lại" : playing ? `Âm Lượng · ${slider.value}%` : needsGesture ? "Bấm ♫ để phát nhạc" : "Đang chuẩn bị nhạc…";
    status.title = status.textContent;
  }

  function savePosition() {
    if (Number.isFinite(audio.currentTime)) write(sessionStorage, "dvlf.music.position", audio.currentTime);
  }

  function play() {
    if (!authenticated || !enabled || attempt || failed) return;
    if (!audio.paused) { update(); return; }
    const serial = generation;
    if (!audio.getAttribute("src")) audio.src = audio.dataset.src;
    needsGesture = false;
    update();
    attempt = audio.play().then(() => {
      if (!authenticated || !enabled) audio.pause();
      update();
    }).catch(error => {
      if (serial !== generation || !authenticated || !enabled) return;
      needsGesture = error.name === "NotAllowedError";
      failed = !needsGesture && error.name !== "AbortError";
      update();
    }).finally(() => {
      attempt = null;
      if (serial !== generation && authenticated && enabled) play();
    });
  }

  window.addEventListener("dvlf:auth-changed", event => {
    const next = event.detail?.authenticated === true;
    if (next !== authenticated) generation++;
    authenticated = next;
    if (!next) { savePosition(); audio.pause(); needsGesture = false; }
    else if (enabled) play();
    update();
  });

  button.addEventListener("click", () => {
    if (!authenticated) return;
    if (enabled && !audio.paused && !failed) {
      enabled = false;
      generation++;
      savePosition();
      audio.pause();
    } else {
      enabled = true;
      if (failed) { failed = false; audio.load(); }
      play();
    }
    write(localStorage, "dvlf.music.enabled", enabled ? "on" : "off");
    update();
  });
  slider.addEventListener("input", () => {
    audio.volume = Math.max(0, Math.min(100, Number(slider.value))) / 100;
    write(localStorage, "dvlf.music.volume", slider.value);
    update();
  });
  function unlock(event) {
    if (!event.isTrusted || !needsGesture || event.target.closest?.("#backgroundMusicToggle, #backgroundMusicVolume, #logoutBtn")) return;
    play();
  }
  document.addEventListener("pointerdown", unlock);
  document.addEventListener("keydown", unlock);
  audio.addEventListener("loadedmetadata", () => {
    if (!restored && position > 0 && position < audio.duration - .25) audio.currentTime = position;
    restored = true;
  });
  audio.addEventListener("timeupdate", () => {
    if (Date.now() - savedAt >= 5000) { savedAt = Date.now(); savePosition(); }
  });
  audio.addEventListener("error", () => { failed = true; update(); });
  ["playing", "pause", "volumechange"].forEach(name => audio.addEventListener(name, update));
  window.addEventListener("pagehide", () => { savePosition(); audio.pause(); });
  window.addEventListener("pageshow", event => { if (event.persisted) play(); });
  update();
})();
