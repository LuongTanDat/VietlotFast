(() => {
  "use strict";
  const names = { google: "Google", facebook: "Facebook", zalo: "Zalo" };
  let providers = {}, busy = false;
  async function configureProviders() {
    try {
      const response = await api("/api/auth/social/providers");
      providers = response.providers || {};
    } catch { providers = {}; }
    let enabled = 0;
    document.querySelectorAll("[data-social-provider]").forEach(button => {
      const ready = providers[button.dataset.socialProvider]?.enabled === true;
      button.setAttribute("aria-disabled", String(!ready));
      button.title = ready ? `Đăng nhập bằng ${names[button.dataset.socialProvider]}` : "Chưa được kích hoạt";
      if (ready) enabled++;
    });
    document.getElementById("socialAuthStatus").textContent = enabled ? "Chọn phương thức đăng nhập phù hợp với bạn." : "Đăng nhập mạng xã hội chưa được kích hoạt.";
  }
  document.querySelectorAll("[data-social-provider]").forEach(button => {
    button.onclick = async () => {
      const provider = button.dataset.socialProvider;
      if (busy) return;
      if (!providers[provider]?.enabled) { setAuthMsg(`Đăng nhập ${names[provider]} chưa được kích hoạt. Bạn vẫn có thể dùng tên tài khoản và mật khẩu.`, "warn"); return; }
      busy = true; button.disabled = true;
      try {
        const response = await api("/api/auth/social/start", "POST", { provider });
        const destination = new URL(response.url);
        if (destination.protocol !== "https:") throw new Error("Đường dẫn đăng nhập không hợp lệ.");
        window.location.assign(destination.href);
      } catch (error) { setAuthMsg(error.message || "Chưa mở được trang đăng nhập. Hãy thử lại.", "warn"); busy = false; button.disabled = false; }
    };
  });
  ["loginUser", "loginPass"].forEach(id => document.getElementById(id).addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); document.getElementById("loginBtn").click(); }
  }));
  ["regUser", "regPass", "regPass2"].forEach(id => document.getElementById(id).addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); document.getElementById("registerBtn").click(); }
  }));
  configureProviders();
})();
