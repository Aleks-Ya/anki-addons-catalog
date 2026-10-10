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
