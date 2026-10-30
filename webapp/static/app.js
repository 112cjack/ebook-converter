/* 电子书转换器 · 前端逻辑
 * 数据同步：页面加载取 /api/status 与 /api/tasks；提交转换后轮询
 * /api/tasks（进行中 1 秒/次，空闲 3 秒/次）。所有动态文本经 textContent 写入。
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var FMT_LABEL = {
    epub: "EPUB", mobi: "MOBI", azw3: "AZW3", pdf: "PDF", txt: "TXT", docx: "DOCX",
    rtf: "RTF", fb2: "FB2", odt: "ODT", htmlz: "HTMLZ",
  };
  var SPINE = {
    EPUB: "light-dark(#2E6E5E,#4E9382)", MOBI: "light-dark(#B0803A,#C99A55)",
    PDF: "light-dark(#4A5560,#7C8794)", TXT: "light-dark(#8A8578,#A8A294)",
    AZW3: "light-dark(#3E5C76,#6E8DA8)", DOCX: "light-dark(#7A5E8C,#A38BB4)",
  };
  var COMMON_INPUTS = ["epub", "mobi", "azw3", "pdf", "txt", "docx"];
  var COMMON_OUTPUTS = ["epub", "pdf", "txt", "mobi"];

  var state = {
    engine: null,
    outputFormats: [],
    inputExtensions: [],
    uploads: [],
    tasks: [],
    to: null,
    timer: null,
    wasBusy: false,
    lastOutputDir: null,
    uploading: false,
  };

  // ── 基础工具 ──

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function icon(name) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ic");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }
  function sizeFmt(n) {
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
    if (n >= 1024) return Math.round(n / 1024) + " KB";
    return n + " B";
  }
  function fmtLabel(fmt) { return FMT_LABEL[fmt] || String(fmt || "").toUpperCase(); }
  function announce(msg) { var live = $("x-live"); if (live) live.textContent = msg; }

  function toast(msg, kind) {
    var box = $("x-toasts");
    var d = el("div", "x-toast" + (kind === "warn" ? " is-warn" : kind === "ok" ? " is-ok" : ""));
    d.setAttribute("role", "status");
    d.textContent = msg;
    box.appendChild(d);
    setTimeout(function () { if (d.parentNode) d.parentNode.removeChild(d); }, 4500);
  }

  function api(path, options) {
    return fetch(path, options).then(function (resp) {
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

  // ── 状态加载与轮询 ──

  function loadStatus() {
    return api("/api/status").then(function (body) {
      state.engine = body.engine;
      state.outputFormats = body.output_formats || [];
      state.inputExtensions = body.input_extensions || [];
      renderEngineBadge();
      renderFormatButtons();
      renderAcceptHint();
    });
  }

  function refreshTasks() {
    return api("/api/tasks").then(function (body) {
      state.uploads = body.uploads || [];
      state.tasks = body.tasks || [];
      var busy = state.tasks.some(function (t) {
        return t.status === "queued" || t.status === "converting";
      });
      if (state.wasBusy && !busy) onAllSettled();
      state.wasBusy = busy;
      renderList();
      schedulePoll(busy ? 1000 : 3000);
    }).catch(function () {
      schedulePoll(3000);  // 服务未就绪或瞬时错误，稍后重试
    });
  }

  function schedulePoll(delay) {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(refreshTasks, delay);
  }

  function onAllSettled() {
    var done = state.tasks.filter(function (t) { return t.status === "done"; }).length;
    var failed = state.tasks.filter(function (t) { return t.status === "failed"; }).length;
    var msg;
    if (done && failed) msg = "转换完成：成功 " + done + " 个，失败 " + failed + " 个";
    else if (failed) msg = "转换结束：" + failed + " 个文件失败";
    else msg = "全部转换完成，共 " + done + " 个文件";
    toast(msg, failed ? "warn" : "ok");
    announce(msg);
  }

  // ── 渲染：引擎胶囊 / 引导条 ──

  function renderEngineBadge() {
    var badge = $("x-cal");
    var text = $("x-caltext");
    var guide = $("x-guide");
    badge.classList.remove("is-bad", "is-busy");
    if (!state.engine) {
      text.textContent = "正在检测 Calibre…";
      badge.classList.add("is-busy");
      guide.hidden = true;
      return;
    }
    if (state.engine.installed) {
      text.textContent = "Calibre 已就绪";
      badge.title = state.engine.path || "";
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
    var seg = $("x-seg");
    seg.textContent = "";
    var ordered = COMMON_OUTPUTS.filter(function (f) {
      return state.outputFormats.indexOf(f) >= 0;
    }).concat(state.outputFormats.filter(function (f) {
      return COMMON_OUTPUTS.indexOf(f) < 0;
    }));
    ordered.forEach(function (fmt) {
      var b = el("button", "x-segbtn", fmtLabel(fmt));
      b.type = "button";
      b.setAttribute("data-to", fmt);
      b.setAttribute("aria-pressed", state.to === fmt ? "true" : "false");
      b.addEventListener("click", function () { selectFormat(fmt, b); });
      seg.appendChild(b);
    });
    updateAction();
  }

  function selectFormat(fmt, btn) {
    state.to = fmt;
    Array.prototype.forEach.call(document.querySelectorAll(".x-segbtn"), function (x) {
      x.setAttribute("aria-pressed", x === btn ? "true" : "false");
    });
    updateAction();
  }

  function renderAcceptHint() {
    var names = COMMON_INPUTS.map(function (f) { return "." + f; });
    $("x-file").setAttribute("accept", state.inputExtensions.join(",") || names.join(","));
    $("x-fmts").textContent = "支持 " + COMMON_INPUTS.map(fmtLabel).join(" · ") +
      " 等（以 Calibre 支持情况为准）";
  }

  // ── 渲染：任务列表 ──

  function latestTaskOf(uploadId) {
    var found = null;
    state.tasks.forEach(function (t) {
      if (t.upload_id === uploadId) found = t;
    });
    return found;
  }

  function renderList() {
    var list = $("x-list");
    list.textContent = "";
    var visible = state.uploads.filter(function (u) { return !u.removed; });
    visible.forEach(function (u) {
      list.appendChild(renderRow(u, latestTaskOf(u.id)));
    });

    var n = visible.length;
    $("x-count").textContent = n ? "（" + n + "）" : "";
    $("x-empty").style.display = n ? "none" : "";
    $("x-clear").disabled = !n || state.uploading;
    updateAction();
    updateOverall();
  }

  function renderRow(upload, task) {
    var row = el("div", "x-row");

    var spine = el("span", "x-spine");
    spine.style.background = SPINE[fmtLabel(upload.format)] || SPINE.TXT;
    spine.setAttribute("aria-hidden", "true");
    row.appendChild(spine);

    var file = el("div", "x-file");
    file.appendChild(el("div", "x-name", upload.name));
    file.appendChild(el("div", "x-meta", sizeFmt(upload.size) + " · " + fmtLabel(upload.format)));
    row.appendChild(file);

    var pair = el("div", "x-pair");
    pair.appendChild(el("span", "x-chip", fmtLabel(upload.format)));
    pair.appendChild(icon("arrow-right"));
    var toFmt = task ? task.format_out : state.to;
    pair.appendChild(el("span", "x-chip" + (toFmt ? " x-chip-to" : ""), toFmt ? fmtLabel(toFmt) : "…"));
    row.appendChild(pair);

    row.appendChild(renderStatus(upload, task));
    row.appendChild(renderActs(upload, task));
    return row;
  }

  function renderStatus(upload, task) {
    var st = el("div", "x-status");
    if (!task || task.status === "queued") {
      st.appendChild(el("span", "x-badge", task ? task.status_label : "等待"));
    } else if (task.status === "converting") {
      var prow = el("div", "x-prow");
      var bar = el("div", "x-pbar");
      var fill = el("div", "x-pfill" + (task.progress > 0 ? "" : " is-indet"));
      fill.style.width = task.progress > 0 ? task.progress + "%" : "";
      bar.appendChild(fill);
      prow.appendChild(bar);
      prow.appendChild(el("span", "x-ptext",
        task.progress > 0 ? task.progress + "%" : "…"));
      st.appendChild(prow);
    } else if (task.status === "done") {
      var stamp = el("span", "x-stamp");
      stamp.appendChild(icon("check"));
      st.appendChild(stamp);
      var wrap = el("div");
      wrap.style.minWidth = "0";
      wrap.appendChild(el("div", "x-done", "已完成"));
      var outName = task.output_path ? task.output_path.split(/[\\/]/).pop() : "";
      wrap.appendChild(el("div", "x-out", outName));
      st.appendChild(wrap);
    } else if (task.status === "skipped") {
      var skipWrap = el("div", "x-failwrap");
      skipWrap.appendChild(el("span", "x-badge", "已跳过"));
      skipWrap.appendChild(el("span", "x-reason", task.message || ""));
      st.appendChild(skipWrap);
    } else {  // failed
      var fw = el("div", "x-failwrap");
      var f1 = el("span", "x-fail");
      f1.appendChild(icon("alert-circle"));
      f1.appendChild(document.createTextNode("转换失败"));
      fw.appendChild(f1);
      fw.appendChild(el("span", "x-reason", task.error || "转换失败"));
      st.appendChild(fw);
    }
    return st;
  }

  function renderActs(upload, task) {
    var acts = el("div", "x-acts");
    var busy = task && (task.status === "queued" || task.status === "converting");
    if (task && task.status === "done") {
      var open = el("button", "x-mini", "打开文件夹");
      open.type = "button";
      open.insertBefore(icon("folder-open"), open.firstChild);
      open.addEventListener("click", function () { openFolder(task.output_dir); });
      acts.appendChild(open);
    }
    if (task && task.status === "failed") {
      var retry = el("button", "x-mini", "重试");
      retry.type = "button";
      retry.insertBefore(icon("rotate-ccw"), retry.firstChild);
      retry.addEventListener("click", function () { retryTask(upload.id, task.format_out); });
      acts.appendChild(retry);
    }
    if (!busy) {
      var rm = el("button", "x-icobtn");
      rm.type = "button";
      rm.setAttribute("aria-label", "移除 " + upload.name);
      rm.appendChild(icon("x"));
      rm.addEventListener("click", function () { removeUploads([upload.id]); });
      acts.appendChild(rm);
    }
    return acts;
  }

  function updateAction() {
    var waiting = state.uploads.filter(function (u) {
      return !u.removed && !latestTaskOf(u.id);
    }).length;
    var go = $("x-go");
    go.disabled = !state.to || !waiting;
    Array.prototype.forEach.call(document.querySelectorAll(".x-segbtn"), function (b) {
      b.disabled = state.uploading;
    });
    var helper = $("x-helper");
    if (!state.to) helper.textContent = "请先选择输出格式";
    else if (waiting) helper.textContent = "输出为 " + fmtLabel(state.to) + " · 待转换 " + waiting + " 个文件";
    else helper.textContent = "输出为 " + fmtLabel(state.to) + " · 没有待转换文件";
  }

  function updateOverall() {
    var total = state.uploads.filter(function (u) { return !u.removed; }).length;
    var settled = state.tasks.filter(function (t) {
      var u = state.uploads.find(function (x) { return x.id === t.upload_id; });
      return u && !u.removed && t.status !== "queued" && t.status !== "converting"
        && latestTaskOf(t.upload_id) === t;
    }).length;
    $("x-ofill").style.width = total ? Math.round(settled / total * 100) + "%" : "0%";
    $("x-otext").textContent = settled + "/" + total;

    var allDone = total > 0 && settled === total &&
      state.tasks.some(function (t) { return t.status === "done"; });
    var openBtn = $("x-openout");
    openBtn.hidden = !allDone;
    if (allDone) {
      for (var i = state.tasks.length - 1; i >= 0; i--) {
        if (state.tasks[i].status === "done" && state.tasks[i].output_dir) {
          state.lastOutputDir = state.tasks[i].output_dir;
          break;
        }
      }
    }
  }

  // ── 动作 ──

  function addFiles(fileList) {
    if (!fileList || !fileList.length) return;
    if (state.uploading) return;
    var form = new FormData();
    var count = 0;
    Array.prototype.forEach.call(fileList, function (f) {
      form.append("files", f, f.name);
      count++;
    });
    state.uploading = true;
    $("x-uploading").hidden = false;
    renderList();
    api("/api/upload", { method: "POST", body: form }).then(function (body) {
      if (body.uploads.length) {
        announce("已添加 " + body.uploads.length + " 个文件");
        toast("已添加 " + body.uploads.length + " 个文件", "ok");
      }
      (body.rejected || []).forEach(function (r) {
        toast("已跳过 " + r.name + "：" + r.reason, "warn");
      });
      return refreshTasks();
    }).catch(function (err) {
      toast(err.message, "warn");
    }).finally(function () {
      state.uploading = false;
      $("x-uploading").hidden = true;
      $("x-file").value = "";
      renderList();
    });
  }

  function startConvert() {
    if (!state.to) { toast("请先选择输出格式", "warn"); return; }
    var waiting = state.uploads.filter(function (u) {
      return !u.removed && !latestTaskOf(u.id);
    }).map(function (u) { return u.id; });
    if (!waiting.length) { toast("没有待转换的文件", "warn"); return; }
    api("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: state.to, upload_ids: waiting }),
    }).then(function () {
      announce("开始转换，共 " + waiting.length + " 个文件");
      state.wasBusy = true;
      return refreshTasks();
    }).catch(function (err) {
      toast(err.message, "warn");
      if (err.body && err.body.engine && err.body.engine.installed === false) {
        renderEngineBadge();
        $("x-guidedlg").showModal();
      }
      refreshTasks();
    });
  }

  function retryTask(uploadId, format) {
    api("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: format, upload_ids: [uploadId] }),
    }).then(function () {
      toast("已重新加入队列", "ok");
      state.wasBusy = true;
      return refreshTasks();
    }).catch(function (err) { toast(err.message, "warn"); });
  }

  function removeUploads(ids) {
    api("/api/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_ids: ids }),
    }).then(function (body) {
      if (body.busy && body.busy.length) toast("转换中的文件暂不能移除", "warn");
      return refreshTasks();
    }).catch(function (err) { toast(err.message, "warn"); });
  }

  function clearList() {
    api("/api/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }).then(function () {
      announce("列表已清空");
      return refreshTasks();
    }).catch(function (err) { toast(err.message, "warn"); });
  }

  function openFolder(path) {
    if (!path) { toast("暂无可打开的输出目录", "warn"); return; }
    api("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path }),
    }).catch(function (err) { toast(err.message, "warn"); });
  }

  // ── 对话框 ──

  function openSettings() {
    api("/api/settings").then(function (body) {
      $("x-outdir").value = body.output_dir || "";
      $("x-calpath").value = body.engine_path || "";
      $("x-limit").value = body.upload_limit_mb || 200;
      $("x-setdlg").showModal();
    }).catch(function (err) { toast(err.message, "warn"); });
  }

  function saveSettings() {
    api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        output_dir: $("x-outdir").value.trim(),
        engine_path: $("x-calpath").value.trim(),
        upload_limit_mb: parseInt($("x-limit").value, 10),
      }),
    }).then(function () {
      $("x-setdlg").close();
      toast("设置已保存", "ok");
      state.engine = null;  // 引擎路径可能变化，重新检测
      return loadStatus();
    }).catch(function (err) { toast(err.message, "warn"); });
  }

  function openHistory() {
    var bodyEl = $("x-histbody");
    bodyEl.textContent = "";
    var rows = state.tasks.slice().reverse();
    if (!rows.length) {
      bodyEl.appendChild(el("div", "x-hempty", "本次运行还没有转换记录。"));
    }
    rows.forEach(function (t) {
      var row = el("div", "x-hrow");
      row.appendChild(el("span", "x-htime", fmtTime(t.finished_at || t.created_at)));
      row.appendChild(el("span", "x-hname", t.name));
      row.appendChild(el("span", "x-meta", fmtLabel(t.format_in) + " → " + fmtLabel(t.format_out)));
      var note = t.status === "done" ? "完成"
        : t.status === "failed" ? (t.error || "失败")
        : (t.message || t.status_label);
      row.appendChild(el("span",
        t.status === "done" ? "x-hst-ok" : t.status === "failed" ? "x-hst-bad" : "x-hst-skip",
        note));
      bodyEl.appendChild(row);
    });
    $("x-histdlg").showModal();
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    var pad = function (x) { return (x < 10 ? "0" : "") + x; };
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  // ── 事件绑定 ──

  $("x-file").addEventListener("change", function (e) {
    addFiles(e.target.files);
  });
  var drop = $("x-drop");
  ["dragenter", "dragover"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      drop.classList.add("is-over");
    });
  });
  drop.addEventListener("dragleave", function (e) {
    if (!drop.contains(e.relatedTarget)) drop.classList.remove("is-over");
  });
  drop.addEventListener("drop", function (e) {
    e.preventDefault();
    drop.classList.remove("is-over");
    if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });

  $("x-go").addEventListener("click", startConvert);
  $("x-clear").addEventListener("click", clearList);
  $("x-openout").addEventListener("click", function () { openFolder(state.lastOutputDir); });

  $("x-setbtn").addEventListener("click", openSettings);
  $("x-setclose").addEventListener("click", function () { $("x-setdlg").close(); });
  $("x-setcancel").addEventListener("click", function () { $("x-setdlg").close(); });
  $("x-setsave").addEventListener("click", saveSettings);

  $("x-histbtn").addEventListener("click", openHistory);
  $("x-histclose").addEventListener("click", function () { $("x-histdlg").close(); });
  $("x-histok").addEventListener("click", function () { $("x-histdlg").close(); });

  $("x-guidebtn").addEventListener("click", function () { $("x-guidedlg").showModal(); });
  $("x-guideclose").addEventListener("click", function () { $("x-guidedlg").close(); });
  $("x-guideok").addEventListener("click", function () { $("x-guidedlg").close(); });
  $("x-guideset").addEventListener("click", function () {
    $("x-guidedlg").close();
    openSettings();
  });
  $("x-copywinget").addEventListener("click", function () {
    var text = $("x-winget").textContent;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { toast("已复制安装命令", "ok"); },
        function () { toast("复制失败，请手动选择命令复制", "warn"); });
    }
  });

  // ── 启动 ──
  loadStatus().then(refreshTasks, refreshTasks);
})();
