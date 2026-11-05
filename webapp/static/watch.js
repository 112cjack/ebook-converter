/* 书渡 · watch：文件夹监听卡片与设置里的规则列表 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  // ── 文件夹监听（F8）──

  var KIND_LABEL = { unconvertible: "无法转换", wrong_format: "格式不符" };

  function loadWatch() {
    return S.api("/api/watch").then(function (body) {
      S.state.watch = body;
      renderWatch(body);
      if (body.enabled && !S.state.watchTimer) {
        S.state.watchTimer = setTimeout(loadWatch, 5000);
      }
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
      S.state.watchTimer = setTimeout(loadWatch, 8000);
    });
  }

  function scheduleWatchPoll() {
    if (S.state.watchTimer) clearTimeout(S.state.watchTimer);
    S.state.watchTimer = null;
    if (S.state.watch && S.state.watch.enabled) {
      S.state.watchTimer = setTimeout(loadWatch, 5000);
    }
  }

  function watchConvert(paths) {
    if (!paths || !paths.length) return;
    S.api("/api/watch-convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: paths }),
    }).then(function (body) {
      S.toast("已把 " + body.tasks.length + " 个文件加入转换队列", "ok");
      S.state.wasBusy = true;
      S.refreshTasks();
      return loadWatch();
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
    });
  }

  function renderWatch(w) {
    var card = S.$("x-watchcard");
    if (!w || !w.enabled) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    var violations = w.violations || [];
    var metaParts = w.rules.map(function (r) {
      var count = violations.filter(function (v) { return v.rule_id == r.id; }).length;
      return r.folder.replace(/[\\/]+$/, "") + " · 期望 " + S.fmtLabel(r.format) +
        (count ? "（" + count + " 个不符）" : "（符合）");
    });
    if (w.unreachable && w.unreachable.length) {
      metaParts.push("暂时不可达：" + w.unreachable.join("、"));
    }
    if (w.auto_converted && w.auto_converted.length) {
      metaParts.push("已自动转换：" + w.auto_converted.join("、"));
    }
    S.$("x-watchmeta").textContent = metaParts.join("　|　");
    S.$("x-watchtitle").textContent = "监听中（" + w.rules.length + " 条规则）";
    var list = S.$("x-watchlist");
    if (violations.length && w.fresh && w.fresh.length) {
      S.toast("监听发现 " + w.fresh.length + " 个不符文件，请查看监听卡", "warn");
    }
    list.textContent = "";
    var convertible = violations.filter(function (v) { return v.kind === "wrong_format"; });
    if (!violations.length) {
      list.appendChild(S.el("div", "x-watchrow", "当前没有不符合要求的文件。"));
    }
    violations.forEach(function (v) {
      var row = S.el("div", "x-watchrow");
      var flag = S.el("span", "x-flagwarn", KIND_LABEL[v.kind] || v.kind);
      row.appendChild(flag);
      row.appendChild(S.el("span", "x-name", v.name));
      row.appendChild(S.el("span", "", v.path + " · 期望 " + S.fmtLabel(v.rule_format)));
      if (v.kind === "wrong_format") {
        var btn = S.el("button", "x-mini", "转换");
        btn.type = "button";
        btn.title = "按期望格式 " + S.fmtLabel(v.rule_format) + " 转换此文件（原文件保持不变）";
        btn.addEventListener("click", function () { watchConvert([v.path]); });
        row.appendChild(btn);
      }
      list.appendChild(row);
    });
    if (convertible.length) {
      var allRow = S.el("div", "x-watchrow");
      var all = S.el("button", "x-mini", "全部转换（" + convertible.length + " 个）");
      all.type = "button";
      all.addEventListener("click", function () {
        watchConvert(convertible.map(function (v) { return v.path; }));
      });
      allRow.appendChild(all);
      list.appendChild(allRow);
    }
    list.hidden = !S.state.watchOpen;
    S.$("x-watchtoggle").textContent = S.state.watchOpen ? "收起" : "查看不符文件";
  }

  // ── 设置里的监听规则列表 ──

  function currentWatchFolderInput() {
    var row = S.state.watchBrowseRow;
    return row && row.isConnected ? row.querySelector('[data-role="folder"]') : null;
  }

  function renderWatchRules(rules) {
    var box = S.$("x-watchrules");
    box.textContent = "";
    (rules || []).forEach(function (rule) {
      box.appendChild(watchRuleRow(rule.folder || "", rule.format || "epub",
                                   !!rule.auto_convert));
    });
  }

  function watchRuleRow(folder, fmt, autoConvert) {
    var row = S.el("div", "x-ruleitem");
    var input = S.el("input", "x-input mono");
    input.type = "text";
    input.placeholder = "要监听的文件夹完整路径";
    input.value = folder;
    input.setAttribute("data-role", "folder");
    var browse = S.el("button", "x-btn x-btnsm", "浏览");
    browse.type = "button";
    browse.addEventListener("click", function () {
      S.state.watchBrowseRow = row;
      S.openBrowse("watch");
    });
    var fmtSel = S.el("select", "x-input x-rulefmt");
    fmtSel.setAttribute("aria-label", "期望格式");
    S.state.outputFormats.forEach(function (f) {
      var opt = S.el("option", "", S.fmtLabel(f));
      opt.value = f;
      if (f === fmt) opt.selected = true;
      fmtSel.appendChild(opt);
    });
    fmtSel.setAttribute("data-role", "format");
    var check = S.el("label", "x-check");
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = autoConvert;
    cb.setAttribute("data-role", "auto");
    check.appendChild(cb);
    check.appendChild(document.createTextNode("自动转换"));
    var del = S.el("button", "x-icobtn");
    del.type = "button";
    del.setAttribute("aria-label", "删除此规则");
    del.appendChild(S.icon("x"));
    del.addEventListener("click", function () { row.parentNode.removeChild(row); });
    row.appendChild(input);
    row.appendChild(browse);
    row.appendChild(fmtSel);
    row.appendChild(check);
    row.appendChild(del);
    // 行内输入框聚焦时记录为浏览目标
    input.addEventListener("focus", function () {
      S.state.watchBrowseRow = row;
    });
    return row;
  }

  function collectWatchRules() {
    var rules = [];
    Array.prototype.forEach.call(S.$("x-watchrules").children, function (row) {
      var folder = row.querySelector('[data-role="folder"]').value.trim();
      var format = row.querySelector('[data-role="format"]').value;
      var auto = row.querySelector('[data-role="auto"]').checked;
      if (folder) rules.push({ folder: folder, format: format, auto_convert: auto });
    });
    return rules;
  }

  function saveWatchFromSettings() {
    return S.api("/api/watch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules: collectWatchRules() }),
    }).then(function (w) {
      S.state.watch = w;
      renderWatch(w);
      scheduleWatchPoll();
      if (w.enabled) S.toast("文件夹监听已启用（" + w.rules.length + " 条规则）", "ok");
    });
  }

  // ── 对外导出 ──
  S.loadWatch = loadWatch;
  S.renderWatch = renderWatch;
  S.watchRuleRow = watchRuleRow;
  S.renderWatchRules = renderWatchRules;
  S.collectWatchRules = collectWatchRules;
  S.saveWatchFromSettings = saveWatchFromSettings;
  S.scheduleWatchPoll = scheduleWatchPoll;
  S.currentWatchFolderInput = currentWatchFolderInput;
})(window.Shudu);
