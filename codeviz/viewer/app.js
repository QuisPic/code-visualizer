/* codeviz viewer: explorer tree, call/caller tree, linked source. Data comes from the DATA global. */
(function () {
  "use strict";

  const FILES = DATA.files;
  const FUNCS = DATA.funcs;
  const FAMILY = { python: "py", javascript: "js", typescript: "js", tsx: "js", c: "c", cpp: "c", go: "go",
                   rust: "rust", java: "java", ruby: "rb", php: "php" };
  const KIND_LETTER = { function: "ƒ", method: "m", constructor: "c", toplevel: "⋯" };
  const $ = (sel, root = document) => root.querySelector(sel);

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children) if (c != null && c !== false) node.append(c);
    return node;
  }

  // ---------------------------------------------------------------- derived indexes
  const sep = (f) => (["c", "rust", "php"].includes(FAMILY[FILES[f.f].lang]) ? "::" : ".");
  const qname = (f) => (f.s ? f.s + sep(f) + f.n : f.n);
  const fileOf = (f) => FILES[f.f].p;
  const callers = FUNCS.map(() => []); // id -> [{from, line}]
  for (const f of FUNCS) for (const c of f.calls) if (c.t) for (const t of c.t) callers[t].push({ from: f.id, line: c.l });
  const byFile = FILES.map(() => []);
  for (const f of FUNCS) byFile[f.f].push(f);

  const prefs = loadPrefs();
  function loadPrefs() {
    const d = { ext: false, low: true, theme: null, sidebar: null, treeW: null };
    try { return Object.assign(d, JSON.parse(localStorage.getItem("codeviz-prefs") || "{}")); } catch { return d; }
  }
  function savePrefs() { try { localStorage.setItem("codeviz-prefs", JSON.stringify(prefs)); } catch { /* ignore */ } }

  // Children of a node in the call tree. Outgoing: grouped by target (or by name for ambiguous/external).
  function outgoing(f) {
    const groups = new Map();
    for (const c of f.calls) {
      let key, item;
      if (!c.t) {
        if (!prefs.ext) continue;
        key = "x:" + (c.q ? c.q + "." : "") + c.n;
        item = { type: "ext", name: c.n, q: c.q };
      } else if (c.x === "a") {
        key = "a:" + c.n + ":" + c.t.join(",");
        item = { type: "amb", name: c.n, targets: c.t };
      } else {
        if (c.x === "l" && !prefs.low) continue;
        key = "f:" + c.t[0];
        item = { type: "fn", id: c.t[0], low: c.x === "l" };
      }
      const g = groups.get(key);
      if (g) { g.lines.push(c.l); if (item.low === false) g.low = false; } else groups.set(key, Object.assign(item, { lines: [c.l] }));
    }
    return [...groups.values()];
  }
  function incoming(f) {
    const groups = new Map();
    for (const c of callers[f.id]) {
      const g = groups.get(c.from);
      if (g) g.lines.push(c.line); else groups.set(c.from, { type: "fn", id: c.from, lines: [c.line] });
    }
    return [...groups.values()].sort((a, b) => fileOf(FUNCS[a.id]).localeCompare(fileOf(FUNCS[b.id])) || FUNCS[a.id].l - FUNCS[b.id].l);
  }

  // ---------------------------------------------------------------- syntax highlighting
  const KEYWORDS = {
    c: "alignas alignof asm auto bool break case catch char class const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept nullptr operator override final private protected public register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile while size_t uint8_t uint16_t uint32_t uint64_t int8_t int16_t int32_t int64_t",
    js: "as async await break case catch class const continue debugger default delete do else enum export extends false finally for from function get if implements import in instanceof interface let new null of private protected public readonly return set static super switch this throw true try type typeof undefined var void while with yield",
    py: "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return self True try while with yield",
    go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false",
    rust: "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
    java: "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new null package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false var record",
    rb: "alias and begin break case class def defined? do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield",
    php: "abstract and array as break callable case catch class clone const continue declare default do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile extends final finally fn for foreach function global goto if implements include include_once instanceof insteadof interface isset list match namespace new null or print private protected public readonly require require_once return static switch throw trait try unset use var while xor true false",
  };
  const KW = {}; for (const k in KEYWORDS) KW[k] = new Set(KEYWORDS[k].split(" "));
  const TOKEN_RE = {};
  function tokenRe(fam) {
    if (TOKEN_RE[fam]) return TOKEN_RE[fam];
    const hashCom = fam === "py" || fam === "rb";
    const parts = [
      hashCom ? null : "(\\/\\*[\\s\\S]*?(?:\\*\\/|$))",           // 1 block comment
      hashCom ? "(#[^\\n]*)" : (fam === "php" ? "(\\/\\/[^\\n]*|#[^\\n]*)" : "(\\/\\/[^\\n]*)"), // 2 line comment
      fam === "py" ? "(\"\"\"[\\s\\S]*?(?:\"\"\"|$)|'''[\\s\\S]*?(?:'''|$))" : null, // 3 triple strings
      "(\"(?:[^\"\\\\\\n]|\\\\.)*\"?|'(?:[^'\\\\\\n]|\\\\.)*'?" + (fam === "js" || fam === "go" ? "|`(?:[^`\\\\]|\\\\.)*`?" : "") + ")", // 4 strings
      fam === "c" ? "(^[ \\t]*#[^\\n]*)" : null,                    // 5 preprocessor
      "(\\b\\d[\\w.]*)",                                           // 6 numbers
      "([A-Za-z_$][\\w$]*)",                                       // 7 identifiers
    ];
    const groups = { com: [], str: [], pp: 0, num: 0, id: 0 };
    let src = "", n = 0;
    parts.forEach((p, i) => {
      if (!p) return;
      n++;
      src += (src ? "|" : "") + p;
      if (i <= 1) groups.com.push(n); else if (i <= 3) groups.str.push(n);
      else if (i === 4) groups.pp = n; else if (i === 5) groups.num = n; else groups.id = n;
    });
    return (TOKEN_RE[fam] = { re: new RegExp(src, "gm"), groups });
  }
  // returns per-char class codes: 0 plain, 1 kw, 2 str, 3 com, 4 num, 5 pp, 6 fn, 7 type
  const CLS = ["", "t-kw", "t-str", "t-com", "t-num", "t-pp", "t-fn", "t-type"];
  function highlight(code, fam) {
    const out = new Uint8Array(code.length);
    const { re, groups } = tokenRe(fam);
    const kw = KW[fam] || new Set();
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(code))) {
      if (m[0] === "") { re.lastIndex++; continue; }
      let cls = 0;
      if (groups.com.some((g) => m[g] !== undefined)) cls = 3;
      else if (groups.str.some((g) => m[g] !== undefined)) cls = 2;
      else if (groups.pp && m[groups.pp] !== undefined) cls = 5;
      else if (m[groups.num] !== undefined) cls = 4;
      else if (m[groups.id] !== undefined) {
        const w = m[0];
        if (kw.has(w)) cls = 1;
        else if (/^\s*\(/.test(code.slice(re.lastIndex, re.lastIndex + 8))) cls = 6;
        else if (/^[A-Z][a-z0-9]/.test(w) && fam !== "rb") cls = 7;
      }
      if (cls) out.fill(cls, m.index, m.index + m[0].length);
    }
    return out;
  }

  // ---------------------------------------------------------------- source panel
  function renderCode(f, container, hlLines) {
    container.textContent = "";
    if (!f.code) {
      container.append(el("div", { class: "empty-note" },
        f.k === "toplevel" ? "Code that runs at the top level of " + fileOf(f) + " (outside any function). Its calls are listed in the tree."
                           : "No source available."));
      return;
    }
    const code = f.code;
    const fam = FAMILY[FILES[f.f].lang] || "c";
    const cls = highlight(code, fam);
    const lineStarts = [0];
    for (let i = 0; i < code.length; i++) if (code.charCodeAt(i) === 10) lineStarts.push(i + 1);
    const link = new Int32Array(code.length).fill(-1);
    f.calls.forEach((c, ci) => {
      const li = c.l - f.l;
      if (li < 0 || li >= lineStarts.length) return;
      const start = lineStarts[li] + c.c;
      if (code.substr(start, c.n.length) !== c.n) return;
      link.fill(ci, start, start + c.n.length);
    });
    const frag = document.createDocumentFragment();
    const hl = new Set(hlLines || []);
    for (let li = 0; li < lineStarts.length; li++) {
      const s = lineStarts[li], e = li + 1 < lineStarts.length ? lineStarts[li + 1] - 1 : code.length;
      const lineNo = f.l + li;
      const src = el("span", { class: "src" });
      let i = s;
      while (i < e) {
        let j = i + 1;
        while (j < e && cls[j] === cls[i] && link[j] === link[i]) j++;
        const text = code.slice(i, j);
        if (link[i] >= 0) {
          const c = f.calls[link[i]];
          const isSelf = c.t && c.t.length === 1 && c.t[0] === f.id;
          const kind = !c.t ? "" : c.x === "a" ? " amb" : c.x === "l" ? " low" : "";
          if (c.t && !isSelf) {
            src.append(el("span", { class: "call" + kind, "data-call": link[i], title: callTitle(c) }, text));
          } else {
            src.append(cls[i] ? el("span", { class: CLS[cls[i]] + (isSelf ? "" : ""), title: isSelf ? "recursive call" : null }, text) : text);
          }
        } else {
          src.append(cls[i] ? el("span", { class: CLS[cls[i]] }, text) : text);
        }
        i = j;
      }
      frag.append(el("div", { class: "ln" + (hl.has(lineNo) ? " hl" : ""), "data-line": lineNo },
        el("span", { class: "gutter" }, String(lineNo)), src));
    }
    const wrap = el("div", { class: "code" });
    wrap.append(frag);
    wrap.addEventListener("click", (ev) => {
      const span = ev.target.closest(".call");
      if (!span) return;
      const c = f.calls[+span.dataset.call];
      if (c.t.length === 1) go(c.t[0]);
      else showChoices(span, c.n, c.t);
    });
    container.append(wrap);
  }
  function callTitle(c) {
    if (c.t.length > 1) return c.t.length + " possible targets, click to choose";
    const t = FUNCS[c.t[0]];
    return qname(t) + "  —  " + fileOf(t) + ":" + t.l + (c.x === "l" ? "  (best guess)" : "");
  }
  function highlightLines(container, lines, scroll) {
    const set = new Set(lines);
    let first = null;
    for (const ln of container.querySelectorAll(".ln")) {
      const on = set.has(+ln.dataset.line);
      ln.classList.toggle("hl", on);
      if (on && !first) first = ln;
    }
    if (scroll && first) first.scrollIntoView({ block: "nearest" });
  }

  // ---------------------------------------------------------------- choice popup (ambiguous calls)
  const popup = $("#popup");
  function showChoices(anchor, name, ids) {
    popup.textContent = "";
    popup.append(el("div", { class: "popup-title" }, ids.length + " functions named " + name + " could be called here:"));
    const ul = el("ul", { class: "tree" });
    for (const id of ids) ul.append(fnRow(FUNCS[id], () => { hidePopup(); go(id); }, true));
    popup.append(ul);
    popup.hidden = false;
    const r = anchor.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    popup.style.left = Math.max(8, Math.min(r.left, innerWidth - pr.width - 8)) + "px";
    popup.style.top = (r.bottom + pr.height + 8 > innerHeight ? Math.max(8, r.top - pr.height - 4) : r.bottom + 4) + "px";
  }
  function hidePopup() { popup.hidden = true; }
  document.addEventListener("mousedown", (e) => { if (!popup.hidden && !popup.contains(e.target)) hidePopup(); });

  // ---------------------------------------------------------------- shared row builders
  function fnLabel(f, withScope = true) {
    const label = el("span", { class: "label" });
    if (withScope && f.s) label.append(el("span", { class: "scope" }, f.s + sep(f)));
    label.append(f.k === "toplevel" ? f.n : f.n + "()");
    return label;
  }
  function fnRow(f, onclick, showPath) {
    return el("li", null, el("div", { class: "row", onclick, title: qname(f) + "\n" + fileOf(f) + ":" + f.l },
      el("span", { class: "caret leaf" }, "▸"),
      el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]),
      fnLabel(f),
      showPath ? el("span", { class: "meta" }, fileOf(f) + ":" + f.l) : null));
  }

  // ---------------------------------------------------------------- call tree
  function buildCallTree(rootFn, dir, container, codeBox) {
    container.textContent = "";
    const ul = el("ul", { class: "tree calltree" });
    const root = treeNode({ type: "fn", id: rootFn.id, lines: [] }, dir, new Set(), 0, codeBox, rootFn);
    ul.append(root.li);
    container.append(ul);
    root.toggle(true);
    // open a second level for small trees so there is something to look at straight away
    const kids = root.li.querySelectorAll(":scope > ul > li");
    if (kids.length && kids.length <= 6) kids.forEach((li) => li._node && li._node.toggle(true));
    if (!kids.length) container.append(el("div", { class: "empty-note" },
      dir === "out" ? (rootFn.calls.length ? "Calls only external functions (library / not in this codebase). Tick “external” to show them."
                                           : "This function doesn’t call anything.")
                    : "No callers found in this codebase. It may be an entry point, a callback, or called dynamically."));
  }

  function treeNode(item, dir, ancestors, depth, codeBox, rootFn) {
    const li = el("li");
    const row = el("div", { class: "row" });
    li.append(row);
    let childUl = null, open = false;
    const node = { li, toggle };
    li._node = node;
    const caret = el("span", { class: "caret" }, "▸");
    row.append(caret);

    let kids = null; // lazily computed children
    let cycle = false;
    if (item.type === "fn") {
      const f = FUNCS[item.id];
      cycle = ancestors.has(item.id);
      kids = () => (dir === "out" ? outgoing(f) : incoming(f));
      row.append(el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]), fnLabel(f));
      if (item.lines.length > 1) row.append(el("span", { class: "badge", title: "called on lines " + item.lines.join(", ") }, "×" + item.lines.length));
      if (item.low) { row.classList.add("low"); row.append(el("span", { class: "badge low", title: "Best guess: resolved by name only" }, "guess")); }
      if (cycle) row.append(el("span", { class: "badge cycle", title: "Already shown above in this branch" }, "↻ recursive"));
      row.append(el("span", { class: "meta" }, fileOf(f) + ":" + f.l));
      if (depth > 0) row.append(el("span", { class: "go" }, "open ↗"));
      row.title = qname(f) + "\n" + fileOf(f) + ":" + f.l + (depth ? "\n\nClick to open · arrow to expand" : "");
      const n = (dir === "out" ? f.calls.some((c) => c.t) : callers[f.id].length);
      if (!n || cycle) caret.classList.add("leaf");
      row.addEventListener("click", (e) => {
        if (e.target === caret) return;
        if (depth === 0) { toggle(); return; }
        go(item.id, dir);
      });
      if (depth === 1 && dir === "out") {
        row.addEventListener("mouseenter", () => highlightLines(codeBox, item.lines, true));
        row.addEventListener("mouseleave", () => highlightLines(codeBox, [], false));
      }
    } else if (item.type === "amb") {
      kids = () => item.targets.map((id) => ({ type: "fn", id, lines: [] }));
      row.append(el("span", { class: "icon amb" }, "?"), el("span", { class: "label" }, item.name + "()"),
        el("span", { class: "badge warn", title: "Several functions share this name; any of them could be the target" }, item.targets.length + " candidates"));
      if (item.lines.length > 1) row.append(el("span", { class: "badge" }, "×" + item.lines.length));
      row.addEventListener("click", (e) => { if (e.target !== caret) toggle(); });
      if (depth === 1) {
        row.addEventListener("mouseenter", () => highlightLines(codeBox, item.lines, true));
        row.addEventListener("mouseleave", () => highlightLines(codeBox, [], false));
      }
    } else { // external
      row.classList.add("ext");
      caret.classList.add("leaf");
      row.append(el("span", { class: "icon ext" }, "·"),
        el("span", { class: "label" }, (item.q ? item.q + (item.q.includes("::") ? "::" : ".") : "") + item.name + "()"),
        el("span", { class: "meta" }, "external"));
      row.title = "Not defined in this codebase (library, built-in or unresolved)";
      if (depth === 1) {
        row.addEventListener("mouseenter", () => highlightLines(codeBox, item.lines, true));
        row.addEventListener("mouseleave", () => highlightLines(codeBox, [], false));
      }
    }
    caret.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });

    function toggle(force) {
      if (caret.classList.contains("leaf") || !kids) return;
      open = force === undefined ? !open : force;
      caret.classList.toggle("open", open);
      if (open && !childUl) {
        childUl = el("ul");
        const nextAnc = new Set(ancestors);
        if (item.type === "fn") nextAnc.add(item.id);
        for (const k of kids()) childUl.append(treeNode(k, dir, nextAnc, depth + 1, codeBox, rootFn).li);
        li.append(childUl);
      }
      if (childUl) childUl.hidden = !open;
    }
    return node;
  }

  // ---------------------------------------------------------------- explorer
  const explorer = $("#explorer");
  const dirTree = { dirs: new Map(), files: [] };
  FILES.forEach((file, i) => {
    const parts = file.p.split("/");
    let d = dirTree;
    for (const p of parts.slice(0, -1)) {
      if (!d.dirs.has(p)) d.dirs.set(p, { dirs: new Map(), files: [] });
      d = d.dirs.get(p);
    }
    d.files.push(i);
  });
  // collapse single-child directory chains: a/b/c
  function compact(name, d) {
    while (d.dirs.size === 1 && d.files.length === 0) {
      const [[n, child]] = d.dirs;
      name += "/" + n; d = child;
    }
    return [name, d];
  }
  const explorerNodes = new Map(); // key -> {li, open()}

  function explorerItem(key, iconCls, iconText, labelText, metaText, render, onSelect) {
    const li = el("li");
    const caret = el("span", { class: "caret" + (render ? "" : " leaf") }, "▸");
    const row = el("div", { class: "row", title: key.replace(/^[a-z]:/, "") }, caret,
      el("span", { class: "icon " + iconCls }, iconText), el("span", { class: "label" }, labelText),
      metaText ? el("span", { class: "meta" }, metaText) : null);
    li.append(row);
    let ul = null, isOpen = false;
    const open = (v = !isOpen) => {
      if (!render) return;
      isOpen = v;
      caret.classList.toggle("open", v);
      if (v && !ul) { ul = el("ul"); render(ul); li.append(ul); }
      if (ul) ul.hidden = !v;
    };
    caret.addEventListener("click", (e) => { e.stopPropagation(); open(); });
    row.addEventListener("click", () => (onSelect ? onSelect() : open()));
    const n = { li, row, open };
    explorerNodes.set(key, n);
    return n;
  }

  function renderDir(ul, d, prefix) {
    const dirs = [...d.dirs.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    for (const [n0, d0] of dirs) {
      const [name, dd] = compact(n0, d0);
      const path = prefix + name;
      ul.append(explorerItem("d:" + path, "dir", "▤", name + "/", null, (cu) => renderDir(cu, dd, path + "/")).li);
    }
    for (const fi of d.files.slice().sort((a, b) => FILES[a].p.localeCompare(FILES[b].p))) {
      const file = FILES[fi];
      const fns = byFile[fi];
      ul.append(explorerItem("f:" + file.p, "file", "▫", file.p.split("/").pop(), fns.length ? String(fns.filter((f) => f.k !== "toplevel").length) : null,
        fns.length ? (cu) => renderFile(cu, fi) : null).li);
    }
  }
  function renderFile(ul, fi) {
    const fns = byFile[fi].slice().sort((a, b) => a.l - b.l);
    const scopes = new Map();
    for (const f of fns) {
      if (!scopes.has(f.s)) scopes.set(f.s, []);
      scopes.get(f.s).push(f);
    }
    const addFns = (target, list) => {
      for (const f of list) {
        const item = explorerItem("fn:" + f.id, f.k, KIND_LETTER[f.k], f.k === "toplevel" ? f.n : f.n + "()", ":" + f.l, null, () => go(f.id));
        target.append(item.li);
      }
    };
    if (scopes.has("")) addFns(ul, scopes.get(""));
    for (const [s, list] of scopes) {
      if (!s) continue;
      ul.append(explorerItem("s:" + fi + ":" + s, "scope", "{}", s, String(list.length), (cu) => addFns(cu, list)).li);
    }
  }
  function revealInExplorer(f) {
    const parts = fileOf(f).split("/");
    // open directories along the path (keys may be compacted, so try every prefix)
    for (let i = 1; i < parts.length; i++) {
      const n = explorerNodes.get("d:" + parts.slice(0, i).join("/"));
      if (n) n.open(true);
    }
    const fileNode = explorerNodes.get("f:" + fileOf(f));
    if (fileNode) fileNode.open(true);
    if (f.s) { const s = explorerNodes.get("s:" + f.f + ":" + f.s); if (s) s.open(true); }
    for (const r of explorer.querySelectorAll(".row.selected")) r.classList.remove("selected");
    const n = explorerNodes.get("fn:" + f.id);
    if (n) { n.row.classList.add("selected"); n.row.scrollIntoView({ block: "nearest" }); }
  }
  renderDir(explorer, dirTree, "");
  $("#btn-collapse-explorer").addEventListener("click", () => {
    explorer.textContent = ""; explorerNodes.clear(); renderDir(explorer, dirTree, "");
  });

  // ---------------------------------------------------------------- views
  const main = $("#main");
  function showFunction(id, dir) {
    const f = FUNCS[id];
    if (!f) return showOverview();
    document.title = f.n + " · " + DATA.name;
    main.textContent = "";
    const nCallees = new Set(f.calls.flatMap((c) => c.t || [])).size;
    const nExt = f.calls.filter((c) => !c.t).length;
    main.append(el("div", { class: "fn-header" },
      el("div", { class: "fn-title" }, el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]), fnLabel(f)),
      el("div", { class: "fn-sub" },
        el("span", { class: "mono" }, fileOf(f) + ":" + f.l + (f.e > f.l ? "–" + f.e : "")),
        el("span", null, f.k),
        el("span", null, "calls " + nCallees + " function" + (nCallees === 1 ? "" : "s") + (nExt ? " (+" + nExt + " external)" : "")),
        el("span", null, "called from " + callers[id].length + " place" + (callers[id].length === 1 ? "" : "s")))));

    const body = el("div", { class: "fn-body" });
    const treePanel = el("section", { class: "panel tree-panel" });
    const codePanel = el("section", { class: "panel code-panel" });
    const treeBox = el("div", { class: "panel-scroll" });
    const codeBox = el("div", { class: "panel-scroll" });
    const tabOut = el("button", { class: "tab" + (dir === "out" ? " active" : ""), onclick: () => go(id, "out") }, "Calls ▸");
    const tabIn = el("button", { class: "tab" + (dir === "in" ? " active" : ""), onclick: () => go(id, "in") }, "◂ Callers");
    const opt = (key, label, title) => el("label", { title },
      el("input", { type: "checkbox", checked: prefs[key], onchange: (e) => { prefs[key] = e.target.checked; savePrefs(); buildCallTree(f, dir, treeBox, codeBox); } }), label);
    treePanel.append(el("div", { class: "pane-title" }, el("div", { class: "tabs" }, tabOut, tabIn),
      dir === "out" ? el("div", { class: "opts" },
        opt("ext", "external", "Show calls to functions that are not defined in this codebase"),
        opt("low", "guesses", "Show links resolved by name only (lower confidence)")) : null), treeBox);
    const split = el("div", { class: "splitter" });
    codePanel.append(el("div", { class: "pane-title" }, el("span", null, "Source"),
      el("span", { class: "opts muted" }, "click a highlighted call to follow it")), codeBox);
    body.append(treePanel, split, codePanel);
    main.append(body);
    if (prefs.treeW) treePanel.style.width = prefs.treeW + "px";
    dragResize(split, (x) => {
      const w = Math.max(220, x - treePanel.getBoundingClientRect().left);
      treePanel.style.width = w + "px"; prefs.treeW = w; savePrefs();
    });
    renderCode(f, codeBox);
    buildCallTree(f, dir, treeBox, codeBox);
    revealInExplorer(f);
  }

  function showOverview() {
    document.title = DATA.name + " · codeviz";
    main.textContent = "";
    for (const r of explorer.querySelectorAll(".row.selected")) r.classList.remove("selected");
    const s = DATA.stats;
    const real = FUNCS.filter((f) => f.k !== "toplevel");
    const langs = {};
    for (const f of FILES) langs[f.lang] = (langs[f.lang] || 0) + 1;
    const card = (num, lbl) => el("div", { class: "card" }, el("div", { class: "num" }, num.toLocaleString()), el("div", { class: "lbl" }, lbl));

    // entry points: nothing calls them, but they call into the codebase; rank by how much they reach
    const reach = (id) => {
      const seen = new Set([id]), stack = [id];
      while (stack.length && seen.size < 5000) {
        for (const c of FUNCS[stack.pop()].calls) if (c.t && c.x !== "a") for (const t of c.t) if (!seen.has(t)) { seen.add(t); stack.push(t); }
      }
      return seen.size - 1;
    };
    const entries = FUNCS.filter((f) => !callers[f.id].length && f.calls.some((c) => c.t))
      .map((f) => ({ f, n: reach(f.id) })).sort((a, b) => b.n - a.n).slice(0, 30);
    const popular = real.map((f) => ({ f, n: new Set(callers[f.id].map((c) => c.from)).size }))
      .filter((x) => x.n > 1).sort((a, b) => b.n - a.n).slice(0, 30);
    const list = (items, metaFn) => {
      const ul = el("ul", { class: "tree fn-list" });
      for (const { f, n } of items) {
        const li = fnRow(f, () => go(f.id), false);
        li.firstChild.append(el("span", { class: "badge" }, metaFn(n)), el("span", { class: "meta" }, fileOf(f)));
        ul.append(li);
      }
      return ul;
    };
    main.append(el("div", { class: "overview" },
      el("h1", null, DATA.name),
      el("div", { class: "muted" }, "Generated " + DATA.generated + " · " +
        Object.entries(langs).sort((a, b) => b[1] - a[1]).map(([l, n]) => n + " " + l).join(", ")),
      el("div", { class: "cards" }, card(s.files, "files"), card(s.functions, "functions"), card(s.calls, "call sites"),
        card(s.resolved, "linked to code here"), card(s.external, "external / library")),
      el("p", { class: "help" }, "Pick a function in the explorer or search with ", el("kbd", null, "/"),
        ". The left panel is a tree of everything the function calls (switch to ", el("b", null, "Callers"),
        " for the reverse). Expand with the arrows, click a name to jump to it, and use ", el("kbd", null, "Alt"), "+",
        el("kbd", null, "←"), " to go back. Calls in the source are links too. Links are resolved by name, so ",
        el("span", { style: "color:var(--warn)" }, "amber"), " marks a name with several candidates and dashed underlines mark best guesses."),
      entries.length ? el("h2", null, "Entry points (not called from anywhere, ranked by how much they reach)") : null,
      entries.length ? list(entries, (n) => n + " reachable") : null,
      popular.length ? el("h2", null, "Most called") : null,
      popular.length ? list(popular, (n) => n + " callers") : null));
  }

  // ---------------------------------------------------------------- routing
  function go(id, dir) {
    const h = "#/f/" + id + (dir === "in" ? "/in" : "");
    if (location.hash !== h) location.hash = h; else route();
  }
  function route() {
    hidePopup();
    const m = /^#\/f\/(\d+)(\/in)?/.exec(location.hash);
    if (m) showFunction(+m[1], m[2] ? "in" : "out"); else showOverview();
    main.scrollTop = 0;
  }
  window.addEventListener("hashchange", route);

  // ---------------------------------------------------------------- search
  const search = $("#search"), results = $("#search-results");
  const index = FUNCS.filter((f) => f.k !== "toplevel").map((f) => ({ f, n: f.n.toLowerCase(), q: qname(f).toLowerCase(), p: fileOf(f).toLowerCase() }));
  let active = 0, shown = [];
  function runSearch() {
    const q = search.value.trim().toLowerCase();
    results.textContent = "";
    if (!q) { results.hidden = true; return; }
    const scored = [];
    for (const it of index) {
      let s = -1;
      if (it.n === q) s = 100; else if (it.n.startsWith(q)) s = 80; else if (it.q === q || it.q.endsWith(q)) s = 75;
      else if (it.n.includes(q)) s = 60; else if (it.q.includes(q)) s = 40; else if (it.p.includes(q)) s = 20;
      if (s >= 0) scored.push([s - it.n.length * 0.01, it]);
    }
    scored.sort((a, b) => b[0] - a[0]);
    shown = scored.slice(0, 40).map((x) => x[1].f);
    active = 0;
    shown.forEach((f, i) => results.append(el("li", { class: i === 0 ? "active" : "", onmousedown: (e) => { e.preventDefault(); pick(i); } },
      el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]), fnLabel(f), el("span", { class: "path" }, fileOf(f) + ":" + f.l))));
    if (!shown.length) results.append(el("li", { class: "muted" }, "No functions match"));
    results.hidden = false;
  }
  function pick(i) { const f = shown[i]; if (!f) return; results.hidden = true; search.blur(); go(f.id); }
  search.addEventListener("input", runSearch);
  search.addEventListener("focus", () => { if (search.value) runSearch(); });
  search.addEventListener("blur", () => setTimeout(() => (results.hidden = true), 100));
  search.addEventListener("keydown", (e) => {
    const items = results.querySelectorAll("li");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!shown.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      items.forEach((li, i) => li.classList.toggle("active", i === active));
      items[active].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") { pick(active); }
    else if (e.key === "Escape") { search.value = ""; results.hidden = true; search.blur(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== search) { e.preventDefault(); search.focus(); search.select(); }
    if (e.key === "Escape") hidePopup();
  });

  // ---------------------------------------------------------------- chrome
  function dragResize(handle, onMove) {
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      handle.classList.add("dragging");
      const move = (ev) => onMove(ev.clientX);
      const up = () => { handle.classList.remove("dragging"); removeEventListener("mousemove", move); removeEventListener("mouseup", up); };
      addEventListener("mousemove", move); addEventListener("mouseup", up);
    });
  }
  const sidebar = $(".sidebar");
  if (prefs.sidebar) sidebar.style.width = prefs.sidebar + "px";
  dragResize($("#split-sidebar"), (x) => { const w = Math.max(160, Math.min(x, innerWidth - 300)); sidebar.style.width = w + "px"; prefs.sidebar = w; savePrefs(); });
  function applyTheme() { if (prefs.theme) document.documentElement.dataset.theme = prefs.theme; else delete document.documentElement.dataset.theme; }
  applyTheme();
  $("#btn-theme").addEventListener("click", () => {
    const dark = prefs.theme ? prefs.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    prefs.theme = dark ? "light" : "dark"; savePrefs(); applyTheme();
  });
  $("#btn-back").addEventListener("click", () => history.back());
  $("#btn-fwd").addEventListener("click", () => history.forward());
  $("#btn-home").addEventListener("click", () => { location.hash = "#/"; });
  $("#project-name").textContent = DATA.name;
  $("#stats").innerHTML = "";
  $("#stats").append(el("span", { class: "stats-text" }, DATA.stats.functions.toLocaleString() + " functions · " + DATA.stats.files.toLocaleString() + " files"));

  route();
})();
