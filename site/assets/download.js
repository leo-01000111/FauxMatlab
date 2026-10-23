/*
 * The download buttons, per operating system.
 *
 * Two kinds of [data-download] button:
 *   - the install page's big one ([data-download-direct]), the only one that
 *     downloads. It names the system it detected above its label and the
 *     file's size and version below, and points at the file itself;
 *   - the others (the home page, the header), which say what you would get
 *     and take you to the install page to get it.
 *
 * Per system:
 *   - Windows: the installer from the latest release, with a note on the
 *     SmartScreen step once clicked;
 *   - macOS: the disk image, which is for Apple Silicon on macOS 13+. Safari
 *     and Firefox say "Intel, 10.15" on every Mac, so the button says who
 *     it is for; only where the browser tells the truth (Chrome and Edge,
 *     through userAgentData) does an Intel Mac or an old macOS get the
 *     source route outright;
 *   - Linux: the source route;
 *   - phones and tablets: a pointer to the install page, Evans being a
 *     desktop application.
 *
 * Every button starts as a plain link that works without JavaScript. The
 * file's address and size come from GitHub's API; if it does not answer,
 * the big button keeps the release page, so it never points nowhere.
 *
 * The big button goes through the download counter (worker/, served at
 * dl/ beside these pages), which counts the download and redirects to the
 * same file. Only once the counter has answered: where it does not (a local
 * build, an outage), the button points at GitHub directly. Its totals go
 * under the Windows and macOS headings ([data-installed]).
 */
(function () {
  "use strict";

  var API = "https://api.github.com/repos/leo-01000111/evans/releases/latest";
  var INSTALLER = /^Evans-Setup-[\d.]+\.exe$/;
  var DISK_IMAGE = /^Evans-[\d.]+-macos-arm64\.dmg$/;
  var COUNTER = "dl/";
  /* The oldest macOS the app runs on: PySide6's wheels need 13. */
  var MAC_MIN = 13;

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

  /*
   * What the browser will say beyond the system: {version, arch}, either
   * null where it will not. Only Chromium answers; its platformVersion is
   * the real one, where the user-agent string is frozen (Windows 10 for
   * Windows 11, macOS 10.15 for every Mac since 11).
   */
  function details() {
    var uad = navigator.userAgentData;
    if (!uad || !uad.getHighEntropyValues) {
      return Promise.resolve({ version: null, arch: null });
    }
    return uad.getHighEntropyValues(["platformVersion", "architecture"])
      .then(function (v) {
        return { version: v.platformVersion || null, arch: v.architecture || null };
      })
      .catch(function () { return { version: null, arch: null }; });
  }

  function major(version) {
    var n = parseInt(String(version || "").split(".")[0], 10);
    return isNaN(n) ? null : n;
  }

  /* "Windows 11", "macOS 14 · Apple Silicon", or the bare name. */
  function describe(os, d) {
    var n = major(d.version);
    if (os === "windows") {
      // Chromium's platformVersion: 13 and up is Windows 11, 1-10 is 10.
      if (n === null || n === 0) return "Windows";
      return n >= 13 ? "Windows 11" : "Windows 10";
    }
    if (os === "mac") {
      var name = n ? "macOS " + n : "macOS";
      if (d.arch === "arm") name += " · Apple Silicon";
      else if (d.arch === "x86") name += " · Intel";
      return name;
    }
    if (os === "linux") return "Linux";
    if (os === "mobile") return "a phone or tablet";
    return null;
  }

  // ── what a button shows ──

  function part(button, name) {
    return button.querySelector("[data-download-" + name + "]");
  }

  function label(button, text) {
    var target = part(button, "label") || button.querySelector("span");
    (target || button).textContent = text;
  }

  function line(button, name, text) {
    var target = part(button, name);
    if (!target) return;
    target.textContent = text || "";
    target.hidden = !text;
  }

  function note(button, html, after) {
    var id = button.getAttribute("data-download-note");
    var target = id && document.getElementById(id);
    if (target) {
      target.innerHTML = html;
      target.hidden = false;
      target.classList.toggle("download-note--after", !!after);
    }
  }

  /*
   * What the visitor sees once they have clicked: that it started, how to
   * start it again if it did not, and the steps that come next.
   */
  function started(b, steps, more) {
    var again = '<a href="' + b.href + '">Try again</a>';
    var all = '<a href="' + (b.getAttribute("data-download-release") ||
                             "#source") + '">All files of this release</a>';
    note(b, '<p class="download-note__title">Your download has started</p>' +
            "<p>Didn’t start? " + again + " · " + all + "</p>" +
            "<ol>" + steps.map(function (s) { return "<li>" + s + "</li>"; })
                          .join("") + "</ol>" +
            (more ? "<p>" + more + "</p>" : ""), true);
  }

  /*
   * The file's SHA-256 under the button, as GitHub publishes it. The short
   * form is for the eye; Copy and the tooltip carry the whole of it.
   */
  function checksum(f) {
    var box = document.querySelector("[data-download-check]");
    var hex = String(f.digest || "").replace(/^sha256:/, "");
    if (!box || !/^[0-9a-f]{64}$/.test(hex)) return;
    var code = box.querySelector("code");
    code.textContent = hex.slice(0, 12) + "…" + hex.slice(-12);
    code.title = hex;
    var copy = box.querySelector("button");
    copy.onclick = function () {
      var done = function () {
        copy.textContent = "Copied";
        setTimeout(function () { copy.textContent = "Copy"; }, 1600);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(hex).then(done);
    };
    box.hidden = false;
  }

  function direct(b) { return b.hasAttribute("data-download-direct"); }
  function sent(b) { return b.hasAttribute("data-download-source"); }

  // ── the latest release ──

  var release = null;
  function latest() {
    if (release) return release;
    release = !window.fetch ? Promise.resolve(null) :
      fetch(API, { headers: { Accept: "application/vnd.github+json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    return release;
  }

  /* The counter's totals, {windows, mac, total}, or null where it is down. */
  var counting = null;
  function counter() {
    if (counting) return counting;
    counting = !window.fetch ? Promise.resolve(null) :
      fetch(COUNTER + "count")
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    return counting;
  }

  /* "(12 already installed)" under each system's heading. */
  function installed() {
    var lines = document.querySelectorAll("[data-installed]");
    if (!lines.length) return;
    counter().then(function (totals) {
      if (!totals) return;
      Array.prototype.forEach.call(lines, function (p) {
        var n = totals[p.getAttribute("data-installed")];
        if (typeof n !== "number") return;
        p.textContent = "(" + n.toLocaleString("en") + " already installed)";
        p.hidden = false;
      });
    });
  }

  /*
   * Point the big button at the file matching `asset`, through the counter
   * at dl/`slug` when it is up, and say its size.
   */
  function file(buttons, asset, kind, slug) {
    Promise.all([latest(), counter()]).then(function (got) {
      var rel = got[0], counted = !!got[1];
      var assets = (rel && rel.assets) || [];
      var f = assets.filter(function (a) { return asset.test(a.name); })[0];
      buttons.forEach(function (b) {
        // Sent to the source route meanwhile (an Intel Mac): leave it there.
        if (!direct(b) || sent(b)) return;
        if (!f) {                               // keep the release page
          line(b, "size", "All downloads on GitHub");
          return;
        }
        b.href = counted ? COUNTER + slug : f.browser_download_url;
        b.setAttribute("title", f.name);
        b.setAttribute("data-download-release", rel.html_url);
        line(b, "size", kind + " size: " + Math.round(f.size / 1048576) +
             " MB · " + rel.tag_name);
        checksum(f);
      });
    });
  }

  // ── per system ──

  function windows(buttons) {
    var steps = [
      "Open the downloaded <code>Evans-Setup</code> file.",
      "If Windows says <em>Windows protected your PC</em>, click " +
        "<strong>More info</strong>, then <strong>Run anyway</strong>. " +
        '<a href="#smartscreen">Why</a>',
      "Follow the installer; no administrator rights needed. Then start " +
        "Evans from the Start menu."
    ];
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Download"
                                                     : "Download for Windows");
      if (direct(b)) b.addEventListener("click", function () {
        started(b, steps, 'No installing allowed on this PC? ' +
                '<a href="#windows">Take the portable zip</a>.');
      });
    });
    file(buttons, INSTALLER, "Installer", "windows");
  }

  function mac(buttons) {
    var who = "For Macs with Apple Silicon (M1 or later) on macOS 13 or " +
      "newer. On an Intel Mac or an older macOS, " +
      '<a href="#source">run Evans from source</a>.';
    var steps = [
      "Open the downloaded disk image and drag <strong>Evans</strong> onto " +
        "<strong>Applications</strong>.",
      "Open Evans from Applications. macOS stops the first launch, because " +
        "Evans is not notarised by Apple yet: close the message.",
      "In System Settings ▸ Privacy &amp; Security, click " +
        '<strong>Open Anyway</strong>. <a href="#gatekeeper">Step by step</a>'
    ];
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Download"
                                                     : "Download for Mac");
      if (!direct(b)) return;
      note(b, who);
      b.addEventListener("click", function () {
        if (!sent(b)) started(b, steps);
      });
    });
    file(buttons, DISK_IMAGE, "Disk image", "mac");
  }

  /* `name` for the button ("Run on Linux from source"), `why` for the note. */
  function source(buttons, name, why) {
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Install"
                                                     : "Run on " + name + " from source");
      b.setAttribute("data-download-source", "");
      if (!direct(b)) return;
      b.href = "#source";
      b.removeAttribute("title");
      var check = document.querySelector("[data-download-check]");
      if (check) check.hidden = true;           // no file, so no checksum
      line(b, "size", "Needs Python 3.12 or newer");
      note(b, why + " Evans runs from source with Python 3.12 or newer: " +
              "clone, <code>pip install -e .</code>, <code>python app.py</code>. " +
              '<a href="#source">Step by step</a>');
    });
  }

  function mobile(buttons) {
    buttons.forEach(function (b) {
      label(b, b.hasAttribute("data-download-short") ? "Install"
                                                     : "How to install");
      if (!direct(b)) return;
      b.href = "#windows-col";
      line(b, "size", "");
      note(b, "Evans is a desktop application for Windows, macOS and Linux. " +
              "Open this page on a computer to download it.");
    });
  }

  function run() {
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll("[data-download]"));
    installed();
    if (!buttons.length) return;
    var os = system();
    document.documentElement.setAttribute("data-os", os);

    // Everywhere but the install page, a button only leads there.
    buttons.forEach(function (b) {
      if (!direct(b)) b.href = "install.html";
    });

    if (os === "windows") windows(buttons);
    else if (os === "mac") mac(buttons);
    else if (os === "linux") source(buttons, "Linux", "There is no Linux build yet.");
    else if (os === "mobile") mobile(buttons);
    // "other": the release page, as written.

    var name = describe(os, { version: null, arch: null });
    buttons.forEach(function (b) { line(b, "os", name && "OS detected: " + name); });

    details().then(function (d) {
      var full = describe(os, d);
      buttons.forEach(function (b) { line(b, "os", full && "OS detected: " + full); });
      if (os !== "mac") return;
      // Only a browser that knows better takes a Mac off the download.
      var n = major(d.version);
      if (d.arch === "x86") {
        source(buttons, "Intel Macs", "There is no build for Intel Macs yet.");
      } else if (n !== null && n >= 10 && n < MAC_MIN) {
        source(buttons, "macOS " + n,
               "The Mac app needs macOS " + MAC_MIN + " or newer.");
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
