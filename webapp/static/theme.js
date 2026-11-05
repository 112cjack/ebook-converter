/* 书渡 · theme：配色主题切换与诗句 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";

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

  // ── 对外导出 ──
  S.applyTheme = applyTheme;
})(window.Shudu);
