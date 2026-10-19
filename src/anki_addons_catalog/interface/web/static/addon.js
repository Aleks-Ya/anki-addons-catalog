// Lazily loads the addon history table when the "History" section is opened.
(() => {
  const details = document.getElementById("history");
  if (!details) return;
  let loaded = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || loaded) return;
    loaded = true;
    const body = details.querySelector("p");
    try {
      const response = await fetch(details.dataset.url);
      if (!response.ok) throw new Error(response.statusText);
      const history = await response.json();
      const table = document.createElement("table");
      const head = ["Snapshot", "Listed", "Rating", "Likes", "Stars", "Updated", "Anki versions"];
      table.innerHTML = "<thead><tr>" + head.map((h) => `<th>${h}</th>`).join("") + "</tr></thead>";
      const tbody = document.createElement("tbody");
      for (const p of history.points.slice().reverse()) {
        const tr = document.createElement("tr");
        for (const value of [p.snapshot, p.present ? "yes" : "no", p.rating, p.likes, p.github_stars,
                             p.update_date, p.anki_version]) {
          const td = document.createElement("td");
          td.textContent = value ?? "–";
          tr.append(td);
        }
        tbody.append(tr);
      }
      table.append(tbody);
      body.replaceWith(table);
    } catch (e) {
      body.removeAttribute("aria-busy");
      body.textContent = "Could not load the history. Please try again later.";
      loaded = false;
    }
  });
})();

// Cuts long descriptions and READMEs to their beginning, with a button to expand them.
(() => {
  for (const article of document.querySelectorAll("[data-collapsible]")) {
    article.classList.add("collapsed");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary outline expand";
    button.textContent = "Show more";
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", () => {
      const collapsed = article.classList.toggle("collapsed");
      button.textContent = collapsed ? "Show more" : "Show less";
      button.setAttribute("aria-expanded", String(!collapsed));
      const section = article.closest("section");
      if (collapsed && section.getBoundingClientRect().top < 0) section.scrollIntoView({ block: "start" });
    });
    // Images load after this script and change the height, so re-check whenever the article resizes.
    const update = () => {
      if (!article.classList.contains("collapsed")) return;
      const overflowing = article.scrollHeight > article.clientHeight;
      article.classList.toggle("overflowing", overflowing);
      if (overflowing) article.after(button);
      else button.remove();
    };
    new ResizeObserver(update).observe(article);
    for (const image of article.querySelectorAll("img")) image.addEventListener("load", update);
    window.addEventListener("load", update);
  }
})();
