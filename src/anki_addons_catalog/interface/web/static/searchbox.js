// Search box: the question field grows with the text, Enter asks and Shift+Enter starts a new line.
(() => {
  const form = document.querySelector("form.searchbox");
  if (!form) return;
  const box = form.elements.q;

  const fit = () => {
    box.style.height = "auto";
    box.style.height = box.scrollHeight + box.offsetHeight - box.clientHeight + "px";
  };
  box.addEventListener("input", fit);
  window.addEventListener("resize", fit);
  fit();

  // Tells the search page that the visitor typed this question, so its AI answer starts without a click.
  form.addEventListener("submit", () => {
    try { sessionStorage.setItem("ai-ask", box.value); } catch { /* private mode */ }
  });

  box.addEventListener("keydown", (e) => {
    // Enter also confirms Japanese, Chinese and Korean input methods: do not submit then.
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    form.requestSubmit();
  });
})();
