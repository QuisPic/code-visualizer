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
    const d = { ext: false, low: true, theme: null, sidebar: null, treeW: null, view: "graph", legend: false };
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
            src.append(el("span", { class: "call" + kind, "data-call": link[i], "data-hc": hcSpec(c),
              "data-hc-hint": c.x === "a" ? "Click to choose one" : c.x === "l" ? "Best guess: matched by name only · click to open" : "Click to open" }, text));
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
  const hcSpec = (c) => (!c.t ? "x:" + c.n : c.t.length > 1 ? "a:" + c.t.join(",") : String(c.t[0]));
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

  // ---------------------------------------------------------------- hover cards
  // Any element with data-hc gets a card after a short hover: "<id>" for a function, "a:<id>,<id>"
  // for an ambiguous call, "x:<name>" for an external one. data-hc-hint adds a muted footer line.
  const hovercard = el("div", { class: "hovercard", role: "tooltip" });
  hovercard.hidden = true;
  document.body.append(hovercard);
  let hcTimer = 0, hcAnchor = null;

  // the declaration part of a function: its first line(s) up to the body
  function signature(f) {
    if (!f.code) return "";
    const lines = f.code.split("\n");
    let sig = "";
    for (let i = 0; i < Math.min(lines.length, 4); i++) {
      sig += (i ? "\n" : "") + lines[i];
      const t = lines[i].trimEnd();
      if (t.includes("{") || t.endsWith(":") || t.endsWith("=>")) break;
    }
    sig = sig.replace(/\s*\{[^{}]*$/, "").replace(/\s*\{\s*$/, "");
    return sig.length > 300 ? sig.slice(0, 299) + "…" : sig;
  }
  function highlighted(code, fam) {
    const cls = highlight(code, fam);
    const out = el("code", { class: "hc-sig" });
    for (let i = 0; i < code.length;) {
      let j = i + 1;
      while (j < code.length && cls[j] === cls[i]) j++;
      out.append(cls[i] ? el("span", { class: CLS[cls[i]] }, code.slice(i, j)) : code.slice(i, j));
      i = j;
    }
    return out;
  }
  function fnCardBody(f) {
    const nCallees = new Set(f.calls.flatMap((c) => c.t || [])).size;
    const nCallers = new Set(callers[f.id].map((c) => c.from)).size;
    const lines = f.e - f.l + 1;
    const parts = [
      el("div", { class: "hc-head" }, el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]), fnLabel(f)),
      el("div", { class: "hc-file" }, fileOf(f) + ":" + f.l + (f.k === "toplevel" ? "" : " · " + lines + " line" + (lines === 1 ? "" : "s"))),
    ];
    const sig = signature(f);
    if (sig) parts.push(highlighted(sig, FAMILY[FILES[f.f].lang] || "c"));
    if (f.d) parts.push(el("div", { class: "hc-doc" }, f.d));
    parts.push(el("div", { class: "hc-stats" },
      el("span", null, el("b", null, String(nCallees)), " callee" + (nCallees === 1 ? "" : "s")),
      el("span", null, el("b", null, String(nCallers)), " caller" + (nCallers === 1 ? "" : "s"))));
    return parts;
  }
  function fillCard(spec, hint) {
    hovercard.textContent = "";
    if (spec.startsWith("a:")) {
      const ids = spec.slice(2).split(",").map(Number);
      hovercard.append(el("div", { class: "hc-head" }, el("span", { class: "icon amb" }, "?"),
        el("span", { class: "label" }, FUNCS[ids[0]].n + "()")),
        el("div", { class: "hc-note warn" }, ids.length + " functions share this name; any of them could be called here:"));
      const ul = el("ul", { class: "hc-list" });
      for (const id of ids.slice(0, 8)) ul.append(el("li", null, fnLabel(FUNCS[id]), el("span", { class: "muted" }, " " + fileOf(FUNCS[id]) + ":" + FUNCS[id].l)));
      if (ids.length > 8) ul.append(el("li", { class: "muted" }, "… and " + (ids.length - 8) + " more"));
      hovercard.append(ul);
    } else if (spec.startsWith("x:")) {
      hovercard.append(el("div", { class: "hc-head" }, el("span", { class: "icon ext" }, "·"), el("span", { class: "label" }, spec.slice(2) + "()")),
        el("div", { class: "hc-note" }, "Not defined in this codebase: a library, a built-in, or a call that couldn’t be resolved."));
    } else {
      const f = FUNCS[+spec];
      if (!f) return false;
      hovercard.append(...fnCardBody(f));
    }
    if (hint) hovercard.append(el("div", { class: "hc-hint" }, hint));
    return true;
  }
  function placeCard(anchor) {
    const r = anchor.getBoundingClientRect();
    hovercard.style.left = "0px"; hovercard.style.top = "0px";
    const cw = hovercard.offsetWidth, ch = hovercard.offsetHeight;
    const left = Math.max(8, Math.min(r.left, innerWidth - cw - 8));
    const below = r.bottom + 6, above = r.top - ch - 6;
    hovercard.style.left = left + "px";
    hovercard.style.top = (below + ch <= innerHeight - 8 || above < 8 ? Math.min(below, innerHeight - ch - 8) : above) + "px";
  }
  function hideCard() { clearTimeout(hcTimer); hcAnchor = null; hovercard.hidden = true; }
  document.addEventListener("mouseover", (e) => {
    const a = e.target.closest && e.target.closest("[data-hc]");
    if (a === hcAnchor) return;
    hideCard();
    if (!a || e.buttons) return;
    hcAnchor = a;
    hcTimer = setTimeout(() => {
      if (hcAnchor !== a || !a.isConnected) return;
      if (!fillCard(a.dataset.hc, a.dataset.hcHint)) return;
      hovercard.hidden = false;
      placeCard(a);
    }, 380);
  });
  for (const ev of ["pointerdown", "wheel", "keydown"]) document.addEventListener(ev, hideCard, true);
  // hovering a graph node scrolls the source to the call, which must not close the node's card
  document.addEventListener("scroll", (e) => { if (hcAnchor && e.target.contains && e.target.contains(hcAnchor)) hideCard(); }, true);

  // ---------------------------------------------------------------- shared row builders
  function fnLabel(f, withScope = true) {
    const label = el("span", { class: "label" });
    if (withScope && f.s) label.append(el("span", { class: "scope" }, f.s + sep(f)));
    label.append(f.k === "toplevel" ? f.n : f.n + "()");
    return label;
  }
  function fnRow(f, onclick, showPath) {
    return el("li", null, el("div", { class: "row", onclick, "data-hc": f.id },
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
      row.dataset.hc = f.id;
      if (depth) row.dataset.hcHint = "Click to open · arrow to expand";
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

  // ---------------------------------------------------------------- call graph (node-link view)
  const SVGNS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVGNS, tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
    for (const c of children) if (c != null) node.append(c);
    return node;
  }
  const measureCtx = document.createElement("canvas").getContext("2d");
  function textWidth(text, font) { measureCtx.font = font; return measureCtx.measureText(text).width; }
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  const G = { nodeH: 42, rowGap: 14, colGap: 70, maxLabel: 46, font: "", metaFont: "", sans: "" };

  function buildCallGraph(rootFn, dir, container, codeBox, showSource) {
    container.textContent = "";
    const mono = getComputedStyle(document.documentElement).getPropertyValue("--mono").trim();
    const sans = getComputedStyle(document.documentElement).getPropertyValue("--sans").trim();
    G.font = "600 12px " + mono; G.metaFont = "11px " + sans; G.sans = sans;

    // graph nodes are created lazily as branches are expanded
    const makeNode = (item, parent) => {
      const n = { item, parent, depth: parent ? parent.depth + 1 : 0, kids: null, open: false,
                  key: (parent ? parent.key + ">" : "") + (item.type === "fn" ? item.id : item.type + ":" + item.name) };
      const anc = new Set();
      for (let p = parent; p; p = p.parent) if (p.item.type === "fn") anc.add(p.item.id);
      n.cycle = item.type === "fn" && anc.has(item.id);
      if (item.type === "fn") {
        const f = FUNCS[item.id];
        n.expandable = !n.cycle && (dir === "out" ? f.calls.some((c) => c.t) : callers[f.id].length > 0);
        n.label = (f.s ? f.s + sep(f) : "") + (f.k === "toplevel" ? f.n : f.n + "()");
        n.meta = fileOf(f).split("/").pop() + ":" + f.l;
        n.kind = f.k;
      } else if (item.type === "amb") {
        n.expandable = true;
        n.label = item.name + "()";
        n.meta = item.targets.length + " candidates";
        n.kind = "amb";
      } else {
        n.expandable = false;
        n.label = (item.q ? item.q + (item.q.includes("::") ? "::" : ".") : "") + item.name + "()";
        n.meta = "external";
        n.kind = "ext";
      }
      if (n.expandable && item.type === "fn" && !childItems(n).length) n.expandable = false;
      n.label = clip(n.label, G.maxLabel);
      n.metaText = n.cycle ? "↻ recursive · " + n.meta : item.low ? "guess · " + n.meta : n.meta;
      n.w = Math.max(textWidth(n.label, G.font) + 34, textWidth(n.metaText, G.metaFont) + 34, 90) + (n.expandable ? 20 : 0);
      return n;
    };
    // what a node would expand to (cheap: no graph nodes are made until it is actually opened)
    const childItems = (n) => {
      if (!n.items) {
        const it = n.item;
        n.items = it.type === "fn" ? (dir === "out" ? outgoing(FUNCS[it.id]) : incoming(FUNCS[it.id]))
          : it.type === "amb" ? it.targets.map((id) => ({ type: "fn", id, lines: [] })) : [];
      }
      return n.items;
    };
    const children = (n) => {
      if (!n.kids) n.kids = childItems(n).map((k) => makeNode(k, n));
      return n.kids;
    };
    const root = makeNode({ type: "fn", id: rootFn.id, lines: [] }, null);
    root.open = root.expandable;
    if (root.open) {
      const kids = children(root);
      if (kids.length <= 6) for (const k of kids) if (k.expandable && !k.cycle) k.open = true;
    }

    // ---- view: svg with pan/zoom
    const wrap = el("div", { class: "graph-wrap" });
    const svgEl = svg("svg", { class: "graph" });
    const viewport = svg("g");
    const edgeLayer = svg("g", { class: "edges" });
    const nodeLayer = svg("g", { class: "nodes" });
    viewport.append(edgeLayer, nodeLayer);
    svgEl.append(viewport);
    const tools = el("div", { class: "graph-tools" },
      el("button", { title: "Zoom in", onclick: () => zoomBy(1.25) }, "+"),
      el("button", { title: "Zoom out", onclick: () => zoomBy(0.8) }, "−"),
      el("button", { title: "Fit to view", onclick: () => fit() }, "Fit"),
      el("button", { title: "Expand one more level", onclick: () => expandLevel() }, "Expand"),
      el("button", { title: "Collapse to the first level", onclick: () => collapseAll() }, "Collapse"),
      el("button", { title: "Put dragged nodes back in their places", onclick: () => tidy() }, "Tidy"),
      el("button", { title: "What the colours and lines mean", class: prefs.legend ? "on" : null, onclick: (e) => {
        prefs.legend = !prefs.legend; savePrefs(); legend.hidden = !prefs.legend; e.currentTarget.classList.toggle("on", prefs.legend);
      } }, "?"));
    const legend = graphLegend();
    legend.hidden = !prefs.legend;
    wrap.append(svgEl, tools, legend);
    container.append(wrap);
    let view = { x: 0, y: 0, k: 1 };
    const applyView = () => viewport.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);

    let positions = new Map(); // key -> {x, y, n}: tidy-tree layout, before any dragging
    function layout() {
      // column widths per depth, rows by leaf count (tidy tree)
      const colW = [];
      const visit = (n) => {
        colW[n.depth] = Math.max(colW[n.depth] || 0, n.w);
        if (n.open) for (const k of children(n)) visit(k);
      };
      visit(root);
      const colX = [0];
      for (let d = 1; d < colW.length; d++) colX[d] = colX[d - 1] + colW[d - 1] + G.colGap;
      positions = new Map();
      let row = 0;
      const place = (n) => {
        let y;
        const kids = n.open ? children(n) : [];
        if (!kids.length) { y = row * (G.nodeH + G.rowGap); row++; }
        else { const ys = kids.map(place); y = (ys[0] + ys[ys.length - 1]) / 2; }
        // callers grow to the left: mirror x and right-align nodes in their column
        const x = dir === "out" ? colX[n.depth] : -colX[n.depth] - n.w;
        positions.set(n.key, { x, y, n });
        return y;
      };
      place(root);
    }
    // where a node is drawn: its layout slot plus its own and its ancestors' drag offsets
    // (dragging a node carries its subtree along)
    function pos(n) {
      const p = positions.get(n.key);
      let x = p.x, y = p.y;
      for (let a = n; a; a = a.parent) { x += a.dx || 0; y += a.dy || 0; }
      return { x, y };
    }
    const visibleKids = (n) => (n.open ? children(n) : []);

    function edgePath(n) {
      const p = pos(n.parent), c = pos(n);
      const cy = c.y + G.nodeH / 2, py = p.y + G.nodeH / 2;
      const x1 = dir === "out" ? p.x + n.parent.w : p.x, x2 = dir === "out" ? c.x : c.x + n.w;
      const mx = (x1 + x2) / 2;
      return { d: `M${x1},${py} C${mx},${py} ${mx},${cy} ${x2},${cy}`, x2, cy };
    }
    function placeNode(n) {
      const c = pos(n);
      n.g.setAttribute("transform", `translate(${c.x},${c.y})`);
      if (n.edge) {
        const e = edgePath(n);
        n.edge.setAttribute("d", e.d);
        if (n.edgeLabel) { n.edgeLabel.setAttribute("x", e.x2 + (dir === "out" ? -6 : 6)); n.edgeLabel.setAttribute("y", e.cy - 5); }
      }
    }
    function raise(n) { nodeLayer.append(n.g); for (const k of visibleKids(n)) raise(k); }
    function placeSubtree(n) { placeNode(n); for (const k of visibleKids(n)) placeSubtree(k); }

    function draw() {
      edgeLayer.textContent = ""; nodeLayer.textContent = "";
      for (const { n } of positions.values()) {
        n.edge = n.edgeLabel = null;
        if (!n.parent) continue;
        const cls = "edge" + (n.kind === "ext" ? " ext" : "") + (n.item.low ? " low" : "") + (n.kind === "amb" ? " amb" : "");
        n.edge = svg("path", { class: cls });
        edgeLayer.append(n.edge);
        if (n.item.lines && n.item.lines.length > 1) {
          n.edgeLabel = svg("text", { class: "edge-label", "text-anchor": dir === "out" ? "end" : "start" }, "×" + n.item.lines.length);
          edgeLayer.append(n.edgeLabel);
        }
      }
      // nodes that were dragged are drawn last so they sit on top of the ones they were dropped on
      const moved = (n) => { for (let a = n; a; a = a.parent) if (a.dx || a.dy) return true; return false; };
      const order = [...positions.values()].map((p) => p.n);
      order.sort((a, b) => moved(a) - moved(b));
      for (const n of order) {
        const g = svg("g", { class: "gnode k-" + n.kind + (n.depth === 0 ? " root" : "") + (n.item.low ? " low" : "")
          + (n.cycle ? " cycle" : "") + (n.key === selectedKey ? " selected" : "") });
        g._node = n;
        g.append(svg("rect", { class: "box", width: n.w, height: G.nodeH, rx: 7 }));
        const tx0 = dir === "in" && n.expandable ? 14 : 0; // leave room for the left-side toggle
        g.append(svg("rect", { class: "stripe", width: 4, height: G.nodeH - 10, x: tx0, y: 5, rx: 2 }));
        g.append(svg("text", { class: "glabel", x: tx0 + 12, y: 17 }, n.label));
        g.append(svg("text", { class: "gmeta", x: tx0 + 12, y: 33 }, n.metaText));
        const isFn = n.item.type === "fn";
        const how = [n.kind === "ext" ? null : "click to see its code", isFn && n.depth ? "double-click to open" : null,
                     n.expandable ? (n.open ? "− to collapse" : "+ to expand (shift: 3 levels)") : null, "drag to move"].filter(Boolean).join(" · ");
        g.setAttribute("data-hc", isFn ? String(n.item.id) : n.kind === "amb" ? "a:" + n.item.targets.join(",")
          : "x:" + n.label.replace(/\(\)$/, ""));
        g.setAttribute("data-hc-hint", how[0].toUpperCase() + how.slice(1));
        if (n.expandable) {
          const tx = dir === "out" ? n.w - 2 : 2;
          // collapsed: a pill saying how many calls are hidden behind the node; open: a "−" circle
          const label = n.open ? "−" : "+" + childItems(n).length;
          const pw = n.open ? 18 : Math.max(18, textWidth(label, "700 11px " + G.sans) + 10);
          g.append(svg("g", { class: "toggle" + (n.open ? "" : " closed"), transform: `translate(${tx},${G.nodeH / 2})` },
            svg("rect", { x: -pw / 2, y: -9, width: pw, height: 18, rx: 9 }),
            svg("text", { "text-anchor": "middle", y: n.open ? 4.5 : 4 }, label)));
        }
        g.addEventListener("mouseenter", () => {
          if (drag && drag.moved) return;
          markPath(n);
          if (n.depth === 1 && dir === "out" && showingRoot()) highlightLines(codeBox, n.item.lines, true);
        });
        g.addEventListener("mouseleave", () => {
          if (drag && drag.moved) return;
          for (const p of svgEl.querySelectorAll(".hot")) p.classList.remove("hot");
          if (n.depth === 1 && dir === "out" && showingRoot()) highlightLines(codeBox, [], false);
        });
        n.g = g;
        nodeLayer.append(g);
      }
      for (const { n } of positions.values()) placeNode(n);
    }
    function markPath(n) {
      for (const p of svgEl.querySelectorAll(".hot")) p.classList.remove("hot");
      for (let p = n; p; p = p.parent) { p.g && p.g.classList.add("hot"); p.edge && p.edge.classList.add("hot"); }
    }

    function rerender(anchor) {
      const before = anchor && pos(anchor);
      layout(); draw();
      const after = anchor && pos(anchor);
      if (before && after) { // keep the clicked node where it was on screen
        view.x += (before.x - after.x) * view.k; view.y += (before.y - after.y) * view.k; applyView();
      }
    }
    function toggle(n) { if (!n.expandable) return; n.open = !n.open; rerender(n); }
    function expandDeep(n, levels) {
      const MAX_NODES = 400; // stop before a fan-out explosion makes the graph unreadable
      let count = positions.size, frontier = [n];
      for (let d = 0; d < levels && frontier.length; d++) {
        const next = [];
        for (const m of frontier) {
          if (!m.expandable || m.cycle) continue;
          if (!m.open) {
            if (count + childItems(m).length > MAX_NODES) { frontier = []; break; }
            m.open = true; count += childItems(m).length;
          }
          next.push(...children(m));
        }
        if (frontier.length) frontier = next;
      }
      rerender(n);
    }
    function expandLevel() {
      let frontier = [root];
      while (frontier.length) { // find the shallowest collapsed level and open it
        const closed = frontier.filter((n) => n.expandable && !n.open);
        if (closed.length) { closed.forEach((n) => (n.open = true)); break; }
        frontier = frontier.flatMap((n) => (n.open ? children(n) : []));
      }
      layout(); draw(); fit();
    }
    function collapseAll() {
      const walk = (n) => { if (n.kids) n.kids.forEach((k) => { k.open = false; walk(k); }); };
      walk(root); root.open = root.expandable; layout(); draw(); fit();
    }
    function tidy() {
      const walk = (n) => { n.dx = n.dy = 0; if (n.kids) n.kids.forEach(walk); };
      walk(root); layout(); draw(); fit();
    }
    function bounds() {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const { n } of positions.values()) {
        const { x, y } = pos(n);
        x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + n.w); y1 = Math.max(y1, y + G.nodeH);
      }
      return { x0, y0, x1, y1 };
    }
    function fit() {
      const b = bounds(), W = wrap.clientWidth || 600, H = wrap.clientHeight || 400, pad = 24;
      const k = Math.max(0.45, Math.min(1, (W - 2 * pad) / (b.x1 - b.x0), (H - 2 * pad) / (b.y1 - b.y0)));
      const rootPos = pos(root);
      view.k = k;
      // horizontally: start at the root's side; vertically: centre, but keep the root in view
      view.x = dir === "out" ? pad - b.x0 * k : W - pad - b.x1 * k;
      const h = (b.y1 - b.y0) * k;
      view.y = h <= H - 2 * pad ? (H - h) / 2 - b.y0 * k : H / 2 - (rootPos.y + G.nodeH / 2) * k;
      applyView();
    }
    function zoomBy(f, cx, cy) {
      const W = wrap.clientWidth, H = wrap.clientHeight;
      cx = cx ?? W / 2; cy = cy ?? H / 2;
      const k = Math.max(0.15, Math.min(2.5, view.k * f));
      view.x = cx - (cx - view.x) * (k / view.k); view.y = cy - (cy - view.y) * (k / view.k); view.k = k;
      applyView();
    }

    // Pointer handling. On a node: click expands/collapses, double-click opens the function,
    // drag moves the node (with its subtree). On the background: drag pans.
    // Clicks are detected on pointerup rather than with click/dblclick events because expanding
    // a node redraws the graph, which would swallow the second click of a double-click.
    let drag = null, lastTap = null;
    svgEl.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const g = e.target.closest(".gnode");
      const n = g ? g._node : null;
      drag = { n, onToggle: !!e.target.closest(".toggle"), shift: e.shiftKey, x: e.clientX, y: e.clientY, id: e.pointerId, moved: false,
               vx: view.x, vy: view.y, dx: n ? n.dx || 0 : 0, dy: n ? n.dy || 0 : 0 };
    });
    svgEl.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved) {
        if (Math.hypot(dx, dy) < 4) return;
        drag.moved = true; svgEl.setPointerCapture(drag.id);
        wrap.classList.add(drag.n ? "dragging-node" : "panning");
        if (drag.n) { markPath(drag.n); raise(drag.n); }
      }
      if (drag.n) {
        drag.n.dx = drag.dx + dx / view.k; drag.n.dy = drag.dy + dy / view.k;
        placeSubtree(drag.n);
      } else {
        view.x = drag.vx + dx; view.y = drag.vy + dy; applyView();
      }
    });
    const endDrag = () => {
      const d = drag;
      drag = null;
      wrap.classList.remove("panning", "dragging-node");
      if (!d || d.moved || !d.n) return;
      const n = d.n;
      if (d.onToggle) { lastTap = null; if (d.shift && !n.open) expandDeep(n, 3); else toggle(n); return; }
      const now = performance.now();
      const isDouble = lastTap && lastTap.key === n.key && now - lastTap.t < 400;
      lastTap = isDouble ? null : { key: n.key, t: now };
      if (isDouble && n.item.type === "fn" && n.depth > 0) go(n.item.id, dir);
      else select(n);
    };
    // selecting a node shows its code in the Source panel
    let selectedKey = root.key;
    const showingRoot = () => +codeBox.dataset.fn === rootFn.id;
    function select(n) {
      selectedKey = n.key;
      for (const g of nodeLayer.querySelectorAll(".gnode.selected")) g.classList.remove("selected");
      n.g.classList.add("selected");
      if (n.item.type === "fn") { showSource(n.item.id); return; }
      showSource(null, n.item.type === "amb"
        ? n.item.targets.length + " functions are named " + n.label + " — expand the node with + to see them, then select one."
        : n.label + " is not defined in this codebase (library, built-in or unresolved), so there is no code to show.");
    }
    svgEl.addEventListener("pointerup", endDrag);
    svgEl.addEventListener("pointercancel", () => { drag = null; wrap.classList.remove("panning", "dragging-node"); });
    svgEl.addEventListener("wheel", (e) => { // wheel / pinch zooms around the cursor, shift+wheel scrolls sideways
      e.preventDefault();
      const r = svgEl.getBoundingClientRect();
      if (e.shiftKey) { view.x -= e.deltaY || e.deltaX; applyView(); return; }
      const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomBy(Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    layout(); draw();
    requestAnimationFrame(fit);
    if (!root.expandable) container.append(el("div", { class: "empty-note graph-empty" },
      dir === "out" ? (rootFn.calls.length ? "Calls only external functions. Tick “external” to show them." : "This function doesn’t call anything.")
                    : "No callers found in this codebase. It may be an entry point, a callback, or called dynamically."));
  }


  function graphLegend() {
    const line = (cls) => svg("svg", { width: 34, height: 10 }, svg("path", { class: "edge " + cls, d: "M1,5 L33,5" }));
    const stripe = (cls) => el("span", { class: "lg-stripe " + cls });
    const row = (sample, text) => el("li", null, el("span", { class: "lg-sample" }, sample), text);
    return el("div", { class: "graph-legend" },
      el("div", { class: "lg-title" }, "Legend"),
      el("ul", null,
        row(stripe("function"), "function"), row(stripe("method"), "method"), row(stripe("constructor"), "constructor"),
        row(stripe("toplevel"), "top-level code of a file"),
        row(line(""), "call, resolved with confidence"), row(line("low"), "best guess (matched by name only)"),
        row(line("amb"), "several functions share the name"), row(line("ext"), "external (not in this codebase)"),
        row(el("span", { class: "lg-pill" }, "+5"), "5 more calls hidden: click to expand"),
        row(el("span", { class: "lg-text" }, "×3"), "called 3 times from the same function"),
        row(el("span", { class: "lg-text" }, "↻"), "recursion: already shown above in this branch")));
  }

  // ---------------------------------------------------------------- impact (transitive callers)
  // Everything that can end up calling `f`, grouped by how many calls away it is. A function counts as
  // "sure" when some shortest chain from it to `f` uses only confident links.
  function impactOf(f, withGuesses) {
    const MAX = 5000;
    const info = new Map([[f.id, { depth: 0, sure: true, via: null, lines: [] }]]);
    let frontier = [f.id];
    for (let depth = 1; frontier.length && info.size < MAX; depth++) {
      const next = [];
      for (const id of frontier) {
        const here = info.get(id);
        for (const c of callerLinks()[id]) {
          if (c.x !== "h" && !withGuesses) continue;
          const sure = here.sure && c.x === "h";
          const seen = info.get(c.from);
          if (!seen) {
            info.set(c.from, { depth, sure, via: id, lines: [c.line] });
            next.push(c.from);
          } else if (seen.depth === depth && seen.via === id) {
            if (!seen.lines.includes(c.line)) seen.lines.push(c.line);
          } else if (seen.depth === depth && sure && !seen.sure) {
            Object.assign(seen, { sure, via: id, lines: [c.line] });
          }
        }
      }
      frontier = next;
    }
    info.delete(f.id);
    return { info, truncated: info.size >= MAX - 1 };
  }
  let callerLinksCache = null;
  function callerLinks() { // id -> [{from, line, x}] with the link confidence, which `callers` doesn't keep
    if (!callerLinksCache) {
      callerLinksCache = FUNCS.map(() => []);
      for (const g of FUNCS) for (const c of g.calls) if (c.t) for (const t of c.t) callerLinksCache[t].push({ from: g.id, line: c.l, x: c.x || "h" });
    }
    return callerLinksCache;
  }

  function buildImpact(f, container, showSource) {
    container.textContent = "";
    const { info, truncated } = impactOf(f, prefs.low);
    const byDepth = [];
    for (const [id, it] of info) (byDepth[it.depth] ||= []).push({ id, ...it });
    const files = new Set([...info.keys()].map((id) => FUNCS[id].f));
    const entries = [...info.keys()].filter((id) => !callers[id].length);
    const unsure = [...info.values()].filter((it) => !it.sure).length;

    const wrap = el("div", { class: "impact" });
    if (!info.size) {
      wrap.append(el("div", { class: "empty-note" }, "Nothing in this codebase calls " + f.n + "(), so changing it affects no other function here. "
        + "It may be an entry point, a callback, or called dynamically."));
      container.append(wrap);
      return;
    }
    const num = (n, word) => el("b", null, n.toLocaleString() + " " + word + (n === 1 ? "" : "s"));
    wrap.append(el("div", { class: "impact-summary" },
      "Changing ", el("span", { class: "mono" }, f.n + "()"), " can affect ", num(info.size, "function"), " in ", num(files.size, "file"),
      ", up to ", num(byDepth.length - 1, "call"), " away", entries.length ? ", reaching " : "",
      entries.length ? num(entries.length, "entry point") : null, ".",
      unsure ? el("div", { class: "muted" }, unsure.toLocaleString() + " of them only through best-guess or ambiguous links (marked guess).") : null,
      truncated ? el("div", { class: "muted" }, "Stopped after " + info.size.toLocaleString() + " functions.") : null));

    let selected = null;
    for (let d = 1; d < byDepth.length; d++) {
      const items = byDepth[d].sort((a, b) => (b.sure - a.sure) || fileOf(FUNCS[a.id]).localeCompare(fileOf(FUNCS[b.id])) || FUNCS[a.id].l - FUNCS[b.id].l);
      const ul = el("ul", { class: "tree impact-list" });
      const SHOW = 200;
      for (const it of items.slice(0, SHOW)) {
        const g = FUNCS[it.id], via = FUNCS[it.via];
        const row = el("div", { class: "row" + (it.sure ? "" : " low"), "data-hc": g.id, "data-hc-hint": "Click to see where it calls " + via.n + "() · double-click to open" },
          el("span", { class: "icon " + g.k }, KIND_LETTER[g.k]), fnLabel(g),
          d > 1 ? el("span", { class: "via" }, "→ " + via.n + "()") : null,
          it.sure ? null : el("span", { class: "badge low" }, "guess"),
          callers[g.id].length ? null : el("span", { class: "badge entry", title: "Nothing calls this: an entry point" }, "entry"),
          el("span", { class: "meta" }, fileOf(g) + ":" + g.l));
        row.addEventListener("click", () => {
          if (selected) selected.classList.remove("selected");
          selected = row; row.classList.add("selected");
          showSource(g.id, null, it.lines);
        });
        row.addEventListener("dblclick", () => go(g.id));
        ul.append(el("li", null, row));
      }
      if (items.length > SHOW) ul.append(el("li", { class: "muted more" }, "… and " + (items.length - SHOW).toLocaleString() + " more"));
      const head = el("div", { class: "impact-head" }, el("span", { class: "caret open" }, "▸"),
        d === 1 ? "Called directly by" : d + " calls away", el("span", { class: "badge" }, items.length.toLocaleString()));
      head.addEventListener("click", () => { ul.hidden = !ul.hidden; head.firstChild.classList.toggle("open", !ul.hidden); });
      if (d > 3) { ul.hidden = true; head.firstChild.classList.remove("open"); }
      wrap.append(el("section", { class: "impact-group" }, head, ul));
    }
    container.append(wrap);
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
        item.row.removeAttribute("title");
        item.row.dataset.hc = f.id;
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
        el("span", null, "called from " + callers[id].length + " place" + (callers[id].length === 1 ? "" : "s")),
        el("a", { href: "#/path/" + id + "/", title: "Find the chains of calls from this function to another one" }, "find path to…"))));

    const body = el("div", { class: "fn-body" });
    const treePanel = el("section", { class: "panel tree-panel" });
    const codePanel = el("section", { class: "panel code-panel" });
    const treeBox = el("div", { class: "panel-scroll" });
    const codeBox = el("div", { class: "panel-scroll" });
    const tabOut = el("button", { class: "tab" + (dir === "out" ? " active" : ""), onclick: () => go(id, "out") }, "Calls ▸");
    const tabIn = el("button", { class: "tab" + (dir === "in" ? " active" : ""), onclick: () => go(id, "in") }, "◂ Callers");
    const tabImpact = el("button", { class: "tab" + (dir === "impact" ? " active" : ""), onclick: () => go(id, "impact"),
      title: "Everything that can end up calling this function, grouped by distance" }, "Impact");
    const renderTree = () => {
      showSource(f.id);
      if (dir === "impact") {
        treeBox.className = "panel-scroll";
        treePanel.classList.add("is-graph"); // same width as the graph
        buildImpact(f, treeBox, showSource);
        return;
      }
      treeBox.className = prefs.view === "list" ? "panel-scroll" : "graph-box";
      treePanel.classList.toggle("is-graph", prefs.view !== "list");
      if (prefs.view === "list") buildCallTree(f, dir, treeBox, codeBox);
      else buildCallGraph(f, dir, treeBox, codeBox, showSource);
    };
    const opt = (key, label, title) => el("label", { title },
      el("input", { type: "checkbox", checked: prefs[key], onchange: (e) => { prefs[key] = e.target.checked; savePrefs(); renderTree(); } }), label);
    const viewBtn = (v, label, title) => el("button", { class: "tab" + ((prefs.view || "graph") === v ? " active" : ""), title,
      onclick: (e) => {
        prefs.view = v; savePrefs();
        for (const b of e.target.parentNode.children) b.classList.toggle("active", b === e.target);
        renderTree();
      } }, label);
    treePanel.append(el("div", { class: "pane-title" }, el("div", { class: "tabs" }, tabOut, tabIn, tabImpact),
      el("div", { class: "opts" },
        dir === "impact" ? null : el("div", { class: "tabs seg" }, viewBtn("graph", "Graph", "Functions as nodes with lines to what they call"),
          viewBtn("list", "List", "Indented list")),
        dir === "out" ? opt("ext", "external", "Show calls to functions that are not defined in this codebase") : null,
        dir !== "in" ? opt("low", "guesses", "Show links resolved by name only (lower confidence)") : null)), treeBox);
    const split = el("div", { class: "splitter" });
    const srcTitle = el("span", { class: "src-title" });
    codePanel.append(el("div", { class: "pane-title" }, srcTitle,
      el("span", { class: "opts muted" }, "click a call to follow it")), codeBox);
    // fid = function to show; or null with a note (external / ambiguous graph nodes)
    function showSource(fid, note, lines) {
      srcTitle.textContent = "";
      if (fid == null) {
        delete codeBox.dataset.fn;
        codeBox.textContent = "";
        codeBox.append(el("div", { class: "empty-note" }, note));
        srcTitle.append("Source");
        return;
      }
      const sf = FUNCS[fid];
      codeBox.dataset.fn = fid;
      renderCode(sf, codeBox, lines);
      codeBox.scrollTop = 0;
      if (lines && lines.length) highlightLines(codeBox, lines, true);
      if (fid === f.id) { srcTitle.append("Source"); return; }
      srcTitle.append("Source · ", el("span", { class: "src-name" }, sf.n + "()"), " ",
        el("span", { class: "muted src-file" }, fileOf(sf) + ":" + sf.l), " ",
        el("button", { class: "link-btn src-open", title: "Make this the graph's main function", onclick: () => go(fid, dir) }, "open ↗"));
    }
    body.append(treePanel, split, codePanel);
    main.append(body);
    if (prefs.treeW) treePanel.style.width = prefs.treeW + "px";
    dragResize(split, (x) => {
      const w = Math.max(220, x - treePanel.getBoundingClientRect().left);
      treePanel.style.width = w + "px"; prefs.treeW = w; savePrefs();
    });
    renderTree();
    revealInExplorer(f);
  }

  function cycleSection() {
    const cycles = callCycles();
    if (!cycles.length) return null;
    const ul = el("ul", { class: "tree cycle-list" });
    for (const comp of cycles.slice(0, 20)) {
      const fns = comp.map((id) => FUNCS[id]).sort((a, b) => fileOf(a).localeCompare(fileOf(b)) || a.l - b.l);
      const row = el("div", { class: "row cycle-row" }, el("span", { class: "badge" }, comp.length + " functions"));
      fns.slice(0, 6).forEach((f, i) => {
        if (i) row.append(el("span", { class: "muted" }, "⇄"));
        row.append(el("a", { href: "#/f/" + f.id, class: "mono", "data-hc": f.id }, f.n + "()"));
      });
      if (fns.length > 6) row.append(el("span", { class: "muted" }, "… +" + (fns.length - 6)));
      ul.append(el("li", null, row));
    }
    return el("section", null, el("h2", null, "Call cycles (functions that can call each other in a loop)"),
      el("p", { class: "help small" }, cycles.length + " group" + (cycles.length === 1 ? "" : "s") + " of mutually recursive functions"
        + (cycles.length > 20 ? ", largest 20 shown" : "") + ". Some may come from best-guess links."), ul);
  }
  function neverCalledSection() {
    const dead = FUNCS.filter((f) => f.k !== "toplevel" && f.k !== "constructor" && !callers[f.id].length && !f.calls.some((c) => c.t));
    if (!dead.length) return null;
    const byF = new Map();
    for (const f of dead) { if (!byF.has(f.f)) byF.set(f.f, []); byF.get(f.f).push(f); }
    const files = [...byF.entries()].sort((a, b) => b[1].length - a[1].length);
    const ul = el("ul", { class: "tree" });
    for (const [fi, fns] of files.slice(0, 40)) {
      const row = el("div", { class: "row", onclick: (e) => fileFunctionsList(e.currentTarget, fns) },
        el("span", { class: "icon file" }, "▫"), el("span", { class: "label" }, FILES[fi].p), el("span", { class: "badge" }, String(fns.length)));
      ul.append(el("li", null, row));
    }
    return el("details", { class: "never-called" },
      el("summary", null, el("h2", null, "Isolated functions (" + dead.length.toLocaleString() + ")")),
      el("p", { class: "help small" }, "Not called from anywhere in this codebase and calling nothing in it: dead code, or reached only "
        + "from outside (callbacks, exported API, tests, virtual or dynamic dispatch). Grouped by file."), ul);
  }
  function fileFunctionsList(anchor, fns) {
    popup.textContent = "";
    const ul = el("ul", { class: "tree popup-scroll" });
    for (const f of fns.sort((a, b) => a.l - b.l)) ul.append(fnRow(f, () => { hidePopup(); go(f.id); }, false));
    popup.append(ul);
    popup.hidden = false;
    const r = anchor.getBoundingClientRect(), pr = popup.getBoundingClientRect();
    popup.style.left = Math.max(8, Math.min(r.left + 40, innerWidth - pr.width - 8)) + "px";
    popup.style.top = (r.bottom + pr.height + 8 > innerHeight ? Math.max(8, r.top - pr.height - 4) : r.bottom + 4) + "px";
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
        ". The graph shows the function as a node linked to every function it calls (switch to ", el("b", null, "Callers"),
        " for the reverse). Click a node to see its code, expand it with +, double-click it to open that function, drag nodes to move them, drag the background to pan, scroll to zoom, and use ", el("kbd", null, "Alt"), "+",
        el("kbd", null, "←"), " to go back. Calls in the source are links too. Links are resolved by name, so ",
        el("span", { style: "color:var(--warn)" }, "amber"), " marks a name with several candidates and dashed underlines mark best guesses."),
      el("h2", null, "Codebase map"),
      el("p", { class: "help small" }, "Each box is a file, sized by lines of code. Click a folder to zoom in, a file to list its functions."),
      codebaseMap(),
      entries.length ? el("h2", null, "Entry points (not called from anywhere, ranked by how much they reach)") : null,
      entries.length ? list(entries, (n) => n + " reachable") : null,
      popular.length ? el("h2", null, "Most called") : null,
      popular.length ? list(popular, (n) => n + " callers") : null,
      cycleSection(), neverCalledSection()));
  }


  // ---------------------------------------------------------------- codebase map (treemap)
  // Squarified treemap of directories → files, area = lines of code. Directories are drawn as frames
  // with a title bar; clicking one zooms into it, clicking a file lists its functions.
  const LANG_COLORS = { c: "#339af0", cpp: "#845ef7", python: "#40c057", javascript: "#f59f00", typescript: "#1098ad", tsx: "#0ca678",
                        go: "#3bc9db", rust: "#e8590c", java: "#d6336c", ruby: "#e03131", php: "#5c7cfa" };
  function squarify(items, x, y, w, h) { // items: [{v}] sorted desc; returns [{item, x, y, w, h}]
    const out = [];
    let rest = items.slice(), total = rest.reduce((a, b) => a + b.v, 0);
    while (rest.length) {
      const short = Math.min(w, h), scale = (w * h) / total;
      let row = [], rowSum = 0, best = Infinity;
      for (const it of rest) {
        const s2 = rowSum + it.v;
        const rmax = Math.max(it.v, ...row.map((r) => r.v)) * scale, rmin = Math.min(it.v, ...row.map((r) => r.v)) * scale;
        const side = s2 * scale / short;
        const worst = Math.max((side * side) / rmin, rmax / (side * side));
        if (row.length && worst > best) break;
        best = worst; row.push(it); rowSum = s2;
      }
      const side = rowSum * scale / short;
      let off = 0;
      for (const it of row) {
        const len = it.v * scale / side;
        out.push(w >= h ? { item: it, x, y: y + off, w: side, h: len } : { item: it, x: x + off, y, w: len, h: side });
        off += len;
      }
      if (w >= h) { x += side; w -= side; } else { y += side; h -= side; }
      rest = rest.slice(row.length); total -= rowSum;
    }
    return out;
  }
  function mapTree() { // directory tree with line totals
    const root = { name: DATA.name, path: "", dirs: new Map(), files: [], v: 0 };
    FILES.forEach((file, i) => {
      let d = root;
      const parts = file.p.split("/");
      for (const part of parts.slice(0, -1)) {
        if (!d.dirs.has(part)) d.dirs.set(part, { name: part, path: (d.path ? d.path + "/" : "") + part, dirs: new Map(), files: [], v: 0, parent: d });
        d = d.dirs.get(part);
      }
      d.files.push({ file: i, v: Math.max(1, file.lines), name: parts[parts.length - 1] });
    });
    const sum = (d) => (d.v = [...d.dirs.values()].reduce((a, c) => a + sum(c), 0) + d.files.reduce((a, f) => a + f.v, 0));
    sum(root);
    return root;
  }
  function codebaseMap() {
    const root = mapTree();
    const fileCallers = FILES.map(() => 0);
    for (const f of FUNCS) fileCallers[f.f] += new Set(callers[f.id].filter((c) => FUNCS[c.from].f !== f.f).map((c) => c.from)).size;
    const maxIn = Math.max(1, ...fileCallers);
    let mode = prefs.mapColor || "lang", current = root;
    const box = el("div", { class: "cmap" });
    const crumbs = el("div", { class: "cmap-crumbs" });
    const legend = el("div", { class: "cmap-legend" });
    const modeBtn = (m, label, title) => el("button", { class: "tab" + (mode === m ? " active" : ""), title, onclick: (e) => {
      mode = prefs.mapColor = m; savePrefs();
      for (const b of e.target.parentNode.children) b.classList.toggle("active", b === e.target);
      draw();
    } }, label);
    const head = el("div", { class: "cmap-head" }, crumbs, el("div", { class: "tabs seg" },
      modeBtn("lang", "Language", "Colour files by language"),
      modeBtn("in", "Used by", "Colour files by how many functions in other files call into them")));
    const color = (fi) => {
      if (mode === "lang") return LANG_COLORS[FILES[fi].lang] || "#868e96";
      const t = Math.sqrt(fileCallers[fi] / maxIn);
      return `color-mix(in srgb, var(--accent) ${Math.round(12 + t * 88)}%, var(--bg-3))`;
    };
    function draw() {
      box.textContent = ""; crumbs.textContent = ""; legend.textContent = "";
      const chain = [];
      for (let d = current; d; d = d.parent) chain.unshift(d);
      chain.forEach((d, i) => {
        if (i) crumbs.append(el("span", { class: "muted" }, " / "));
        crumbs.append(i === chain.length - 1 ? el("b", null, d.name) : el("a", { href: "#", onclick: (e) => { e.preventDefault(); current = d; draw(); } }, d.name));
      });
      const W = box.clientWidth || 800, H = box.clientHeight || 420;
      layoutDir(current, 0, 0, W, H, 0);
      if (mode === "lang") {
        const langs = [...new Set(FILES.map((f) => f.lang))];
        for (const l of langs) legend.append(el("span", null, el("i", { style: "background:" + (LANG_COLORS[l] || "#868e96") }), l));
      } else legend.append(el("span", { class: "muted" }, "darker = called from more functions in other files (max " + maxIn + ")"));
    }
    const TITLE = 17, PAD = 2;
    function layoutDir(d, x, y, w, h, depth) {
      const kids = [...[...d.dirs.values()].map((c) => ({ dir: c, v: c.v })), ...d.files.map((f) => ({ file: f, v: f.v }))]
        .filter((k) => k.v > 0).sort((a, b) => b.v - a.v);
      for (const r of squarify(kids, x, y, w, h)) {
        if (r.w < 2 || r.h < 2) continue;
        if (r.item.dir) {
          const dd = r.item.dir;
          const frame = el("div", { class: "cmap-dir", style: `left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px`,
            title: dd.path + "/ · " + dd.v.toLocaleString() + " lines" });
          if (r.h > TITLE + 8 && r.w > 30) frame.append(el("div", { class: "cmap-dtitle" }, dd.name + "/"));
          frame.addEventListener("click", (e) => { e.stopPropagation(); current = dd; draw(); });
          box.append(frame);
          const top = r.h > TITLE + 8 && r.w > 30 ? TITLE : PAD;
          if (r.w > 2 * PAD + 4 && r.h > top + PAD + 4) layoutDir(dd, r.x + PAD, r.y + top, r.w - 2 * PAD, r.h - top - PAD, depth + 1);
        } else {
          const fi = r.item.file.file, file = FILES[fi];
          const n = byFile[fi].filter((f) => f.k !== "toplevel").length;
          const pale = mode === "in" && fileCallers[fi] / maxIn < 0.2;
          const cell = el("div", { class: "cmap-file" + (pale ? " pale" : ""), style: `left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px;background:${color(fi)}`,
            title: file.p + "\n" + file.lines.toLocaleString() + " lines · " + n + " function" + (n === 1 ? "" : "s")
              + (fileCallers[fi] ? " · called from " + fileCallers[fi] + " function" + (fileCallers[fi] === 1 ? "" : "s") + " in other files" : "") });
          if (r.w > 46 && r.h > 16) cell.append(el("span", null, r.item.file.name));
          cell.addEventListener("click", (e) => { e.stopPropagation(); fileFunctions(cell, fi); });
          box.append(cell);
        }
      }
    }
    const wrap = el("div", { class: "cmap-wrap" }, head, box, legend);
    new ResizeObserver(() => draw()).observe(box);
    return wrap;
  }
  function fileFunctions(anchor, fi) {
    const fns = byFile[fi].filter((f) => f.k !== "toplevel").sort((a, b) => a.l - b.l);
    popup.textContent = "";
    popup.append(el("div", { class: "popup-title" }, FILES[fi].p + " · " + fns.length + " function" + (fns.length === 1 ? "" : "s")));
    const ul = el("ul", { class: "tree popup-scroll" });
    for (const f of fns) ul.append(fnRow(f, () => { hidePopup(); go(f.id); }, false));
    if (!fns.length) ul.append(el("li", { class: "empty-note" }, "No functions found in this file."));
    popup.append(ul);
    popup.hidden = false;
    const r = anchor.getBoundingClientRect(), pr = popup.getBoundingClientRect();
    popup.style.left = Math.max(8, Math.min(r.left + 10, innerWidth - pr.width - 8)) + "px";
    popup.style.top = Math.max(8, Math.min(r.top + 10, innerHeight - pr.height - 8)) + "px";
  }

  // ---------------------------------------------------------------- cycles and never-called functions
  function callCycles() { // strongly connected components of size > 1 (Tarjan, iterative), ignoring ambiguous links
    const idx = new Int32Array(FUNCS.length).fill(-1), low = new Int32Array(FUNCS.length), onStack = new Uint8Array(FUNCS.length);
    const stack = [], out = [];
    let counter = 0;
    const succ = (id) => [...new Set(FUNCS[id].calls.filter((c) => c.t && c.x !== "a").map((c) => c.t[0]))];
    for (let s0 = 0; s0 < FUNCS.length; s0++) {
      if (idx[s0] >= 0) continue;
      const work = [[s0, succ(s0), 0]];
      idx[s0] = low[s0] = counter++; stack.push(s0); onStack[s0] = 1;
      while (work.length) {
        const top = work[work.length - 1];
        const [v, next] = top;
        if (top[2] < next.length) {
          const w = next[top[2]++];
          if (idx[w] < 0) { idx[w] = low[w] = counter++; stack.push(w); onStack[w] = 1; work.push([w, succ(w), 0]); }
          else if (onStack[w]) low[v] = Math.min(low[v], idx[w]);
        } else {
          work.pop();
          if (work.length) { const u = work[work.length - 1][0]; low[u] = Math.min(low[u], low[v]); }
          if (low[v] === idx[v]) {
            const comp = [];
            let w;
            do { w = stack.pop(); onStack[w] = 0; comp.push(w); } while (w !== v);
            if (comp.length > 1) out.push(comp);
          }
        }
      }
    }
    return out.sort((a, b) => b.length - a.length);
  }


  // ---------------------------------------------------------------- path finder
  // Shortest call chains from one function to another (BFS over callees), up to MAX_PATHS of them.
  const MAX_PATHS = 8;
  function shortestPaths(fromId, toId, withGuesses) {
    const dist = new Map([[fromId, 0]]), preds = new Map();
    let frontier = [fromId];
    while (frontier.length && !dist.has(toId)) {
      const next = [];
      for (const id of frontier) {
        const d = dist.get(id);
        for (const c of FUNCS[id].calls) {
          if (!c.t || (c.x !== "h" && !withGuesses)) continue;
          for (const t of c.t) {
            if (!dist.has(t)) { dist.set(t, d + 1); preds.set(t, []); next.push(t); }
            if (dist.get(t) === d + 1) {
              const list = preds.get(t);
              const e = list.find((p) => p.id === id);
              if (e) { if (!e.lines.includes(c.l)) e.lines.push(c.l); if (c.x === "h") e.sure = true; }
              else list.push({ id, lines: [c.l], sure: c.x === "h" });
            }
          }
        }
      }
      frontier = next;
    }
    if (!dist.has(toId) || fromId === toId) return [];
    // walk back from the target; prefer confident steps so the first paths shown are the most certain
    const paths = [];
    const walk = (id, tail) => {
      if (paths.length >= MAX_PATHS) return;
      if (id === fromId) { paths.push(tail); return; }
      for (const p of preds.get(id).slice().sort((a, b) => b.sure - a.sure)) walk(p.id, [{ id: p.id, to: id, lines: p.lines, sure: p.sure }, ...tail]);
    };
    walk(toId, []);
    return paths;
  }

  function fnPicker(placeholder, value, onPick) {
    const input = el("input", { type: "search", placeholder, autocomplete: "off", spellcheck: "false", value: value != null ? qname(FUNCS[value]) : "" });
    const list = el("ul", { class: "search-results" });
    list.hidden = true;
    let items = [], act = 0;
    const render = () => {
      list.textContent = "";
      items = input.value.trim() ? findFunctions(input.value, 30) : [];
      act = 0;
      items.forEach((f, i) => list.append(el("li", { class: i ? "" : "active", onmousedown: (e) => { e.preventDefault(); pick(i); } },
        el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]), fnLabel(f), el("span", { class: "path" }, fileOf(f) + ":" + f.l))));
      if (input.value.trim() && !items.length) list.append(el("li", { class: "muted" }, "No functions match"));
      list.hidden = !input.value.trim();
    };
    const pick = (i) => { const f = items[i]; if (!f) return; list.hidden = true; input.value = qname(f); input.blur(); onPick(f.id); };
    input.addEventListener("input", render);
    input.addEventListener("focus", () => { input.select(); });
    input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 100));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!items.length) return;
        act = (act + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        list.querySelectorAll("li").forEach((li, i) => li.classList.toggle("active", i === act));
      } else if (e.key === "Enter") pick(act);
      else if (e.key === "Escape") { list.hidden = true; input.blur(); }
    });
    return { node: el("div", { class: "search picker" }, input, list), input };
  }

  function showPath(fromId, toId) {
    const from = FUNCS[fromId], to = FUNCS[toId];
    document.title = "Path" + (from ? " from " + from.n : "") + (to ? " to " + to.n : "") + " · " + DATA.name;
    main.textContent = "";
    for (const r of explorer.querySelectorAll(".row.selected")) r.classList.remove("selected");
    const setRoute = (a, b) => { location.hash = "#/path/" + (a ?? "") + "/" + (b ?? ""); };
    const pickFrom = fnPicker("From function…", from ? fromId : null, (id) => setRoute(id, to ? toId : null));
    const pickTo = fnPicker("To function…", to ? toId : null, (id) => setRoute(from ? fromId : null, id));
    const swap = el("button", { title: "Swap", onclick: () => setRoute(to ? toId : null, from ? fromId : null) }, "⇄");
    const guesses = el("label", { title: "Also follow links resolved by name only" },
      el("input", { type: "checkbox", checked: prefs.low, onchange: (e) => { prefs.low = e.target.checked; savePrefs(); showPath(fromId, toId); } }), "guesses");
    main.append(el("div", { class: "fn-header path-header" },
      el("div", { class: "fn-title" }, "How does one function reach another?"),
      el("div", { class: "path-pickers" }, pickFrom.node, swap, pickTo.node, guesses)));

    const body = el("div", { class: "fn-body" });
    const listPanel = el("section", { class: "panel tree-panel is-graph" });
    const listBox = el("div", { class: "panel-scroll" });
    const codePanel = el("section", { class: "panel code-panel" });
    const codeBox = el("div", { class: "panel-scroll" });
    const srcTitle = el("span", { class: "src-title" }, "Source");
    listPanel.append(el("div", { class: "pane-title" }, el("span", null, "Call chains")), listBox);
    codePanel.append(el("div", { class: "pane-title" }, srcTitle), codeBox);
    body.append(listPanel, el("div", { class: "splitter" }), codePanel);
    main.append(body);
    const showCode = (id, lines) => {
      const f = FUNCS[id];
      srcTitle.textContent = "";
      srcTitle.append("Source · ", el("span", { class: "src-name" }, f.n + "()"), " ", el("span", { class: "muted src-file" }, fileOf(f) + ":" + f.l), " ",
        el("button", { class: "link-btn src-open", onclick: () => go(id) }, "open ↗"));
      renderCode(f, codeBox, lines);
      codeBox.scrollTop = 0;
      if (lines && lines.length) highlightLines(codeBox, lines, true);
    };
    const note = (text) => listBox.append(el("div", { class: "empty-note" }, text));

    if (!from || !to) {
      note("Pick two functions to see the chains of calls that lead from the first to the second.");
      if (from) showCode(fromId);
      requestAnimationFrame(() => (from ? pickTo : pickFrom).input.focus());
      return;
    }
    let paths = shortestPaths(fromId, toId, prefs.low), reversed = false;
    if (!paths.length) { paths = shortestPaths(toId, fromId, prefs.low); reversed = paths.length > 0; }
    if (!paths.length) {
      note("No chain of calls in this codebase leads from " + from.n + "() to " + to.n + "() or back"
        + (prefs.low ? "." : ". Tick “guesses” to also follow links matched by name only."));
      showCode(fromId);
      return;
    }
    const steps = paths[0].length;
    listBox.append(el("div", { class: "path-summary" },
      reversed ? el("div", { class: "muted" }, from.n + "() doesn’t lead to " + to.n + "(), but the reverse does:") : null,
      el("b", null, (reversed ? to : from).n + "()"), " reaches ", el("b", null, (reversed ? from : to).n + "()"), " in ",
      el("b", null, steps + " call" + (steps === 1 ? "" : "s")), paths.length > 1 ? " along " + (paths.length >= MAX_PATHS ? "at least " : "") + paths.length + " different shortest chains." : "."));
    let selected = null;
    const select = (row, id, lines) => { if (selected) selected.classList.remove("selected"); selected = row; row.classList.add("selected"); showCode(id, lines); };
    paths.forEach((path, pi) => {
      const chain = el("ol", { class: "chain" });
      const stepRow = (id, call) => {
        const f = FUNCS[id];
        const row = el("div", { class: "row chain-step" + (call && !call.sure ? " low" : ""), "data-hc": id },
          el("span", { class: "icon " + f.k }, KIND_LETTER[f.k]), fnLabel(f),
          call && !call.sure ? el("span", { class: "badge low" }, "guess") : null,
          call ? el("span", { class: "meta" }, "calls " + FUNCS[call.to].n + "() on line " + call.lines.join(", ")) : el("span", { class: "meta" }, fileOf(f) + ":" + f.l));
        row.addEventListener("click", () => select(row, id, call ? call.lines : null));
        row.addEventListener("dblclick", () => go(id));
        return el("li", null, row);
      };
      for (const step of path) chain.append(stepRow(step.id, step));
      chain.append(stepRow(path[path.length - 1].to, null));
      listBox.append(el("section", { class: "chain-group" }, el("div", { class: "path-head" }, "Chain " + (pi + 1)), chain));
      if (pi === 0) select(chain.querySelector(".row"), path[0].id, path[0].lines);
    });
  }

  // ---------------------------------------------------------------- routing
  function go(id, dir) {
    const h = "#/f/" + id + (dir === "in" ? "/in" : dir === "impact" ? "/impact" : "");
    if (location.hash !== h) location.hash = h; else route();
  }
  function route() {
    hidePopup(); hideCard();
    const m = /^#\/f\/(\d+)(?:\/(in|impact))?/.exec(location.hash);
    const p = /^#\/path\/(\d*)\/(\d*)/.exec(location.hash);
    if (m) showFunction(+m[1], m[2] || "out");
    else if (p) showPath(p[1] === "" ? null : +p[1], p[2] === "" ? null : +p[2]);
    else showOverview();
    main.scrollTop = 0;
  }
  window.addEventListener("hashchange", route);

  // ---------------------------------------------------------------- search
  let searchIndex = null;
  function findFunctions(query, limit) {
    searchIndex ||= FUNCS.filter((f) => f.k !== "toplevel").map((f) => ({ f, n: f.n.toLowerCase(), q: qname(f).toLowerCase(), p: fileOf(f).toLowerCase() }));
    const q = query.trim().toLowerCase();
    const scored = [];
    for (const it of searchIndex) {
      let s = -1;
      if (it.n === q) s = 100; else if (it.n.startsWith(q)) s = 80; else if (it.q === q || it.q.endsWith(q)) s = 75;
      else if (it.n.includes(q)) s = 60; else if (it.q.includes(q)) s = 40; else if (it.p.includes(q)) s = 20;
      if (s >= 0) scored.push([s - it.n.length * 0.01, it]);
    }
    scored.sort((a, b) => b[0] - a[0]);
    return scored.slice(0, limit).map((x) => x[1].f);
  }
  const search = $("#search"), results = $("#search-results");
  let active = 0, shown = [];
  function runSearch() {
    const q = search.value.trim();
    results.textContent = "";
    if (!q) { results.hidden = true; return; }
    shown = findFunctions(q, 40);
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
  $("#btn-path").addEventListener("click", () => {
    const m = /^#\/f\/(\d+)/.exec(location.hash);
    location.hash = "#/path/" + (m ? m[1] : "") + "/";
  });
  $("#project-name").textContent = DATA.name;
  $("#stats").innerHTML = "";
  $("#stats").append(el("span", { class: "stats-text" }, DATA.stats.functions.toLocaleString() + " functions · " + DATA.stats.files.toLocaleString() + " files"));

  route();
})();
