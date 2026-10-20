/*
 * The download buttons, per operating system.
 *
 * Every element with [data-download] starts as a plain link to the latest
 * release page, which works without JavaScript and on any system. Here it
 * becomes, on
 *   - Windows: a direct download of the installer from the latest release,
 *     with a note on what to do once it has downloaded;
 *   - macOS and Linux: a link to running Evans from source;
 *   - phones and tablets: a pointer to the install page, Evans being a
 *     desktop application.
 * The installer's address comes from GitHub's API (its file name carries
 * the version). If the API does not answer, the button keeps the release
 * page, so it is never left pointing nowhere.
 */
(function () {
  "use strict";

  var API = "https://api.github.com/repos/leo-01000111/evans/releases/latest";
  var INSTALLER = /^Evans-Setup-[\d.]+\.exe$/;

  function system() {
    var uad = navigator.userAgentData;
    var ua = navigator.userAgent || "";
    var platform = (uad && uad.platform) || navigator.platform || "";
    if (uad && uad.mobile) return "mobile";
    if (/Android|iPhone|iPad|iPod/i.test(ua)) return "mobile";
    // iPadOS reports itself as a Mac; touch gives it away.
    if (/Mac/i.test(platform) && navigator.maxTouchPoints > 1) return "mobile";
    if (/Win/i.test(platform) || /Windows/i.test(ua)) return "windows";
    if (/Mac/i.test(platform) || /Mac OS X/i.test(ua)) return "mac";
    if (/Linux|X11|CrOS/i.test(platform + ua)) return "linux";
    return "other";
  }

  function label(button, text) {
    var span = button.querySelector("span");
    (span || button).textContent = text;
  }

  function note(button, html) {
    var id = button.getAttribute("data-download-note");
    var target = id && document.getElementById(id);
    if (target) {
      target.innerHTML = html;
      target.hidden = false;
    }
  }

  function windows(buttons) {
    var after = "Downloading the installer. When it has finished, run it: " +
      "Windows may say <em>Windows protected your PC</em>, because the " +
      "installer is not code-signed yet, so choose <strong>More info</strong> " +
      "then <strong>Run anyway</strong>. " +
      '<a href="install.html#smartscreen">Why</a> · ' +
      '<a href="install.html#windows">Portable zip instead</a>';
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Download"
                                                     : "Download for Windows");
      b.addEventListener("click", function () { note(b, after); });
    });
    if (!window.fetch) return;
    fetch(API, { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (release) {
        var assets = (release && release.assets) || [];
        var exe = assets.filter(function (a) { return INSTALLER.test(a.name); })[0];
        if (!exe) return;                       // keep the release page
        buttons.forEach(function (b) {
          b.href = exe.browser_download_url;
          b.setAttribute("title", exe.name + " · " +
                         Math.round(exe.size / 1048576) + " MB");
        });
      })
      .catch(function () { /* the release page stays */ });
  }

  function source(buttons, name) {
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Install"
                                                     : "Run on " + name + " from source");
      b.href = "install.html#source";
      note(b, "There is no " + name + " build yet. Evans runs from source " +
              "with Python 3.12 or newer: clone, <code>pip install -e .</code>, " +
              "<code>python app.py</code>. " +
              '<a href="install.html#source">Step by step</a>');
    });
  }

  function mobile(buttons) {
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Install"
                                                     : "How to install");
      b.href = "install.html";
      note(b, "Evans is a desktop application for Windows, macOS and Linux. " +
              "Open this page on a computer to download it.");
    });
  }

  function run() {
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll("[data-download]"));
    if (!buttons.length) return;
    var os = system();
    document.documentElement.setAttribute("data-os", os);
    if (os === "windows") windows(buttons);
    else if (os === "mac") source(buttons, "macOS");
    else if (os === "linux") source(buttons, "Linux");
    else if (os === "mobile") mobile(buttons);
    // "other": the release page, as written.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
