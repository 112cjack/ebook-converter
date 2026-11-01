/* 书渡（电子书转换器）· 前端逻辑
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
    outputDir: null,   // 用户在目录浏览器中显式选定，优先于 lastOutputDir
    guideShown: false,
    uploading: false,
    frozen: false,
    settings: {},
    watch: null,          // GET /api/watch 快照
    watchTimer: null,
    watchOpen: false,     // 状态卡违规列表展开状态
    browseTarget: "output", // 目录浏览器当前服务的目标：output | watch
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

  function showConnBanner(visible) {
    var bar = $("x-connbar");
    if (bar) bar.hidden = !visible;
  }

  var CONN_MSG = "无法连接本地服务，程序可能已关闭——请重新打开程序，再刷新本页面。";

  function api(path, options) {
    return fetch(path, options).catch(function () {
      showConnBanner(true);
      var err = new Error(CONN_MSG);
      err.network = true;
      throw err;
    }).then(function (resp) {
      showConnBanner(false);
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

  function engineReady() {
    return !!(state.engine && state.engine.installed);
  }

  function loadStatus() {
    return api("/api/status").then(function (body) {
      state.engine = body.engine;
      state.outputFormats = body.output_formats || [];
      state.inputExtensions = body.input_extensions || [];
      state.settings = body.settings || {};
      state.frozen = !!body.frozen;
      renderEngineBadge();
      renderFormatButtons();
      renderAcceptHint();
      renderOutdirHint();
      if (state.engine && !state.engine.installing) {
        if (state.engine.installed) {
          if (state.engine.version && !state._announcedEngine) {
            toast("Calibre 已就绪 · " + state.engine.version, "ok");
            state._announcedEngine = true;
          }
        } else if (!state.guideShown) {
          state.guideShown = true;
          $("x-guidedlg").showModal();
        }
      }
    }).catch(function (err) {
      // 状态获取失败时置回"检测中"，不留过期画面（避免与轮询侧显示矛盾）
      state.engine = null;
      state._announcedEngine = false;
      renderEngineBadge();
      throw err;
    });
  }

  function refreshTasks() {
    return api("/api/tasks").then(function (body) {
      state.uploads = body.uploads || [];
      state.tasks = body.tasks || [];
      // 引擎状态随轮询持续同步：保证胶囊/引导条/提示行三者永远一致
      if (body.engine) {
        state.engine = body.engine;
        renderEngineBadge();
      }
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
    notifyDesktop(msg);
  }

  function notifyDesktop(msg) {
    // 页面在前台时 toast 足够；仅在后台标签页用系统通知提醒
    if (!("Notification" in window) || document.hasFocus()) return;
    if (Notification.permission === "granted") {
      try { new Notification("书渡", { body: msg }); } catch (e) { /* 部分环境不支持 */ }
    }
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
    var nameRow = el("div", "x-name");
    nameRow.textContent = upload.name;
    if (upload.scanned_pdf) {
      var flag = el("span", "x-flagwarn", "扫描版");
      flag.title = "疑似扫描版 PDF（无文字层），转成文本格式可能内容缺失";
      nameRow.appendChild(flag);
    }
    if (upload.truncated) {
      var trunc = el("span", "x-flagwarn", "文件名过长已截断");
      trunc.title = "原文件名超出系统路径长度限制，已自动截断";
      nameRow.appendChild(trunc);
    }
    file.appendChild(nameRow);
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
      skipWrap.appendChild(el("span", "x-badge", task.status_label));
      skipWrap.appendChild(el("span", "x-reason", task.message || ""));
      st.appendChild(skipWrap);
    } else if (task.status === "cancelled") {
      var cw = el("div", "x-failwrap");
      cw.appendChild(el("span", "x-badge", "已取消"));
      cw.appendChild(el("span", "x-reason", task.message || "已取消"));
      st.appendChild(cw);
    } else {  // failed
      var fw = el("div", "x-failwrap");
      var f1 = el("span", "x-fail");
      f1.appendChild(icon("alert-circle"));
      f1.appendChild(document.createTextNode("转换失败"));
      fw.appendChild(f1);
      fw.appendChild(el("span", "x-reason", task.error || "转换失败"));
      if (task.error_detail) {
        var detail = el("details", "x-detail");
        var summary = el("summary", "", "查看详情");
        var code = el("code", "", task.error_detail);
        detail.appendChild(summary);
        detail.appendChild(code);
        fw.appendChild(detail);
      }
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
      var openf = el("button", "x-mini", "打开文件");
      openf.type = "button";
      openf.title = "用系统默认程序打开 " + (task.output_path || "").split(/[\\/]/).pop();
      openf.addEventListener("click", function () {
        api("/api/open-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: task.output_path }),
        }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
      });
      acts.appendChild(openf);
    }
    if (task && task.status === "failed") {
      var retry = el("button", "x-mini", "重试");
      retry.type = "button";
      retry.insertBefore(icon("rotate-ccw"), retry.firstChild);
      retry.addEventListener("click", function () { retryTask(upload.id, task.format_out, false); });
      acts.appendChild(retry);
    }
    if (task && (task.status === "done" || task.status === "skipped" || task.status === "cancelled")) {
      var re = el("button", "x-mini", task.status === "done" ? "重新转换" : "重新转换");
      re.type = "button";
      re.title = "覆盖旧输出并重新转换";
      re.addEventListener("click", function () { retryTask(upload.id, task.format_out, true); });
      acts.appendChild(re);
    }
    if (task && task.status === "converting") {
      var cancel = el("button", "x-mini", "取消");
      cancel.type = "button";
      cancel.addEventListener("click", function () { cancelTask(task.id); });
      acts.appendChild(cancel);
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

  function renderOutdirHint() {
    var path = state.outputDir || state.lastOutputDir ||
      (state.settings && state.settings.output_dir) || "";
    $("x-outdir-text").textContent = path || "默认目录（程序目录下 converted）";
  }

  function updateAction() {
    var waiting = state.uploads.filter(function (u) {
      return !u.removed && !latestTaskOf(u.id);
    }).length;
    var go = $("x-go");
    go.disabled = !state.to || !waiting || !engineReady();
    Array.prototype.forEach.call(document.querySelectorAll(".x-segbtn"), function (b) {
      b.disabled = state.uploading;
    });
    var helper = $("x-helper");
    if (!state.engine) helper.textContent = "正在检测引擎…";
    else if (!engineReady()) helper.textContent = "未检测到转换引擎，暂时无法转换";
    else if (!state.to) helper.textContent = "请先选择输出格式";
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
      renderOutdirHint();
    }
  }

  // ── 目录浏览器 ──

  var browseCurrent = null;
  var browseParent = null;

  function openBrowse(target) {
    state.browseTarget = target || "output";
    browseCurrent = state.browseTarget === "watch"
      ? $("x-watchfolder").value.trim() || null
      : (state.outputDir || state.lastOutputDir || null);
    browseParent = null;
    $("x-browsedlg").showModal();
    loadBrowse(browseCurrent);
  }

  function loadBrowse(path) {
    var url = path ? "/api/browse?path=" + encodeURIComponent(path) : "/api/browse";
    api(url).then(function (body) {
      browseCurrent = body.current;
      browseParent = body.parent;
      $("x-browsecwd").textContent = body.current || "本机";
      $("x-browseup").disabled = !body.parent;
      var list = $("x-browsebody");
      list.textContent = "";
      if (!body.entries.length) {
        list.appendChild(el("div", "x-browseempty", "此目录下没有子文件夹。"));
        return;
      }
      body.entries.forEach(function (entry) {
        var row = el("button", "x-browserow");
        row.type = "button";
        row.appendChild(icon("folder-open"));
        row.appendChild(document.createTextNode(entry.name));
        row.addEventListener("click", function () { loadBrowse(entry.path); });
        list.appendChild(row);
      });
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
    });
  }

  function chooseBrowse() {
    if (browseCurrent) {
      if (state.browseTarget === "watch") {
        $("x-watchfolder").value = browseCurrent;
      } else {
        state.outputDir = browseCurrent;
        renderOutdirHint();
        toast("输出目录已选定：" + browseCurrent, "ok");
      }
    }
    $("x-browsedlg").close();
  }

  // ── 文件夹监听（F8）──

  var KIND_LABEL = { unconvertible: "无法转换", wrong_format: "格式不符" };

  function loadWatch() {
    return api("/api/watch").then(function (body) {
      state.watch = body;
      renderWatch(body);
      if (body.enabled && !state.watchTimer) {
        state.watchTimer = setTimeout(loadWatch, 5000);
      }
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
      state.watchTimer = setTimeout(loadWatch, 8000);
    });
  }

  function scheduleWatchPoll() {
    if (state.watchTimer) clearTimeout(state.watchTimer);
    state.watchTimer = null;
    if (state.watch && state.watch.enabled) {
      state.watchTimer = setTimeout(loadWatch, 5000);
    }
  }

  function watchConvert(paths) {
    if (!paths || !paths.length) return;
    api("/api/watch-convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: paths }),
    }).then(function (body) {
      toast("已把 " + body.tasks.length + " 个文件加入转换队列", "ok");
      state.wasBusy = true;
      refreshTasks();
      return loadWatch();
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
    });
  }

  function renderWatch(w) {
    var card = $("x-watchcard");
    if (!w || !w.enabled) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    var meta;
    if (w.reachable === false) {
      meta = "文件夹暂时不可达：" + w.folder;
    } else {
      var n = (w.violations || []).length;
      meta = w.folder + " · 期望 " + fmtLabel(w.format) +
        (n ? " · " + n + " 个不符文件" : " · 格式全部符合");
    }
    $("x-watchmeta").textContent = meta;
    $("x-watchtitle").textContent = "监听中";
    var list = $("x-watchlist");
    var violations = w.violations || [];
    if (violations.length && w.fresh && w.fresh.length) {
      toast("监听发现 " + w.fresh.length + " 个不符文件，请查看监听卡", "warn");
    }
    list.textContent = "";
    var convertible = violations.filter(function (v) { return v.kind === "wrong_format"; });
    if (!violations.length) {
      list.appendChild(el("div", "x-watchrow", "当前没有不符合要求的文件。"));
    }
    violations.forEach(function (v) {
      var row = el("div", "x-watchrow");
      var flag = el("span", "x-flagwarn", KIND_LABEL[v.kind] || v.kind);
      row.appendChild(flag);
      row.appendChild(el("span", "x-name", v.name));
      row.appendChild(el("span", "", v.path));
      if (v.kind === "wrong_format") {
        var btn = el("button", "x-mini", "转换");
        btn.type = "button";
        btn.title = "按期望格式 " + fmtLabel(w.format) + " 转换此文件（原文件保持不变）";
        btn.addEventListener("click", function () { watchConvert([v.path]); });
        row.appendChild(btn);
      }
      list.appendChild(row);
    });
    if (convertible.length) {
      var allRow = el("div", "x-watchrow");
      var all = el("button", "x-mini", "全部转换（" + convertible.length + " 个）");
      all.type = "button";
      all.addEventListener("click", function () {
        watchConvert(convertible.map(function (v) { return v.path; }));
      });
      allRow.appendChild(all);
      list.appendChild(allRow);
    }
    list.hidden = !state.watchOpen;
    $("x-watchtoggle").textContent = state.watchOpen ? "收起" : "查看不符文件";
  }

  function saveWatchFromSettings() {
    var body = {
      enabled: $("x-watchon").checked,
      folder: $("x-watchfolder").value.trim(),
      format: $("x-watchformat").value,
    };
    return api("/api/watch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (w) {
      state.watch = w;
      renderWatch(w);
      scheduleWatchPoll();
      if (w.enabled) toast("文件夹监听已启用", "ok");
    });
  }

  // ── 动作 ──

  function uploadWithProgress(form, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded * 100 / e.total));
      };
      xhr.onload = function () {
        showConnBanner(false);
        var body = {};
        try { body = JSON.parse(xhr.responseText); } catch (e) { /* 非 JSON 响应 */ }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body);
        } else {
          var err = new Error(body.error || ("请求失败（" + xhr.status + "）"));
          err.status = xhr.status;
          err.body = body;
          reject(err);
        }
      };
      xhr.onerror = function () {
        showConnBanner(true);
        var err = new Error(CONN_MSG);
        err.network = true;
        reject(err);
      };
      xhr.send(form);
    });
  }

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
    var progressEl = $("x-uploading");
    progressEl.hidden = false;
    progressEl.textContent = "正在上传… 0%";
    renderList();
    uploadWithProgress(form, function (pct) {
      progressEl.textContent = "正在上传… " + pct + "%";
    }).then(function (body) {
      if (body.uploads.length) {
        announce("已添加 " + body.uploads.length + " 个文件");
        toast("已添加 " + body.uploads.length + " 个文件", "ok");
      }
      (body.rejected || []).forEach(function (r) {
        toast("已跳过 " + r.name + "：" + r.reason, "warn");
      });
      return refreshTasks();
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
    }).finally(function () {
      state.uploading = false;
      progressEl.hidden = true;
      progressEl.textContent = "正在上传…";
      $("x-file").value = "";
      renderList();
    });
  }

  function startConvert() {
    if (!state.to) { toast("请先选择输出格式", "warn"); return; }
    if (!engineReady()) { toast("未检测到转换引擎，请先安装或指定 Calibre", "warn"); return; }
    var waiting = state.uploads.filter(function (u) {
      return !u.removed && !latestTaskOf(u.id);
    }).map(function (u) { return u.id; });
    if (!waiting.length) { toast("没有待转换的文件", "warn"); return; }
    var body = { format: state.to, upload_ids: waiting };
    var outDir = state.outputDir || state.lastOutputDir;
    if (outDir) body.output_dir = outDir;
    api("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function () {
      announce("开始转换，共 " + waiting.length + " 个文件");
      state.wasBusy = true;
      // 大文件转换期间用户常切走标签页，提前请求通知权限（用户手势内）
      if ("Notification" in window && Notification.permission === "default") {
        try { Notification.requestPermission(); } catch (e) { /* 忽略 */ }
      }
      return refreshTasks();
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
      if (err.body && err.body.engine && err.body.engine.installed === false) {
        renderEngineBadge();
        $("x-guidedlg").showModal();
      }
      refreshTasks();
    });
  }

  function retryTask(uploadId, format, overwrite) {
    var body = { format: format, upload_ids: [uploadId] };
    if (overwrite) body.overwrite = true;
    api("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function () {
      toast(overwrite ? "已重新开始转换（将覆盖旧输出）" : "已重新加入队列", "ok");
      state.wasBusy = true;
      return refreshTasks();
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  }

  function cancelTask(taskId) {
    api("/api/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    }).then(function () {
      return refreshTasks();
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  }

  function removeUploads(ids) {
    api("/api/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_ids: ids }),
    }).then(function (body) {
      if (body.busy && body.busy.length) toast("转换中的文件暂不能移除", "warn");
      return refreshTasks();
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  }

  function clearList() {
    api("/api/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }).then(function () {
      announce("列表已清空");
      return refreshTasks();
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  }

  function openFolder(path) {
    if (!path) { toast("暂无可打开的输出目录", "warn"); return; }
    api("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path }),
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  }

  // ── 对话框 ──

  function openSettings() {
    var watchReady = api("/api/watch").then(function (w) {
      state.watch = w;
      $("x-watchon").checked = !!w.enabled;
      $("x-watchfolder").value = w.folder || "";
      renderWatchFormatOptions(w.format);
      scheduleWatchPoll();
      return w;
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
    });
    api("/api/settings").then(function (body) {
      $("x-outdir").value = body.output_dir || "";
      $("x-calpath").value = body.engine_path || "";
      $("x-limit").value = body.upload_limit_mb || 200;
      // 仅打包版（exe）显示桌面快捷方式入口；脚本版用 start.bat
      $("x-mkshortcut").hidden = !state.frozen;
      return watchReady;
    }).then(function () {
      $("x-setdlg").showModal();
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  }

  function renderWatchFormatOptions(selected) {
    var select = $("x-watchformat");
    select.textContent = "";
    state.outputFormats.forEach(function (fmt) {
      var opt = el("option", "", fmtLabel(fmt));
      opt.value = fmt;
      if (fmt === selected) opt.selected = true;
      select.appendChild(opt);
    });
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
      toast("设置已保存", "ok");
      state.engine = null;  // 引擎路径可能变化，重新检测
      return saveWatchFromSettings().catch(function (err) {
        if (!err.network) toast(err.message, "warn");
      });
    }).then(function () {
      $("x-setdlg").close();
      return loadStatus();
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
    });
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
    var hasDir = false;
    if (e.dataTransfer && e.dataTransfer.items) {
      for (var i = 0; i < e.dataTransfer.items.length; i++) {
        var entry = e.dataTransfer.items[i].webkitGetAsEntry &&
                    e.dataTransfer.items[i].webkitGetAsEntry();
        if (entry && entry.isDirectory) { hasDir = true; break; }
      }
    }
    if (hasDir) {
      toast("暂不支持拖入整个文件夹，请打开文件夹后选择里面的文件，或使用监听功能", "warn");
      return;
    }
    if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });

  $("x-go").addEventListener("click", startConvert);
  $("x-clear").addEventListener("click", clearList);
  $("x-openout").addEventListener("click", function () { openFolder(state.outputDir || state.lastOutputDir); });
  $("x-browsebtn").addEventListener("click", function () { openBrowse("output"); });
  $("x-watchbrowse").addEventListener("click", function () { openBrowse("watch"); });
  $("x-watchtoggle").addEventListener("click", function () {
    state.watchOpen = !state.watchOpen;
    if (state.watch) renderWatch(state.watch);
  });
  $("x-browseup").addEventListener("click", function () { if (browseParent) loadBrowse(browseParent); });
  $("x-browseclose").addEventListener("click", function () { $("x-browsedlg").close(); });
  $("x-browsecancel").addEventListener("click", function () { $("x-browsedlg").close(); });
  $("x-browseok").addEventListener("click", chooseBrowse);

  $("x-setbtn").addEventListener("click", openSettings);
  $("x-setclose").addEventListener("click", function () { $("x-setdlg").close(); });
  $("x-setcancel").addEventListener("click", function () { $("x-setdlg").close(); });
  $("x-setsave").addEventListener("click", saveSettings);
  $("x-mkshortcut").addEventListener("click", function () {
    api("/api/create-shortcut", { method: "POST" }).then(function () {
      toast("已在桌面创建快捷方式", "ok");
    }).catch(function (err) { if (!err.network) toast(err.message, "warn"); });
  });

  $("x-histbtn").addEventListener("click", openHistory);
  $("x-histclose").addEventListener("click", function () { $("x-histdlg").close(); });
  $("x-histok").addEventListener("click", function () { $("x-histdlg").close(); });

  // ── 引擎安装引导 ──

  var installTimer = null;

  function setInstallButtons(disabled) {
    $("x-installportable").disabled = disabled;
    $("x-installwinget").disabled = disabled;
  }

  function renderInstallState(install) {
    var box = $("x-installstate");
    if (!install || (!install.active && install.state === "idle")) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    $("x-installfill").style.width = (install.progress || 0) + "%";
    $("x-installmsg").textContent = install.message || "";
    $("x-installmsg").style.color = install.state === "failed" ? "var(--x-clay)"
      : install.state === "done" ? "var(--x-moss)" : "";
  }

  function pollInstall() {
    if (installTimer) clearTimeout(installTimer);
    api("/api/status").then(function (body) {
      state.engine = body.engine;
      renderEngineBadge();
      renderInstallState(body.engine.install);
      var install = body.engine.install || {};
      if (!install.active) {
        setInstallButtons(false);
        if (install.state === "done") {
          toast("引擎已安装，检测更新中…", "ok");
          renderInstallState({ active: false, state: "idle", progress: 0, message: "" });
          return loadStatus();
        }
        return;  // failed：状态留在对话框上，按钮已恢复可重试
      }
      installTimer = setTimeout(pollInstall, 1000);
    }).catch(function () {
      installTimer = setTimeout(pollInstall, 2000);
    });
  }

  function installEngine(mode) {
    api("/api/install-engine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: mode }),
    }).then(function () {
      setInstallButtons(true);
      renderInstallState({ active: true, state: "downloading", progress: 0, message: "正在启动安装…" });
      pollInstall();
    }).catch(function (err) {
      if (!err.network) toast(err.message, "warn");
    });
  }

  $("x-guidebtn").addEventListener("click", function () { $("x-guidedlg").showModal(); });
  $("x-guideclose").addEventListener("click", function () { $("x-guidedlg").close(); });
  $("x-guideok").addEventListener("click", function () { $("x-guidedlg").close(); });
  $("x-guideset").addEventListener("click", function () {
    $("x-guidedlg").close();
    openSettings();
  });
  $("x-guideredetect").addEventListener("click", function () {
    state._announcedEngine = false;
    loadStatus();
  });
  $("x-installportable").addEventListener("click", function () { installEngine("portable"); });
  $("x-installwinget").addEventListener("click", function () { installEngine("winget"); });

  // ── 主题切换（纯视觉：读写 localStorage、切换 :root 的 data-theme）──

  var THEMES = ["night", "kindle", "kindledark", "santi"];
  var QUOTES = {
    night: "腹有诗书气自华 —— 苏轼《和董传留别》",
    kindle: "纵一苇之所如，凌万顷之茫然 —— 苏轼《赤壁赋》",
    kindledark: "明月几时有？把酒问青天 —— 苏轼《水调歌头》",
    santi: "大江东去，浪淘尽，千古风流人物 —— 苏轼《念奴娇·赤壁怀古》"
  };

  function applyTheme(name) {
    if (THEMES.indexOf(name) < 0) name = "night";
    document.documentElement.setAttribute("data-theme", name);
    Array.prototype.forEach.call(document.querySelectorAll(".x-theme"), function (b) {
      b.classList.toggle("is-on", b.getAttribute("data-theme") === name);
    });
    // Chromium 在 color-scheme 切换后 backdrop-filter 层可能渲染陈旧：
    // 短暂移除再恢复各面板的 backdrop-filter，强制重建合成层
    var blurEls = document.querySelectorAll(
      ".x-top,.x-row,.x-drop,.x-empty,.x-action,.x-dlg,.x-toast,.x-watchcard,.x-guide");
    var layers = document.querySelectorAll(".x-scenebg,.x-texbg,.x-grain");
    Array.prototype.forEach.call(layers, function (el) {
      el.style.display = "none";
    });
    Array.prototype.forEach.call(blurEls, function (el) {
      el.style.backdropFilter = "none";
      el.style.webkitBackdropFilter = "none";
    });
    setTimeout(function () {
      Array.prototype.forEach.call(blurEls, function (el) {
        el.style.backdropFilter = "";
        el.style.webkitBackdropFilter = "";
      });
      Array.prototype.forEach.call(layers, function (el) {
        el.style.display = "";
      });
    }, 80);
    var quote = document.getElementById("x-quote");
    if (quote) quote.textContent = QUOTES[name];
    try { localStorage.setItem("theme", name); } catch (e) {}
  }

  Array.prototype.forEach.call(document.querySelectorAll(".x-theme"), function (b) {
    b.addEventListener("click", function () {
      applyTheme(b.getAttribute("data-theme"));
    });
  });

  var savedTheme = null;
  try { savedTheme = localStorage.getItem("theme"); } catch (e) {}
  applyTheme(savedTheme || "night");

  // ── 启动 ──
  loadStatus().then(refreshTasks, refreshTasks);
  loadWatch();
})();
