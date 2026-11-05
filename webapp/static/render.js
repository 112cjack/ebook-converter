/* 书渡 · render：引擎胶囊、格式按钮、任务列表、输出目录提示 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  // ── 渲染：引擎胶囊 / 引导条 ──

  function renderEngineBadge() {
    var badge = S.$("x-cal");
    var text = S.$("x-caltext");
    var guide = S.$("x-guide");
    badge.classList.remove("is-bad", "is-busy");
    if (!S.state.engine) {
      text.textContent = "正在检测 Calibre…";
      badge.classList.add("is-busy");
      guide.hidden = true;
      return;
    }
    if (S.state.engine.installed) {
      text.textContent = "Calibre 已就绪";
      badge.title = S.state.engine.path || "";
      guide.hidden = true;
    } else {
      text.textContent = "Calibre 未检测到";
      badge.classList.add("is-bad");
      badge.title = "未检测到转换引擎，点击下方按钮查看安装引导";
      guide.hidden = false;
    }
  }

  // ── 渲染：格式按钮与支持说明 ──

  function renderFormatButtons() {
    var seg = S.$("x-seg");
    seg.textContent = "";
    var ordered = S.COMMON_OUTPUTS.filter(function (f) {
      return S.state.outputFormats.indexOf(f) >= 0;
    }).concat(S.state.outputFormats.filter(function (f) {
      return S.COMMON_OUTPUTS.indexOf(f) < 0;
    }));
    ordered.forEach(function (fmt) {
      var b = S.el("button", "x-segbtn", S.fmtLabel(fmt));
      b.type = "button";
      b.setAttribute("data-to", fmt);
      b.setAttribute("aria-pressed", S.state.to === fmt ? "true" : "false");
      b.addEventListener("click", function () { selectFormat(fmt, b); });
      seg.appendChild(b);
    });
    updateAction();
  }

  function selectFormat(fmt, btn) {
    S.state.to = fmt;
    Array.prototype.forEach.call(document.querySelectorAll(".x-segbtn"), function (x) {
      x.setAttribute("aria-pressed", x === btn ? "true" : "false");
    });
    updateAction();
  }

  function renderAcceptHint() {
    var names = S.COMMON_INPUTS.map(function (f) { return "." + f; });
    S.$("x-file").setAttribute("accept", S.state.inputExtensions.join(",") || names.join(","));
    S.$("x-fmts").textContent = "支持 " + S.COMMON_INPUTS.map(S.fmtLabel).join(" · ") +
      " 等（以 Calibre 支持情况为准）";
  }

  // ── 渲染：任务列表 ──

  function latestTaskOf(uploadId) {
    var found = null;
    S.state.tasks.forEach(function (t) {
      if (t.upload_id === uploadId) found = t;
    });
    return found;
  }

  function renderList() {
    var list = S.$("x-list");
    list.textContent = "";
    var visible = S.state.uploads.filter(function (u) { return !u.removed; });
    visible.forEach(function (u) {
      list.appendChild(renderRow(u, latestTaskOf(u.id)));
    });

    var n = visible.length;
    S.$("x-count").textContent = n ? "（" + n + "）" : "";
    S.$("x-empty").style.display = n ? "none" : "";
    S.$("x-clear").disabled = !n || S.state.uploading;
    updateAction();
    updateOverall();
  }

  function renderRow(upload, task) {
    var row = S.el("div", "x-row");

    var spine = S.el("span", "x-spine");
    spine.style.background = S.SPINE[S.fmtLabel(upload.format)] || S.SPINE.TXT;
    spine.setAttribute("aria-hidden", "true");
    row.appendChild(spine);

    var file = S.el("div", "x-file");
    var nameRow = S.el("div", "x-name");
    nameRow.textContent = upload.name;
    if (upload.scanned_pdf) {
      var flag = S.el("span", "x-flagwarn", "扫描版");
      flag.title = "疑似扫描版 PDF（无文字层），转成文本格式可能内容缺失";
      nameRow.appendChild(flag);
    }
    if (upload.truncated) {
      var trunc = S.el("span", "x-flagwarn", "文件名过长已截断");
      trunc.title = "原文件名超出系统路径长度限制，已自动截断";
      nameRow.appendChild(trunc);
    }
    file.appendChild(nameRow);
    file.appendChild(S.el("div", "x-meta", S.sizeFmt(upload.size) + " · " + S.fmtLabel(upload.format)));
    row.appendChild(file);

    var pair = S.el("div", "x-pair");
    pair.appendChild(S.el("span", "x-chip", S.fmtLabel(upload.format)));
    pair.appendChild(S.icon("arrow-right"));
    var toFmt = task ? task.format_out : S.state.to;
    pair.appendChild(S.el("span", "x-chip" + (toFmt ? " x-chip-to" : ""), toFmt ? S.fmtLabel(toFmt) : "…"));
    row.appendChild(pair);

    row.appendChild(renderStatus(upload, task));
    row.appendChild(renderActs(upload, task));
    return row;
  }

  function renderStatus(upload, task) {
    var st = S.el("div", "x-status");
    if (!task || task.status === "queued") {
      st.appendChild(S.el("span", "x-badge", task ? task.status_label : "等待"));
    } else if (task.status === "converting") {
      var prow = S.el("div", "x-prow");
      var bar = S.el("div", "x-pbar");
      var fill = S.el("div", "x-pfill" + (task.progress > 0 ? "" : " is-indet"));
      fill.style.width = task.progress > 0 ? task.progress + "%" : "";
      bar.appendChild(fill);
      prow.appendChild(bar);
      prow.appendChild(S.el("span", "x-ptext",
        task.progress > 0 ? task.progress + "%" : "…"));
      st.appendChild(prow);
    } else if (task.status === "done") {
      var stamp = S.el("span", "x-stamp");
      stamp.appendChild(S.icon("check"));
      st.appendChild(stamp);
      var wrap = S.el("div");
      wrap.style.minWidth = "0";
      wrap.appendChild(S.el("div", "x-done", "已完成"));
      var outName = task.output_path ? task.output_path.split(/[\\/]/).pop() : "";
      wrap.appendChild(S.el("div", "x-out", outName));
      st.appendChild(wrap);
    } else if (task.status === "skipped") {
      var skipWrap = S.el("div", "x-failwrap");
      skipWrap.appendChild(S.el("span", "x-badge", task.status_label));
      skipWrap.appendChild(S.el("span", "x-reason", task.message || ""));
      st.appendChild(skipWrap);
    } else if (task.status === "cancelled") {
      var cw = S.el("div", "x-failwrap");
      cw.appendChild(S.el("span", "x-badge", "已取消"));
      cw.appendChild(S.el("span", "x-reason", task.message || "已取消"));
      st.appendChild(cw);
    } else {  // failed
      var fw = S.el("div", "x-failwrap");
      var f1 = S.el("span", "x-fail");
      f1.appendChild(S.icon("alert-circle"));
      f1.appendChild(document.createTextNode("转换失败"));
      fw.appendChild(f1);
      fw.appendChild(S.el("span", "x-reason", task.error || "转换失败"));
      if (task.error_detail) {
        var detail = S.el("details", "x-detail");
        var summary = S.el("summary", "", "查看详情");
        var code = S.el("code", "", task.error_detail);
        detail.appendChild(summary);
        detail.appendChild(code);
        fw.appendChild(detail);
      }
      st.appendChild(fw);
    }
    return st;
  }

  function renderActs(upload, task) {
    var acts = S.el("div", "x-acts");
    var busy = task && (task.status === "queued" || task.status === "converting");
    if (task && task.status === "done") {
      var open = S.el("button", "x-mini", "打开文件夹");
      open.type = "button";
      open.insertBefore(S.icon("folder-open"), open.firstChild);
      open.addEventListener("click", function () { S.openFolder(task.output_dir); });
      acts.appendChild(open);
      var openf = S.el("button", "x-mini", "打开文件");
      openf.type = "button";
      openf.title = "用系统默认程序打开 " + (task.output_path || "").split(/[\\/]/).pop();
      openf.addEventListener("click", function () {
        S.api("/api/open-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: task.output_path }),
        }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
      });
      acts.appendChild(openf);
    }
    if (task && task.status === "failed") {
      var retry = S.el("button", "x-mini", "重试");
      retry.type = "button";
      retry.insertBefore(S.icon("rotate-ccw"), retry.firstChild);
      retry.addEventListener("click", function () { S.retryTask(upload.id, task.format_out, false); });
      acts.appendChild(retry);
    }
    if (task && (task.status === "done" || task.status === "skipped" || task.status === "cancelled")) {
      var re = S.el("button", "x-mini", task.status === "done" ? "重新转换" : "重新转换");
      re.type = "button";
      re.title = "覆盖旧输出并重新转换";
      re.addEventListener("click", function () { S.retryTask(upload.id, task.format_out, true); });
      acts.appendChild(re);
    }
    if (task && task.status === "converting") {
      var cancel = S.el("button", "x-mini", "取消");
      cancel.type = "button";
      cancel.addEventListener("click", function () { S.cancelTask(task.id); });
      acts.appendChild(cancel);
    }
    if (!busy) {
      var rm = S.el("button", "x-icobtn");
      rm.type = "button";
      rm.setAttribute("aria-label", "移除 " + upload.name);
      rm.appendChild(S.icon("x"));
      rm.addEventListener("click", function () { S.removeUploads([upload.id]); });
      acts.appendChild(rm);
    }
    return acts;
  }

  function renderOutdirHint() {
    var path = S.state.outputDir || S.state.lastOutputDir ||
      (S.state.settings && S.state.settings.output_dir) || "";
    S.$("x-outdir-text").textContent = path || "默认目录（程序目录下 converted）";
  }

  function updateAction() {
    var waiting = S.state.uploads.filter(function (u) {
      return !u.removed && !latestTaskOf(u.id);
    }).length;
    var go = S.$("x-go");
    go.disabled = !S.state.to || !waiting || !S.engineReady();
    Array.prototype.forEach.call(document.querySelectorAll(".x-segbtn"), function (b) {
      b.disabled = S.state.uploading;
    });
    var helper = S.$("x-helper");
    if (!S.state.engine) helper.textContent = "正在检测引擎…";
    else if (!S.engineReady()) helper.textContent = "未检测到转换引擎，暂时无法转换";
    else if (!S.state.to) helper.textContent = "请先选择输出格式";
    else if (waiting) helper.textContent = "输出为 " + S.fmtLabel(S.state.to) + " · 待转换 " + waiting + " 个文件";
    else helper.textContent = "输出为 " + S.fmtLabel(S.state.to) + " · 没有待转换文件";
  }

  function updateOverall() {
    var total = S.state.uploads.filter(function (u) { return !u.removed; }).length;
    var settled = S.state.tasks.filter(function (t) {
      var u = S.state.uploads.find(function (x) { return x.id === t.upload_id; });
      return u && !u.removed && t.status !== "queued" && t.status !== "converting"
        && latestTaskOf(t.upload_id) === t;
    }).length;
    S.$("x-ofill").style.width = total ? Math.round(settled / total * 100) + "%" : "0%";
    S.$("x-otext").textContent = settled + "/" + total;

    var allDone = total > 0 && settled === total &&
      S.state.tasks.some(function (t) { return t.status === "done"; });
    var openBtn = S.$("x-openout");
    openBtn.hidden = !allDone;
    if (allDone) {
      for (var i = S.state.tasks.length - 1; i >= 0; i--) {
        if (S.state.tasks[i].status === "done" && S.state.tasks[i].output_dir) {
          S.state.lastOutputDir = S.state.tasks[i].output_dir;
          break;
        }
      }
      renderOutdirHint();
    }
  }

  // ── 对外导出 ──
  S.renderEngineBadge = renderEngineBadge;
  S.renderFormatButtons = renderFormatButtons;
  S.renderAcceptHint = renderAcceptHint;
  S.renderList = renderList;
  S.renderOutdirHint = renderOutdirHint;
  S.updateAction = updateAction;
  S.updateOverall = updateOverall;
  S.latestTaskOf = latestTaskOf;
})(window.Shudu);
