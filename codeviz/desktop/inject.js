// Desktop app only: buttons in the viewer's top bar to open another folder or rescan this one.
(function () {
  const cfg = window.CODEVIZ_DESKTOP;
  const base = location.pathname.replace(/view\/[^/]+\/?$/, "");
  const api = (path, body) => fetch(base + "api/" + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then((r) => r.json());
  const btn = (label, title, onclick) => {
    const b = document.createElement("button");
    b.textContent = label; b.title = title; b.onclick = onclick;
    return b;
  };
  const home = () => { location.href = base + "#pick"; };
  let scanning = false;
  async function rescan(b) {
    if (scanning) return;
    scanning = true; b.textContent = "↻ Scanning…"; b.disabled = true;
    try {
      const { job } = await api("scan", { path: cfg.path });
      for (;;) {
        await new Promise((r) => setTimeout(r, 200));
        const j = await api("job/" + job);
        if (j.state === "done") { location.reload(); return; }
        if (j.state === "error") { alert("Rescan failed: " + j.error); break; }
      }
    } catch (e) { alert("Rescan failed: " + e); }
    scanning = false; b.textContent = "↻ Rescan"; b.disabled = false;
  }
  const bar = document.querySelector(".top-right");
  const group = document.createElement("span");
  group.className = "desktop-buttons";
  group.style.cssText = "display:flex;gap:4px";
  const re = btn("↻ Rescan", "Scan " + cfg.path + " again to pick up changes", () => rescan(re));
  group.append(btn("📂 Open…", "Open another folder (Ctrl/⌘+O)", home), re);
  bar.prepend(group);
  document.getElementById("project-name").title = cfg.path;
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") { e.preventDefault(); home(); }
  });
})();
