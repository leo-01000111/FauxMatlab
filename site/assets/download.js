/*
 * The download buttons, per operating system.
 *
 * Every element with [data-download] starts as a plain link to the latest
 * release page, which works without JavaScript and on any system. Here it
 * becomes, on
 *   - Windows: a direct download of the installer from the latest release,
 *     with a note on what to do once it has downloaded;
 *   - macOS: a direct download of the disk image, which is for Apple Silicon
 *     only. Safari and Firefox say "Intel" on every Mac, so the button says
 *     who it is for and links the source route; only where the browser can
 *     tell (Chrome and Edge, through userAgentData) does an Intel Mac get
 *     the source route outright;
 *   - Linux: a link to running Evans from source;
 *   - phones and tablets: a pointer to the install page, Evans being a
 *     desktop application.
 * The download's address comes from GitHub's API (its file name carries
 * the version). If the API does not answer, the button keeps the release
 * page, so it is never left pointing nowhere.
 */
(function () {
  "use strict";

  var API = "https://api.github.com/repos/leo-01000111/evans/releases/latest";
  var INSTALLER = /^Evans-Setup-[\d.]+\.exe$/;
  var DISK_IMAGE = /^Evans-[\d.]+-macos-arm64\.dmg$/;

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

  /* Point every button at the latest release's file matching `asset`. */
  function latest(buttons, asset) {
    if (!window.fetch) return;
    fetch(API, { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (release) {
        var assets = (release && release.assets) || [];
        var file = assets.filter(function (a) { return asset.test(a.name); })[0];
        if (!file) return;                      // keep the release page
        buttons.forEach(function (b) {
          // Sent to the source route meanwhile (an Intel Mac): leave it there.
          if (b.hasAttribute("data-download-source")) return;
          b.href = file.browser_download_url;
          b.setAttribute("title", file.name + " · " +
                         Math.round(file.size / 1048576) + " MB");
        });
      })
      .catch(function () { /* the release page stays */ });
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
    latest(buttons, INSTALLER);
  }

  function mac(buttons) {
    var who = "For Macs with Apple Silicon (M1 or later) on macOS 13 or " +
      "newer. On an Intel Mac or an older macOS, " +
      '<a href="install.html#source">run Evans from source</a>.';
    var after = "Downloading the disk image. Open it and drag Evans onto " +
      "Applications. The first time you open Evans, macOS stops it, because " +
      "it is not notarised by Apple yet: close the message, then click " +
      "<strong>Open Anyway</strong> in System Settings ▸ Privacy &amp; " +
      'Security. <a href="install.html#gatekeeper">Step by step</a>';
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Download"
                                                     : "Download for Mac");
      note(b, who);
      b.addEventListener("click", function () {
        if (!b.hasAttribute("data-download-source")) note(b, after);
      });
    });
    latest(buttons, DISK_IMAGE);
  }

  /* "arm", "x86", or null where the browser will not say (Safari, Firefox). */
  function macArchitecture() {
    var uad = navigator.userAgentData;
    if (!uad || !uad.getHighEntropyValues) return Promise.resolve(null);
    return uad.getHighEntropyValues(["architecture"])
      .then(function (v) { return v.architecture || null; })
      .catch(function () { return null; });
  }

  /* `name` for the button ("Run on Linux from source"), `which` for the note. */
  function source(buttons, name, which) {
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Install"
                                                     : "Run on " + name + " from source");
      b.href = "install.html#source";
      b.removeAttribute("title");
      b.setAttribute("data-download-source", "");
      note(b, "There is no build for " + which + " yet. Evans runs from " +
              "source with Python 3.12 or newer: clone, " +
              "<code>pip install -e .</code>, <code>python app.py</code>. " +
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
    else if (os === "mac") {
      // Offer the download at once; only a browser that knows better takes
      // an Intel Mac back to the source route.
      mac(buttons);
      macArchitecture().then(function (arch) {
        if (arch === "x86") source(buttons, "Intel Macs", "an Intel Mac");
      });
    }
    else if (os === "linux") source(buttons, "Linux", "Linux");
    else if (os === "mobile") mobile(buttons);
    // "other": the release page, as written.
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
