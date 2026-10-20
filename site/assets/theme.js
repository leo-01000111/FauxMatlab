/* Copied from leo-01000111.github.io (assets/theme.js), the Holding Point design system
   behind leongorecki.eu. Keep in step with that repo rather than editing here. */
/* Day / Night toggle. Loaded synchronously in <head> so a saved choice is
   applied before first paint. Without a saved choice (or without JS) the
   theme follows the OS via tokens.css. */
(function () {
  var KEY = "hp-theme";
  var COLORS = { light: "#e7e8e3", dark: "#0e0f11" };
  var root = document.documentElement;

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function current() {
    var t = root.getAttribute("data-theme");
    if (t === "light" || t === "dark") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i++) metas[i].setAttribute("content", COLORS[theme]);
  }

  var saved = stored();
  if (saved === "light" || saved === "dark") apply(saved);

  function sync(group) {
    var theme = current();
    var buttons = group.querySelectorAll("button[data-set-theme]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed", buttons[i].getAttribute("data-set-theme") === theme ? "true" : "false");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var group = document.querySelector("[data-theme-toggle]");
    if (!group) return;
    group.hidden = false;
    sync(group);
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-set-theme]");
      if (!btn) return;
      var theme = btn.getAttribute("data-set-theme");
      apply(theme);
      try { localStorage.setItem(KEY, theme); } catch (err) {}
      sync(group);
    });
    if (!saved && window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () { if (!stored()) sync(group); };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
    }
  });
})();
