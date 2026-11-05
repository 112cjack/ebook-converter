/* 书渡 · browse：本机目录浏览器 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  // ── 目录浏览器 ──

  var browseCurrent = null;
  var browseParent = null;

  function openBrowse(target) {
    S.state.browseTarget = target || "output";
    browseCurrent = S.state.browseTarget === "watch"
      ? (S.currentWatchFolderInput() ? S.currentWatchFolderInput().value.trim() || null : null)
      : (S.state.outputDir || S.state.lastOutputDir || null);
    browseParent = null;
    S.$("x-browsedlg").showModal();
    loadBrowse(browseCurrent);
  }

  function loadBrowse(path) {
    var url = path ? "/api/browse?path=" + encodeURIComponent(path) : "/api/browse";
    S.api(url).then(function (body) {
      browseCurrent = body.current;
      browseParent = body.parent;
      S.$("x-browsecwd").textContent = body.current || "本机";
      S.$("x-browseup").disabled = !body.parent;
      var list = S.$("x-browsebody");
      list.textContent = "";
      if (!body.entries.length) {
        list.appendChild(S.el("div", "x-browseempty", "此目录下没有子文件夹。"));
        return;
      }
      body.entries.forEach(function (entry) {
        var row = S.el("button", "x-browserow");
        row.type = "button";
        row.appendChild(S.icon("folder-open"));
        row.appendChild(document.createTextNode(entry.name));
        row.addEventListener("click", function () { loadBrowse(entry.path); });
        list.appendChild(row);
      });
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
    });
  }

  function chooseBrowse() {
    if (browseCurrent) {
      if (S.state.browseTarget === "watch") {
        var input = S.currentWatchFolderInput();
        if (input) input.value = browseCurrent;
      } else {
        S.state.outputDir = browseCurrent;
        S.renderOutdirHint();
        S.toast("输出目录已选定：" + browseCurrent, "ok");
      }
    }
    S.$("x-browsedlg").close();
  }

  // ── 对外导出 ──
  S.openBrowse = openBrowse;
  S.chooseBrowse = chooseBrowse;
  S.browseUp = function () { if (browseParent) loadBrowse(browseParent); };
})(window.Shudu);
