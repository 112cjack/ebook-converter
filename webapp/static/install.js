/* 书渡 · install：引擎安装引导（便携版 / winget / 本地安装包） */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  // ── 引擎安装引导 ──

  var installTimer = null;

  function setInstallButtons(disabled) {
    S.$("x-installportable").disabled = disabled;
    S.$("x-installwinget").disabled = disabled;
    S.$("x-installlocal").disabled = disabled;
  }

  function renderInstallState(install) {
    var box = S.$("x-installstate");
    if (!install || (!install.active && install.state === "idle")) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    S.$("x-installfill").style.width = (install.progress || 0) + "%";
    S.$("x-installmsg").textContent = install.message || "";
    S.$("x-installmsg").style.color = install.state === "failed" ? "var(--x-clay)"
      : install.state === "done" ? "var(--x-moss)" : "";
  }

  function pollInstall() {
    if (installTimer) clearTimeout(installTimer);
    S.api("/api/status").then(function (body) {
      S.state.engine = body.engine;
      S.renderEngineBadge();
      renderInstallState(body.engine.install);
      var install = body.engine.install || {};
      if (!install.active) {
        setInstallButtons(false);
        if (install.state === "done") {
          S.toast("引擎已安装，检测更新中…", "ok");
          renderInstallState({ active: false, state: "idle", progress: 0, message: "" });
          return S.loadStatus();
        }
        return;  // failed：状态留在对话框上，按钮已恢复可重试
      }
      installTimer = setTimeout(pollInstall, 1000);
    }).catch(function () {
      installTimer = setTimeout(pollInstall, 2000);
    });
  }

  function installEngine(mode) {
    S.api("/api/install-engine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode }),
    }).then(function () {
      setInstallButtons(true);
      renderInstallState({ active: true, state: "downloading", progress: 0, message: "正在启动安装…" });
      pollInstall();
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
    });
  }

  function installEngineLocal(file) {
    var fd = new FormData();
    fd.append("mode", "local");
    fd.append("package", file, file.name);
    setInstallButtons(true);
    renderInstallState({ active: true, state: "installing", progress: 0, message: "正在上传安装包…" });
    S.api("/api/install-engine", { method: "POST", body: fd }).then(function () {
      pollInstall();
    }).catch(function (err) {
      setInstallButtons(false);
      if (!err.network) S.toast(err.message, "warn");
    });
  }

  S.$("x-guidebtn").addEventListener("click", function () { S.$("x-guidedlg").showModal(); });
  S.$("x-guideclose").addEventListener("click", function () { S.$("x-guidedlg").close(); });
  S.$("x-guideok").addEventListener("click", function () { S.$("x-guidedlg").close(); });
  S.$("x-guideset").addEventListener("click", function () {
    S.$("x-guidedlg").close();
    S.openSettings();
  });
  S.$("x-guideredetect").addEventListener("click", function () {
    S.state._announcedEngine = false;
    S.loadStatus();
  });
  S.$("x-installportable").addEventListener("click", function () { installEngine("portable"); });
  S.$("x-installwinget").addEventListener("click", function () { installEngine("winget"); });
  S.$("x-installlocal").addEventListener("click", function () { S.$("x-installfile").click(); });
  S.$("x-installfile").addEventListener("change", function () {
    var f = S.$("x-installfile").files && S.$("x-installfile").files[0];
    S.$("x-installfile").value = "";
    if (f) installEngineLocal(f);
  });

  // ── 对外导出 ──
  S.setInstallButtons = setInstallButtons;
  S.renderInstallState = renderInstallState;
  S.pollInstall = pollInstall;
  S.installEngine = installEngine;
  S.installEngineLocal = installEngineLocal;
})(window.Shudu);
