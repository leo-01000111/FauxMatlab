/*
 * The issue form on the patch-notes page.
 *
 * Without JavaScript the form posts to Formspree and the visitor lands on
 * Formspree's thank-you page. Here it is sent in the background instead, so
 * the visitor stays on the page and sees the answer under the button. The
 * subject line carries the kind and the summary, so a report reads at a
 * glance in the inbox. On failure everything typed stays in the form.
 */
(function () {
  "use strict";

  var form = document.querySelector("[data-issue-form]");
  if (!form || !window.fetch || !window.FormData) return;
  var status = form.querySelector(".issue-form__status");
  var button = form.querySelector("button[type=submit]");

  function say(text, kind) {
    status.textContent = text;
    status.className = "issue-form__status" + (kind ? " is-" + kind : "");
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var data = new FormData(form);
    data.set("_subject", "Evans " + data.get("kind") + ": " + data.get("summary"));
    button.disabled = true;
    say("Sending…");
    fetch(form.action, { method: "POST", body: data, headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          if (!response.ok) {
            var errors = body.errors && body.errors.map(function (e) { return e.message; }).join(" ");
            throw new Error(errors || "the server answered " + response.status);
          }
        });
      })
      .then(function () {
        var version = form.elements.version.value;
        form.reset();
        form.elements.version.value = version;
        say("Sent. Thank you, I read every one.", "ok");
      })
      .catch(function (error) {
        say("Not sent: " + error.message + ". Try again, or open an issue on GitHub.", "bad");
      })
      .then(function () { button.disabled = false; });
  });
})();
