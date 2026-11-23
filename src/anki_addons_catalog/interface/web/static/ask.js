// Streams the AI answer from /api/ask (Server-Sent Events). It starts by itself when the visitor has just typed the
// question in the search box, or when the answer is cached (free, no human check); otherwise after a click on the
// button, as a question that starts on every page load is mostly cancelled by a filter change or a quick exit, but
// still costs money.
(() => {
  const root = document.getElementById("ai");
  if (!root) return;
  const query = root.dataset.query;
  const siteKey = root.dataset.siteKey;
  const status = document.getElementById("ai-status");
  const answer = document.getElementById("ai-answer");
  const addons = document.getElementById("ai-addons");
  const widget = document.getElementById("ai-turnstile");
  const button = document.getElementById("ai-start");

  const setStatus = (text, busy = true) => {
    status.replaceChildren();
    if (!text) return;
    const span = document.createElement("span");
    span.textContent = text;
    if (busy) span.setAttribute("aria-busy", "true");
    status.append(span);
  };
  const showError = (text) => {
    status.replaceChildren();
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = text;
    status.append(p);
  };

  function verify() {
    setStatus("Please confirm you are human to use the AI search.", false);
    const render = () => window.turnstile.render(widget, {
      sitekey: siteKey,
      callback: async (token) => {
        const response = await fetch("/api/verify", {
          method: "POST",
          body: new URLSearchParams({ token }),
          credentials: "same-origin",
        });
        widget.replaceChildren();
        if (response.ok) start(); else showError("The check failed. Please reload the page.");
      },
    });
    if (window.turnstile) render();
    else window.addEventListener("load", render, { once: true });
  }

  function start(cachedOnly = false) {
    setStatus(cachedOnly ? "" : "Starting…");
    answer.replaceChildren();
    addons.replaceChildren();
    let streamed = "";
    const filters = root.dataset.filters ? "&" + root.dataset.filters : "";
    const cached = cachedOnly ? "&cached=1" : "";
    const source = new EventSource("/api/ask?q=" + encodeURIComponent(query) + filters + cached);
    const finish = () => source.close();
    const data = (event) => JSON.parse(event.data);

    source.addEventListener("status", (e) => setStatus(data(e) + "…"));
    source.addEventListener("text", (e) => {
      streamed += data(e);
      answer.classList.add("streaming");
      answer.textContent = streamed;
    });
    source.addEventListener("answer", (e) => {
      answer.classList.remove("streaming");
      answer.innerHTML = data(e).html;  // rendered server-side from markdown with raw HTML disabled
    });
    source.addEventListener("addons", (e) => {
      const payload = data(e);
      if (!payload.count) return;
      addons.innerHTML = "<h3>Addons in this answer</h3>" + payload.html;
    });
    source.addEventListener("done", () => { setStatus(""); finish(); });
    source.addEventListener("not_cached", () => { finish(); button.hidden = false; });
    source.addEventListener("error", (e) => {
      finish();
      if (cachedOnly && !e.data && !answer.innerHTML) button.hidden = false;
      else if (e.data) showError(data(e));
      else if (!answer.innerHTML) showError("The connection was interrupted. Please reload the page to try again.");
    });
    source.addEventListener("verify", () => {
      finish();
      if (siteKey) verify(); else showError("AI search is not available right now.");
    });
  }

  button.addEventListener("click", () => {
    button.hidden = true;
    start();
  });

  const typed = (() => {
    try {
      const value = sessionStorage.getItem("ai-ask");
      sessionStorage.removeItem("ai-ask");  // once: a reload or a filter change is not typing
      return value;
    } catch {
      return null;
    }
  })();
  const normalize = (text) => (text || "").replace(/\s+/g, " ").trim();
  button.hidden = true;
  if (typed !== null && normalize(typed) === normalize(query)) start();
  else start(true);
})();
