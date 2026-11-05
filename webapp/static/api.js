/* 书渡 · api：请求封装与连接提示 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  var CONN_MSG = "无法连接本地服务，程序可能已关闭——请重新打开程序，再刷新本页面。";

  function api(path, options) {
    return fetch(path, options).catch(function () {
      S.showConnBanner(true);
      var err = new Error(CONN_MSG);
      err.network = true;
      throw err;
    }).then(function (resp) {
      S.showConnBanner(false);
      return resp.json().catch(function () { return {}; }).then(function (body) {
        if (!resp.ok) {
          var err = new Error(body.error || ("请求失败（" + resp.status + "）"));
          err.status = resp.status;
          err.body = body;
          throw err;
        }
        return body;
      });
    });
  }

  // ── 对外导出 ──
  S.api = api;
  S.CONN_MSG = CONN_MSG;
})(window.Shudu);
