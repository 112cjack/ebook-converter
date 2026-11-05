/* 书渡 · state：引擎状态、任务列表加载与轮询 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  // ── 状态加载与轮询 ──

  function engineReady() {
    return !!(S.state.engine && S.state.engine.installed);
  }

  function loadStatus() {
    return S.api("/api/status").then(function (body) {
      S.state.engine = body.engine;
      S.state.outputFormats = body.output_formats || [];
      S.state.inputExtensions = body.input_extensions || [];
      S.state.settings = body.settings || {};
      S.state.frozen = !!body.frozen;
      S.renderEngineBadge();
      S.renderFormatButtons();
      S.renderAcceptHint();
      S.renderOutdirHint();
      if (S.state.engine && !S.state.engine.installing) {
        if (S.state.engine.installed) {
          if (S.state.engine.version && !S.state._announcedEngine) {
            S.toast("Calibre 已就绪 · " + S.state.engine.version, "ok");
            S.state._announcedEngine = true;
          }
        } else if (!S.state.guideShown) {
          S.state.guideShown = true;
          S.$("x-guidedlg").showModal();
        }
      }
    }).catch(function (err) {
      // 状态获取失败时置回"检测中"，不留过期画面（避免与轮询侧显示矛盾）
      S.state.engine = null;
      S.state._announcedEngine = false;
      S.renderEngineBadge();
      throw err;
    });
  }

  function refreshTasks() {
    return S.api("/api/tasks").then(function (body) {
      S.state.uploads = body.uploads || [];
      S.state.tasks = body.tasks || [];
      // 引擎状态随轮询持续同步：保证胶囊/引导条/提示行三者永远一致
      if (body.engine) {
        S.state.engine = body.engine;
        S.renderEngineBadge();
      }
      var busy = S.state.tasks.some(function (t) {
        return t.status === "queued" || t.status === "converting";
      });
      if (S.state.wasBusy && !busy) onAllSettled();
      S.state.wasBusy = busy;
      S.renderList();
      schedulePoll(busy ? 1000 : 3000);
    }).catch(function () {
      schedulePoll(3000);  // 服务未就绪或瞬时错误，稍后重试
    });
  }

  function schedulePoll(delay) {
    if (S.state.timer) clearTimeout(S.state.timer);
    S.state.timer = setTimeout(refreshTasks, delay);
  }

  function onAllSettled() {
    var done = S.state.tasks.filter(function (t) { return t.status === "done"; }).length;
    var failed = S.state.tasks.filter(function (t) { return t.status === "failed"; }).length;
    var msg;
    if (done && failed) msg = "转换完成：成功 " + done + " 个，失败 " + failed + " 个";
    else if (failed) msg = "转换结束：" + failed + " 个文件失败";
    else msg = "全部转换完成，共 " + done + " 个文件";
    S.toast(msg, failed ? "warn" : "ok");
    S.announce(msg);
    notifyDesktop(msg);
  }

  function notifyDesktop(msg) {
    // 页面在前台时 toast 足够；仅在后台标签页用系统通知提醒
    if (!("Notification" in window) || document.hasFocus()) return;
    if (Notification.permission === "granted") {
      try { new Notification("书渡", { body: msg }); } catch (e) { /* 部分环境不支持 */ }
    }
  }

  // ── 对外导出 ──
  S.engineReady = engineReady;
  S.loadStatus = loadStatus;
  S.refreshTasks = refreshTasks;
  S.schedulePoll = schedulePoll;
})(window.Shudu);
