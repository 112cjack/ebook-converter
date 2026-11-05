/* 书渡 · 入口 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";
  S.loadStatus().then(S.refreshTasks, S.refreshTasks);
  S.loadWatch();
  try {
    if (!localStorage.getItem("seen_intro")) {
      S.$("x-introdlg").showModal();
      S.$("x-introok").addEventListener("click", function () {
        S.$("x-introdlg").close();
        try { localStorage.setItem("seen_intro", "1"); } catch (e) { /* 隐私模式 */ }
      });
    }
  } catch (e) { /* localStorage 不可用时跳过引导 */ }
})(window.Shudu);
