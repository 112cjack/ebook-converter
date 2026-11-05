/* 书渡 · actions：上传/转换/移除等动作、对话框与事件绑定 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

  // ── 动作 ──

  function uploadWithProgress(form, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded * 100 / e.total));
      };
      xhr.onload = function () {
        S.showConnBanner(false);
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
        S.showConnBanner(true);
        var err = new Error(S.CONN_MSG);
        err.network = true;
        reject(err);
      };
      xhr.send(form);
    });
  }

  function addFiles(fileList) {
    if (!fileList || !fileList.length) return;
    if (S.state.uploading) return;
    var form = new FormData();
    var count = 0;
    Array.prototype.forEach.call(fileList, function (f) {
      form.append("files", f, f.name);
      count++;
    });
    S.state.uploading = true;
    var progressEl = S.$("x-uploading");
    progressEl.hidden = false;
    progressEl.textContent = "正在上传… 0%";
    S.renderList();
    uploadWithProgress(form, function (pct) {
      progressEl.textContent = "正在上传… " + pct + "%";
    }).then(function (body) {
      if (body.uploads.length) {
        S.announce("已添加 " + body.uploads.length + " 个文件");
        S.toast("已添加 " + body.uploads.length + " 个文件", "ok");
      }
      (body.rejected || []).forEach(function (r) {
        S.toast("已跳过 " + r.name + "：" + r.reason, "warn");
      });
      return S.refreshTasks();
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
    }).finally(function () {
      S.state.uploading = false;
      progressEl.hidden = true;
      progressEl.textContent = "正在上传…";
      S.$("x-file").value = "";
      S.renderList();
    });
  }

  function startConvert() {
    if (!S.state.to) { S.toast("请先选择输出格式", "warn"); return; }
    if (!S.engineReady()) { S.toast("未检测到转换引擎，请先安装或指定 Calibre", "warn"); return; }
    var waiting = S.state.uploads.filter(function (u) {
      return !u.removed && !S.latestTaskOf(u.id);
    }).map(function (u) { return u.id; });
    if (!waiting.length) { S.toast("没有待转换的文件", "warn"); return; }
    var body = { format: S.state.to, upload_ids: waiting, preset: S.state.preset || "default" };
    var outDir = S.state.outputDir || S.state.lastOutputDir;
    if (outDir) body.output_dir = outDir;
    S.api("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function () {
      S.announce("开始转换，共 " + waiting.length + " 个文件");
      S.state.wasBusy = true;
      // 大文件转换期间用户常切走标签页，提前请求通知权限（用户手势内）
      if ("Notification" in window && Notification.permission === "default") {
        try { Notification.requestPermission(); } catch (e) { /* 忽略 */ }
      }
      return S.refreshTasks();
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
      if (err.body && err.body.engine && err.body.engine.installed === false) {
        S.renderEngineBadge();
        S.$("x-guidedlg").showModal();
      }
      S.refreshTasks();
    });
  }

  function retryTask(uploadId, format, overwrite) {
    var body = { format: format, upload_ids: [uploadId] };
    if (overwrite) body.overwrite = true;
    S.api("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function () {
      S.toast(overwrite ? "已重新开始转换（将覆盖旧输出）" : "已重新加入队列", "ok");
      S.state.wasBusy = true;
      return S.refreshTasks();
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  }

  function cancelTask(taskId) {
    S.api("/api/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    }).then(function () {
      return S.refreshTasks();
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  }

  function removeUploads(ids) {
    S.api("/api/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_ids: ids }),
    }).then(function (body) {
      if (body.busy && body.busy.length) S.toast("转换中的文件暂不能移除", "warn");
      return S.refreshTasks();
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  }

  function clearList() {
    S.api("/api/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }).then(function () {
      S.announce("列表已清空");
      return S.refreshTasks();
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  }

  function openFolder(path) {
    if (!path) { S.toast("暂无可打开的输出目录", "warn"); return; }
    S.api("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path }),
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  }

  // ── 对话框 ──

  function openSettings() {
    var watchReady = S.api("/api/watch").then(function (w) {
      S.state.watch = w;
      S.renderWatchRules(w.rules || []);
      S.scheduleWatchPoll();
      return w;
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
    });
    S.api("/api/settings").then(function (body) {
      S.$("x-outdir").value = body.output_dir || "";
      S.$("x-calpath").value = body.engine_path || "";
      S.$("x-limit").value = body.upload_limit_mb || 200;
      // 仅打包版（exe）显示桌面快捷方式入口；脚本版用 start.bat
      S.$("x-mkshortcut").hidden = !S.state.frozen;
      return watchReady;
    }).then(function () {
      S.$("x-setdlg").showModal();
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  }

  function saveSettings() {
    S.api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        output_dir: S.$("x-outdir").value.trim(),
        engine_path: S.$("x-calpath").value.trim(),
        upload_limit_mb: parseInt(S.$("x-limit").value, 10),
      }),
    }).then(function () {
      S.toast("设置已保存", "ok");
      S.state.engine = null;  // 引擎路径可能变化，重新检测
      return S.saveWatchFromSettings().catch(function (err) {
        if (!err.network) S.toast(err.message, "warn");
      });
    }).then(function () {
      S.$("x-setdlg").close();
      return S.loadStatus();
    }).catch(function (err) {
      if (!err.network) S.toast(err.message, "warn");
    });
  }

  function openHistory() {
    var bodyEl = S.$("x-histbody");
    bodyEl.textContent = "";
    var rows = S.state.tasks.slice().reverse();
    if (!rows.length) {
      bodyEl.appendChild(S.el("div", "x-hempty", "本次运行还没有转换记录。"));
    }
    rows.forEach(function (t) {
      var row = S.el("div", "x-hrow");
      row.appendChild(S.el("span", "x-htime", fmtTime(t.finished_at || t.created_at)));
      row.appendChild(S.el("span", "x-hname", t.name));
      row.appendChild(S.el("span", "x-meta", S.fmtLabel(t.format_in) + " → " + S.fmtLabel(t.format_out)));
      var note = t.status === "done" ? "完成"
        : t.status === "failed" ? (t.error || "失败")
        : (t.message || t.status_label);
      row.appendChild(S.el("span",
        t.status === "done" ? "x-hst-ok" : t.status === "failed" ? "x-hst-bad" : "x-hst-skip",
        note));
      bodyEl.appendChild(row);
    });
    S.$("x-histdlg").showModal();
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    var pad = function (x) { return (x < 10 ? "0" : "") + x; };
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  // ── 事件绑定 ──

  S.$("x-file").addEventListener("change", function (e) {
    addFiles(e.target.files);
  });
  var drop = S.$("x-drop");
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
      S.toast("暂不支持拖入整个文件夹，请打开文件夹后选择里面的文件，或使用监听功能", "warn");
      return;
    }
    if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });

  S.$("x-go").addEventListener("click", startConvert);
  S.$("x-clear").addEventListener("click", clearList);
  S.$("x-openout").addEventListener("click", function () { openFolder(S.state.outputDir || S.state.lastOutputDir); });
  S.$("x-browsebtn").addEventListener("click", function () { S.openBrowse("output"); });
  S.$("x-watchaddrule").addEventListener("click", function () {
    S.$("x-watchrules").appendChild(S.watchRuleRow("", S.state.outputFormats[0] || "epub", false));
  });
  S.$("x-watchtoggle").addEventListener("click", function () {
    S.state.watchOpen = !S.state.watchOpen;
    if (S.state.watch) S.renderWatch(S.state.watch);
  });
  S.$("x-browseup").addEventListener("click", S.browseUp);
  S.$("x-browseclose").addEventListener("click", function () { S.$("x-browsedlg").close(); });
  S.$("x-browsecancel").addEventListener("click", function () { S.$("x-browsedlg").close(); });
  S.$("x-browseok").addEventListener("click", S.chooseBrowse);

  S.$("x-setbtn").addEventListener("click", openSettings);
  S.$("x-setclose").addEventListener("click", function () { S.$("x-setdlg").close(); });
  S.$("x-setcancel").addEventListener("click", function () { S.$("x-setdlg").close(); });
  S.$("x-setsave").addEventListener("click", saveSettings);
  S.$("x-mkshortcut").addEventListener("click", function () {
    S.api("/api/create-shortcut", { method: "POST" }).then(function () {
      S.toast("已在桌面创建快捷方式", "ok");
    }).catch(function (err) { if (!err.network) S.toast(err.message, "warn"); });
  });

  S.$("x-histbtn").addEventListener("click", openHistory);
  S.$("x-histclose").addEventListener("click", function () { S.$("x-histdlg").close(); });
  S.$("x-histok").addEventListener("click", function () { S.$("x-histdlg").close(); });
  S.$("x-histcsv").addEventListener("click", function () {
    var link = document.createElement("a");
    link.href = "/api/history.csv";
    link.download = "";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  });
  S.$("x-preset").addEventListener("change", function (e) {
    S.state.preset = e.target.value || "default";
  });

  // ── 对外导出 ──
  S.openSettings = openSettings;
  S.openFolder = openFolder;
  S.retryTask = retryTask;
  S.cancelTask = cancelTask;
  S.removeUploads = removeUploads;
})(window.Shudu);
