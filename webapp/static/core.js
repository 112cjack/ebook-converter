/* 书渡 · core：常量、状态壳、DOM 小工具 */
window.Shudu = window.Shudu || {};
(function (S) {
  "use strict";
  S.$ = function (id) { return document.getElementById(id); };
  S.FMT_LABEL = {
    epub: "EPUB", mobi: "MOBI", azw3: "AZW3", pdf: "PDF", txt: "TXT", docx: "DOCX",
    rtf: "RTF", fb2: "FB2", odt: "ODT", htmlz: "HTMLZ",
  };
  S.SPINE = {
    EPUB: "light-dark(#2E6E5E,#4E9382)", MOBI: "light-dark(#B0803A,#C99A55)",
    PDF: "light-dark(#4A5560,#7C8794)", TXT: "light-dark(#8A8578,#A8A294)",
    AZW3: "light-dark(#3E5C76,#6E8DA8)", DOCX: "light-dark(#7A5E8C,#A38BB4)",
  };
  S.COMMON_INPUTS = ["epub", "mobi", "azw3", "pdf", "txt", "docx"];
  S.COMMON_OUTPUTS = ["epub", "pdf", "txt", "mobi"];
  S.state = {
    engine: null, outputFormats: [], inputExtensions: [], uploads: [], tasks: [],
    to: null, timer: null, wasBusy: false, lastOutputDir: null, outputDir: null,
    guideShown: false, uploading: false, frozen: false, settings: {},
    preset: "default", watch: null, watchTimer: null, watchOpen: false,
    watchBrowseRow: null, browseTarget: "output",
  };
  S.el = function (tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  S.icon = function (name) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ic");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  };
  S.sizeFmt = function (n) {
    if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
    if (n >= 1024) return Math.round(n / 1024) + " KB";
    return n + " B";
  };
  S.fmtLabel = function (fmt) { return S.FMT_LABEL[fmt] || String(fmt || "").toUpperCase(); };
  S.announce = function (msg) { var live = S.$("x-live"); if (live) live.textContent = msg; };
  S.toast = function (msg, kind) {
    var box = S.$("x-toasts");
    var d = S.el("div", "x-toast" + (kind === "warn" ? " is-warn" : kind === "ok" ? " is-ok" : ""));
    d.setAttribute("role", "status");
    d.textContent = msg;
    box.appendChild(d);
    setTimeout(function () { if (d.parentNode) d.parentNode.removeChild(d); }, 4500);
  };
  S.showConnBanner = function (visible) {
    var bar = S.$("x-connbar");
    if (bar) bar.hidden = !visible;
  };
})(window.Shudu);
