// Filter panel of the search page: applies a filter as soon as it changes and remembers the visitor's Anki version.
(() => {
  const form = document.getElementById("filters");
  if (!form) return;
  const panel = form.closest("details");
  if (window.matchMedia("(max-width: 767px)").matches) panel.removeAttribute("open");
  form.querySelector(".apply").hidden = true;

  const KEY = "anki-version";
  const anki = form.elements.anki;
  const storage = {
    get: () => { try { return localStorage.getItem(KEY); } catch { return null; } },
    set: (value) => { try { value ? localStorage.setItem(KEY, value) : localStorage.removeItem(KEY); } catch { /* private mode */ } },
  };

  let submitted = false;
  const submit = () => {
    if (submitted) return;  // a picked suggestion may fire both "input" and "change"
    if (!anki.checkValidity()) { anki.reportValidity(); return; }
    storage.set(anki.value.trim());
    // The "Any rating" radio has an empty value: leave it out of the URL like the other defaults.
    for (const input of form.querySelectorAll("input[name=rating]")) input.disabled = input.checked && !input.value;
    if (!anki.value.trim()) anki.disabled = true;
    submitted = true;
    form.submit();
  };
  form.addEventListener("change", submit);
  // Picking a suggestion fires "input" (a plain Event in Chrome, "insertReplacementText" in Firefox), not always
  // "change"; typed input is left to "change", so typing 25.09.1 does not submit at 25.09.
  anki.addEventListener("input", (e) => {
    if (!(e instanceof InputEvent) || e.inputType === "insertReplacementText") submit();
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

  const saved = storage.get();
  const offer = document.getElementById("f-anki-saved");
  if (saved && !anki.value) {
    offer.querySelector("span").textContent = saved;
    offer.hidden = false;
    offer.querySelector("a").addEventListener("click", (e) => {
      e.preventDefault();
      anki.value = saved;
      submit();
    });
  }
})();
