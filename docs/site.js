/* Hand-written. No framework, no build step, no dependencies.
   Three interactive devices, each tied to a specific chapter's argument. */

(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function el(name, attrs) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) if (attrs.hasOwnProperty(k)) n.setAttribute(k, attrs[k]);
    return n;
  }

  /* ============================================================
     1. TOKENIZER — type a word, see how BPE would chew it up.
     A real greedy BPE over a tiny merge table. The point is that
     the splits are arbitrary and corpus-dependent, which is the
     chapter's whole argument.
     ============================================================ */
  var MERGES = [
    ["t","h"], ["h","e"], ["e"," "], [" ","t"], ["th","e"], ["the"," "],
    ["i","n"], ["in","g"], ["e","r"], ["s","t"], ["a","n"], ["o","n"],
    ["e","n"], ["t","i"], ["o","r"], ["l","y"], ["e","d"], ["i","on"],
    ["at","ion"], ["the","re"], ["th","ere"], ["i","s"], ["is"," "],
    ["a","l"], ["al","l"], ["t","o"], ["to"," "], ["c","o"], ["o","m"],
    ["m","p"], ["co","m"], ["com","p"], ["comp","ress"], ["i","on"],
    ["w","o"], ["o","r"], ["wor","d"], ["word","s"], ["s"," "],
    ["f","o"], ["fo","r"], ["for"," "], ["n","o"], ["no","t"],
    ["u","n"], ["un","u"], ["unu","s"], ["usu","al"]
  ];
  var KNOWN = {};
  MERGES.forEach(function (m) { KNOWN[m[0] + m[1]] = true; });

  function bpeStep(tokens) {
    // find the leftmost adjacent pair that exists in the merge table
    for (var i = 0; i < tokens.length - 1; i++) {
      var pair = tokens[i] + tokens[i + 1];
      if (KNOWN[pair]) {
        return {
          found: true, index: i, merged: pair,
          next: tokens.slice(0, i).concat([pair], tokens.slice(i + 2))
        };
      }
    }
    return { found: false };
  }

  function tokenize(word) {
    var toks = word.toLowerCase().split("");
    var steps = [toks.slice()];
    var guard = 0;
    while (guard++ < 40) {
      var r = bpeStep(toks);
      if (!r.found) break;
      toks = r.next;
      steps.push(toks.slice());
    }
    return steps;
  }

  function mountTokenizer() {
    var input = document.getElementById("bpe-input");
    var host = document.getElementById("bpe-host");
    var out = document.getElementById("bpe-out");
    if (!input || !host) return;

    function draw() {
      var raw = input.value || "unusual";
      var steps = tokenize(raw);
      host.innerHTML = "";

      var W = 640, rowH = 34, padT = 8;
      var H = padT + steps.length * rowH + 20;
      var svg = el("svg", {
        viewBox: "0 0 " + W + " " + H, width: "100%",
        role: "img", "aria-label": "Byte-pair merge steps for the typed word"
      });
      svg.classList.add("bpe-svg");

      steps.forEach(function (toks, row) {
        var y = padT + row * rowH;
        var x = 8;
        toks.forEach(function (t) {
          var w = Math.max(26, t.length * 11 + 14);
          svg.appendChild(el("rect", {
            x: x, y: y, width: w, height: 22, rx: 2,
            fill: row === steps.length - 1 ? "var(--accent)" : "none",
            "fill-opacity": row === steps.length - 1 ? 0.14 : 0,
            stroke: "var(--rule)", "stroke-width": 1
          }));
          var label = el("text", {
            x: x + w / 2, y: y + 15, "text-anchor": "middle",
            "font-size": 11, fill: "var(--ink)",
            "font-family": "DejaVu Sans Mono, monospace"
          });
          label.textContent = t === " " ? "\u2423" : t;
          svg.appendChild(label);
          x += w + 4;
        });
        var n = el("text", {
          x: W - 4, y: y + 15, "text-anchor": "end",
          "font-size": 9, fill: "var(--ink-soft)", opacity: 0.7
        });
        n.textContent = toks.length + " tokens";
        svg.appendChild(n);
      });

      host.appendChild(svg);
      var final = steps[steps.length - 1];
      out.innerHTML =
        "<strong>" + final.length + "</strong> tokens for " +
        "<strong>" + raw.length + "</strong> characters &middot; " +
        (raw.length / final.length).toFixed(2) + " chars per token";
    }

    input.addEventListener("input", draw);
    draw();
  }

  /* ============================================================
     2. ATTENTION — one query token scoring against its context.
     Shows the raw dot products, then the softmax that turns them
     into shares. Dragging the temperature shows saturation.
     ============================================================ */
  function mountAttention() {
    var host = document.getElementById("attn-host");
    var slider = document.getElementById("attn-slider");
    var out = document.getElementById("attn-out");
    if (!host || !slider) return;

    var WORDS = ["The", "cat", "sat", "on", "the", "mat", "because", "it", "was", "tired"];
    // pretend pre-softmax scores: the query "it" is looking for an antecedent
    var SCORES = [0.4, 2.9, 0.8, 0.2, 0.3, 1.1, 1.8, 3.4, 1.2, 0.9];

    function softmax(scores, temp) {
      var t = Math.max(0.05, temp);
      var scaled = scores.map(function (s) { return s / t; });
      var mx = Math.max.apply(null, scaled);
      var ex = scaled.map(function (s) { return Math.exp(s - mx); });
      var sum = ex.reduce(function (a, b) { return a + b; }, 0);
      return ex.map(function (e) { return e / sum; });
    }

    function draw() {
      var temp = parseFloat(slider.value);
      var w = softmax(SCORES, temp);
      host.innerHTML = "";

      var W = 640, barH = 26, gap = 8, padL = 74;
      var H = WORDS.length * (barH + gap) + 16;
      var svg = el("svg", {
        viewBox: "0 0 " + W + " " + H, width: "100%",
        role: "img", "aria-label": "Attention weights over context words"
      });
      svg.classList.add("attn-svg");

      var maxW = W - padL - 60;
      WORDS.forEach(function (word, i) {
        var y = 8 + i * (barH + gap);
        var bw = Math.max(1, w[i] * maxW);
        var lab = el("text", {
          x: padL - 8, y: y + 17, "text-anchor": "end",
          "font-size": 11, fill: "var(--ink)",
          "font-family": "DejaVu Sans Mono, monospace"
        });
        lab.textContent = word;
        svg.appendChild(lab);

        svg.appendChild(el("rect", {
          x: padL, y: y, width: bw, height: barH,
          fill: "var(--accent)", "fill-opacity": i === 7 ? 0.85 : 0.4
        }));

        var pct = el("text", {
          x: padL + bw + 6, y: y + 17, "font-size": 10,
          fill: "var(--ink-soft)",
          "font-family": "DejaVu Sans Mono, monospace"
        });
        pct.textContent = (w[i] * 100).toFixed(1) + "%";
        svg.appendChild(pct);
      });

      host.appendChild(svg);

      // entropy as a focus measure
      var ent = -w.reduce(function (a, p) {
        return a + (p > 0 ? p * Math.log(p) : 0);
      }, 0);
      var top = WORDS[w.indexOf(Math.max.apply(null, w))];
      out.innerHTML =
        "temperature <strong>" + temp.toFixed(2) + "</strong> &middot; " +
        "peak on <strong>" + top + "</strong> at " +
        "<strong>" + (Math.max.apply(null, w) * 100).toFixed(1) + "%</strong> &middot; " +
        "entropy <strong>" + ent.toFixed(2) + "</strong> nats";
    }

    slider.addEventListener("input", draw);
    draw();
  }

  /* ============================================================
     2b. MULTI-HEAD — the same context scored by different heads.
     Hand-built patterns, not real weights. The point is that each
     head answers a different question about the same tokens.
     ============================================================ */
  function mountMultiHead() {
    var host = document.getElementById("mh-host");
    var sel = document.getElementById("mh-select");
    var out = document.getElementById("mh-out");
    if (!host || !sel) return;

    var WORDS = ["The", "cat", "sat", "on", "the", "mat", "because", "it", "was", "tired"];
    var QUERY = 7; // "it"

    // Each head is a set of pre-softmax scores over the ten positions.
    var HEADS = [
      { name: "previous token", scores: [0.2, 0.1, 0.3, 0.2, 0.4, 0.3, 0.5, 0.2, 4.6, 0.3] },
      { name: "subject of the clause", scores: [0.3, 4.4, 0.6, 0.2, 0.3, 0.7, 0.9, 0.4, 1.1, 0.5] },
      { name: "nearest noun", scores: [0.2, 1.8, 0.4, 0.3, 0.5, 3.9, 0.6, 0.4, 1.2, 0.7] },
      { name: "diffuse", scores: [1.1, 1.3, 0.9, 1.0, 1.2, 1.1, 0.8, 1.4, 1.0, 1.3] }
    ];

    function softmax(scores) {
      var mx = Math.max.apply(null, scores);
      var ex = scores.map(function (s) { return Math.exp(s - mx); });
      var sum = ex.reduce(function (a, b) { return a + b; }, 0);
      return ex.map(function (e) { return e / sum; });
    }

    function draw() {
      var h = HEADS[parseInt(sel.value, 10)] || HEADS[0];
      var w = softmax(h.scores);
      host.innerHTML = "";

      var W = 640, barH = 24, gap = 7, padL = 74;
      var H = WORDS.length * (barH + gap) + 12;
      var svg = el("svg", {
        viewBox: "0 0 " + W + " " + H, width: "100%",
        role: "img", "aria-label": "Attention weights for one head over the context"
      });
      svg.classList.add("mh-svg");

      var maxW = W - padL - 60;
      WORDS.forEach(function (word, i) {
        var y = 6 + i * (barH + gap);
        var bw = Math.max(1, w[i] * maxW);
        var lab = el("text", {
          x: padL - 8, y: y + 16, "text-anchor": "end",
          "font-size": 11,
          fill: i === QUERY ? "var(--accent)" : "var(--ink)",
          "font-weight": i === QUERY ? "bold" : "normal",
          "font-family": "DejaVu Sans Mono, monospace"
        });
        lab.textContent = word;
        svg.appendChild(lab);

        svg.appendChild(el("rect", {
          x: padL, y: y, width: bw, height: barH,
          fill: "var(--accent)", "fill-opacity": i === QUERY ? 0.25 : 0.55
        }));

        var pct = el("text", {
          x: padL + bw + 6, y: y + 16, "font-size": 10,
          fill: "var(--ink-soft)",
          "font-family": "DejaVu Sans Mono, monospace"
        });
        pct.textContent = (w[i] * 100).toFixed(1) + "%";
        svg.appendChild(pct);
      });

      host.appendChild(svg);

      var peak = 0;
      for (var i = 1; i < w.length; i++) if (w[i] > w[peak]) peak = i;
      var ent = -w.reduce(function (a, p) {
        return a + (p > 0 ? p * Math.log(p) : 0);
      }, 0);
      out.innerHTML =
        "<strong>" + h.name + "</strong> &middot; peak on <strong>" + WORDS[peak] +
        "</strong> at <strong>" + (w[peak] * 100).toFixed(1) + "%</strong> &middot; entropy " +
        "<strong>" + ent.toFixed(2) + "</strong> nats" +
        (ent > 2.0 ? " &mdash; this head is not resolving anything" : "");
    }

    sel.addEventListener("change", draw);
    draw();
  }

  /* ============================================================
     3. KV CACHE — the size formula, with the levers exposed.
     Two tensors x layers x kv heads x head dim x seq len x bytes.
     ============================================================ */
  function mountCache() {
    var host = document.getElementById("kv-host");
    var sliders = {
      layers: document.getElementById("kv-layers"),
      heads: document.getElementById("kv-heads"),
      dim: document.getElementById("kv-dim"),
      seq: document.getElementById("kv-seq")
    };
    var out = document.getElementById("kv-out");
    if (!host || !sliders.layers) return;

    function draw() {
      var L = +sliders.layers.value;
      var H = +sliders.heads.value;
      var D = +sliders.dim.value;
      var S = +sliders.seq.value;
      var bytes = 2; // fp16
      // 2 (K and V) * L * H * D * S * bytes
      var total = 2 * L * H * D * S * bytes;
      var gib = total / (1024 * 1024 * 1024);

      var parts = [
        ["2 tensors (K and V)", 2],
        [L + " layers", L],
        [H + " KV heads", H],
        [D + " head dim", D],
        [S.toLocaleString() + " positions", S],
        ["2 bytes (fp16)", bytes]
      ];
      var logTotal = Math.log(total);
      host.innerHTML = "";
      var W = 640, H2 = parts.length * 30 + 20;
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H2, width: "100%",
        role: "img", "aria-label": "Factors contributing to KV cache size" });
      svg.classList.add("kv-svg");
      parts.forEach(function (p, i) {
        var y = 8 + i * 30;
        var share = Math.log(p[1]) / logTotal; // log-scale share
        var bw = Math.max(3, share * (W - 190));
        var lab = el("text", { x: 0, y: y + 16, "font-size": 11,
          fill: "var(--ink)", "font-family": "DejaVu Sans Mono, monospace" });
        lab.textContent = p[0];
        svg.appendChild(lab);
        svg.appendChild(el("rect", { x: 168, y: y + 4, width: bw, height: 16,
          fill: "var(--accent)", "fill-opacity": 0.45 }));
      });
      host.appendChild(svg);

      out.innerHTML =
        "<strong>" + gib.toFixed(2) + " GiB</strong> per sequence &middot; " +
        "2 &times; " + L + " &times; " + H + " &times; " + D + " &times; " +
        S.toLocaleString() + " &times; 2 bytes";
    }

    Object.keys(sliders).forEach(function (k) {
      if (sliders[k]) sliders[k].addEventListener("input", draw);
    });
    draw();
  }

  /* ---- keyboard nav between chapters --------------------------------- */
  function mountKeys() {
    var links = document.querySelectorAll(".chapter-nav a");
    if (!links.length) return;
    document.addEventListener("keydown", function (e) {
      if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey) return;
      if (e.key === "ArrowLeft" && links[0]) location.href = links[0].href;
      if (e.key === "ArrowRight" && links[links.length - 1])
        location.href = links[links.length - 1].href;
    });
  }


  /* ---- reader shell: theme, contents rail, search, chapter progress ---- */
  function mountShell() {
    var root = document.documentElement;

    /* theme: stored choice, else the system preference (set before paint) */
    var themeBtn = document.querySelector("[data-theme-toggle]");
    function themeLabel() {
      if (!themeBtn) return;
      var cur = root.getAttribute("data-theme");
      themeBtn.setAttribute("aria-label", "Switch to " + (cur === "dark" ? "light" : "dark") + " theme");
      themeBtn.setAttribute("aria-pressed", cur === "dark" ? "true" : "false");
    }
    if (themeBtn) {
      themeLabel();
      themeBtn.addEventListener("click", function () {
        var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem("sft-theme", next); } catch (e) {}
        themeLabel();
      });
    }

    /* contents rail on narrow screens */
    var railBtn = document.querySelector("[data-rail-toggle]");
    var rail = document.getElementById("rail");
    if (railBtn && rail) {
      railBtn.addEventListener("click", function () {
        var open = rail.getAttribute("data-open") === "true";
        rail.setAttribute("data-open", open ? "false" : "true");
        railBtn.setAttribute("aria-expanded", open ? "false" : "true");
      });
      /* tapping a chapter closes the overlay, so it does not sit over the page */
      rail.addEventListener("click", function (e) {
        if (e.target.closest("a") && rail.getAttribute("data-open") === "true") {
          rail.setAttribute("data-open", "false");
          railBtn.setAttribute("aria-expanded", "false");
        }
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && rail.getAttribute("data-open") === "true") {
          rail.setAttribute("data-open", "false");
          railBtn.setAttribute("aria-expanded", "false");
          railBtn.focus();
        }
      });
    }

    /* in-chapter rail: highlight the heading you are reading, show progress */
    var crLinks = document.querySelectorAll(".chapter-rail a");
    var bar = document.getElementById("read-bar");
    var pctLabel = document.getElementById("read-pct");
    if (crLinks.length || bar) {
      var targets = [];
      for (var i = 0; i < crLinks.length; i++) {
        var t = document.getElementById(crLinks[i].getAttribute("href").slice(1));
        if (t) targets.push({ el: t, link: crLinks[i] });
      }
      var onScroll = function () {
        var cur = null;
        for (var j = 0; j < targets.length; j++) {
          if (targets[j].el.getBoundingClientRect().top <= 140) cur = targets[j];
        }
        for (var k = 0; k < crLinks.length; k++) crLinks[k].classList.remove("active");
        if (cur) cur.link.classList.add("active");
        if (bar) {
          var doc = document.documentElement;
          var max = doc.scrollHeight - doc.clientHeight;
          var pct = max > 0 ? Math.min(100, Math.round((doc.scrollTop / max) * 100)) : 0;
          bar.style.width = pct + "%";
          if (pctLabel) pctLabel.textContent = "Read " + pct + "%";
        }
      };
      onScroll();
      document.addEventListener("scroll", onScroll, { passive: true });
    }

    /* search: one JSON index, fetched on first open, matched in the browser */
    var dlg = document.getElementById("search");
    if (!dlg) return;
    var input = document.getElementById("search-input");
    var list = document.getElementById("search-results");
    var status = document.getElementById("search-status");
    var index = null, loading = false, results = [], sel = 0;

    function escHtml(s) {
      return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function load() {
      if (index || loading) return Promise.resolve(index);
      loading = true;
      status.textContent = "Loading the index\u2026";
      return fetch(window.__SEARCH_INDEX__).then(function (r) { return r.json(); })
        .then(function (d) {
          index = d;
          index.chaptersById = {};
          d.chapters.forEach(function (c) { index.chaptersById[c.id] = c; });
          loading = false;
          status.textContent = "Type a word, a term, or a number.";
          return index;
        })
        .catch(function () {
          loading = false;
          status.textContent = "The index did not load. Try reloading the page.";
        });
    }

    function snippet(t, terms) {
      var low = t.toLowerCase(), at = -1;
      for (var i = 0; i < terms.length; i++) {
        var p = low.indexOf(terms[i]);
        if (p >= 0 && (at < 0 || p < at)) at = p;
      }
      var start = at > 90 ? at - 90 : 0;
      var out = (start > 0 ? "\u2026" : "") + escHtml(t.slice(start, start + 220)) + (start + 220 < t.length ? "\u2026" : "");
      terms.forEach(function (term) {
        if (term.length < 2) return;
        out = out.replace(new RegExp("(" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi"), "<mark>$1</mark>");
      });
      return out;
    }

    function run() {
      var q = input.value.trim().toLowerCase();
      if (q.length < 2) {
        results = []; list.innerHTML = "";
        status.textContent = "Type at least two characters.";
        return;
      }
      if (!index) { load().then(run); return; }
      var terms = q.split(/\s+/).filter(Boolean);
      var scored = [];
      index.chunks.forEach(function (ch) {
        var low = ch.t.toLowerCase(), head = ch.h.toLowerCase(), title = index.chaptersById[ch.c].title.toLowerCase();
        var score = 0, all = true;
        terms.forEach(function (term) {
          var n = low.split(term).length - 1;
          if (!n && head.indexOf(term) < 0 && title.indexOf(term) < 0) { all = false; return; }
          score += n * 2;
          if (head.indexOf(term) >= 0) score += 6;
          if (title.indexOf(term) >= 0) score += 4;
        });
        if (!all) return;
        scored.push({ score: score, ch: ch });
      });
      scored.sort(function (a, b) { return b.score - a.score; });
      results = scored.slice(0, 40);
      sel = 0;
      if (!results.length) {
        list.innerHTML = '<li class="search-empty">Nothing matched \u201c' + escHtml(q) + '\u201d.</li>';
        status.textContent = "No matches.";
        return;
      }
      status.textContent = results.length + (results.length === 1 ? " passage" : " passages") +
        (scored.length > results.length ? " (best of " + scored.length + ")" : "");
      list.innerHTML = results.map(function (r, i) {
        var c = index.chaptersById[r.ch.c];
        var href = (location.pathname.indexOf("/chapters/") >= 0 ? "" : "chapters/") + c.id + ".html";
        return '<li><a href="' + href + '" data-i="' + i + '"' + (i === 0 ? ' aria-selected="true"' : "") + '>' +
          '<span class="r-ch">' + c.n + ' \u00b7 ' + escHtml(c.part) + '</span>' +
          '<span class="r-t">' + escHtml(r.ch.h) + '</span>' +
          '<span class="r-s">' + snippet(r.ch.t, terms) + '</span></a></li>';
      }).join("");
    }

    var searchOpener = null;
    function openSearch(e) {
      searchOpener = (e && e.currentTarget) || document.activeElement;
      dlg.setAttribute("open", "");
      input.focus();
      load().then(function () { if (input.value.trim().length >= 2) run(); });
    }
    function closeSearch() {
      dlg.removeAttribute("open");
      /* return focus to whatever opened the dialog, not to <body> */
      if (searchOpener && searchOpener.focus) searchOpener.focus();
    }
    /* aria-modal promises a trap; honour it */
    dlg.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      var f = dlg.querySelectorAll("a[href], button, input, [tabindex]:not([tabindex='-1'])");
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });

    document.querySelectorAll("[data-open-search]").forEach(function (b) {
      b.addEventListener("click", openSearch);
    });
    document.querySelectorAll("[data-close-search]").forEach(function (b) {
      b.addEventListener("click", closeSearch);
    });
    dlg.addEventListener("click", function (e) { if (e.target === dlg) closeSearch(); });
    input.addEventListener("input", run);

    input.addEventListener("keydown", function (e) {
      var links = list.querySelectorAll("a");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!links.length) return;
        sel = e.key === "ArrowDown" ? Math.min(links.length - 1, sel + 1) : Math.max(0, sel - 1);
        for (var i = 0; i < links.length; i++) links[i].setAttribute("aria-selected", i === sel ? "true" : "false");
        links[sel].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        if (links[sel]) location.href = links[sel].href;
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey &&
          e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault();
        openSearch();
      }
      if (e.key === "Escape" && dlg.hasAttribute("open")) closeSearch();
    });
  }

  function boot() { mountTokenizer(); mountAttention(); mountMultiHead(); mountCache(); mountKeys(); mountShell(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
