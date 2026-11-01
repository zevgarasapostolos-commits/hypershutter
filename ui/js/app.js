/* HyperShutter screens: Projects (home), Scan & Analyze, Review. */
(function () {
  const HS = window.HS;
  const t = (k, v) => HS.t(k, v);
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const view = $("#view");

  const STAGES = ["scan", "sync", "frames", "describe", "structure"];
  const STAR_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>';

  const S = {
    view: "home",
    info: null,
    recent: [],
    project: null, // {root, name, known, event_type, event_name, schedule, has_structure}
    scan: null, // scan summary
    stages: {}, // stage -> {status, done, total}
    model: null,
    analyzeResult: null,
    review: null,
    current: null, // selected folder key
    sel: new Set(),
    lastClick: null,
    reviewOnly: false,
    apply: null, // dry-run plan while the Apply card is open
    applyProgress: null,
    applyDone: null,
    backupDest: null,
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("error", !!isError);
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (el.hidden = true), isError ? 7000 : 3500);
  }

  function ask(message) {
    return new Promise((resolve) => {
      const m = $("#modal");
      $("#modal-text").textContent = message;
      m.hidden = false;
      const done = (v) => {
        m.hidden = true;
        $("#modal-ok").onclick = $("#modal-cancel").onclick = null;
        resolve(v);
      };
      $("#modal-ok").onclick = () => done(true);
      $("#modal-cancel").onclick = () => done(false);
      $("#modal-ok").focus();
    });
  }

  async function call(name, args) {
    try {
      return await HS.call(name, args);
    } catch (e) {
      toast(t("common.error") + ": " + e.message, true);
      throw e;
    }
  }

  // ---------------- navigation ----------------

  function canGo(v) {
    if (v === "analyze") return !!S.project;
    if (v === "review") return !!(S.project && S.project.has_structure);
    return true;
  }

  function updateNav() {
    $$(".nav-item").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === S.view);
      b.disabled = !canGo(b.dataset.view);
    });
  }

  async function go(v) {
    if (!canGo(v)) return;
    S.view = v;
    updateNav();
    if (v === "review" && !S.review) S.review = await call("review");
    render();
  }

  function render() {
    updateNav();
    view.scrollTop = 0;
    if (S.view === "home") renderHome();
    else if (S.view === "analyze") renderAnalyze();
    else renderReview();
  }

  // ---------------- Projects ----------------

  function renderHome() {
    const p = S.project;
    const types = (S.info ? S.info.event_types : ["baptism", "wedding", "event"])
      .map((ty) => `<button class="seg ${p && p.event_type === ty ? "on" : ""}" data-type="${ty}">${esc(t("type." + ty))}</button>`)
      .join("");
    view.innerHTML = `
      <header class="view-head">
        <p class="eyebrow">${esc(t("home.eyebrow"))}</p>
        <h1>${esc(t("home.title"))}</h1>
      </header>
      <section class="dropzone" id="drop">
        <p class="drop-title">${esc(t("home.drop"))}</p>
        <p class="drop-or">${esc(t("home.or"))}</p>
        <button class="btn" id="choose">${esc(t("home.choose"))}</button>
      </section>
      ${
        p
          ? `<section class="card project-form">
        <p class="eyebrow">${esc(t("home.folder"))}</p>
        <h2 class="project-name">${esc(p.name)}</h2>
        <p class="muted path">${esc(p.root)} · ${esc(p.known ? t("home.known") : t("home.new"))}</p>
        <div class="field"><span class="label">${esc(t("home.type"))}</span><div class="segs" id="types">${types}</div></div>
        <label class="field"><span class="label">${esc(t("home.name"))}</span>
          <input id="ev-name" value="${esc(p.event_name)}" autocomplete="off"><span class="hint">${esc(t("home.name_hint"))}</span></label>
        <label class="field"><span class="label">${esc(t("home.schedule"))}</span>
          <textarea id="ev-schedule" rows="2">${esc(p.schedule)}</textarea><span class="hint">${esc(t("home.schedule_hint"))}</span></label>
        <div class="actions">
          <button class="btn primary" id="scan">${esc(t("home.scan"))}</button>
          ${p.has_structure ? `<button class="btn" id="open-review">${esc(t("home.open_review"))}</button>` : ""}
        </div>
      </section>`
          : ""
      }
      <section class="recent">
        <p class="eyebrow">${esc(t("home.recent"))}</p>
        ${
          S.recent.length
            ? `<ul class="recent-list">${S.recent
                .map(
                  (r) => `<li><button class="recent-item" data-root="${esc(r.root)}" ${r.available ? "" : "disabled"}>
                <span class="recent-name">${esc(r.name)}</span>
                <span class="muted">${esc(r.available ? r.root : t("home.missing"))}</span></button></li>`
                )
                .join("")}</ul>`
            : `<p class="muted">${esc(t("home.none"))}</p>`
        }
      </section>`;

    $("#choose").onclick = async () => {
      const path = await call("pick_folder");
      if (path) selectFolder(path);
    };
    const drop = $("#drop");
    drop.ondragover = (e) => {
      e.preventDefault();
      drop.classList.add("over");
    };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      // In the app window Python receives the full path and sends a "dropped" event.
      setTimeout(() => {
        if (!drop.dataset.got) toast(t("home.drop_browser"));
      }, 900);
    };
    $$(".recent-item").forEach((b) => (b.onclick = () => selectFolder(b.dataset.root)));
    if (p) {
      $$("#types .seg").forEach(
        (b) =>
          (b.onclick = () => {
            p.event_type = b.dataset.type;
            $$("#types .seg").forEach((x) => x.classList.toggle("on", x === b));
          })
      );
      $("#scan").onclick = startScan;
      const or = $("#open-review");
      if (or) or.onclick = () => go("review");
    }
  }

  async function selectFolder(path) {
    const drop = $("#drop");
    if (drop) drop.dataset.got = "1";
    S.project = await call("open_project", { path });
    S.scan = null;
    S.review = null;
    S.analyzeResult = null;
    S.stages = {};
    S.current = null;
    S.sel.clear();
    S.view = "home";
    render();
  }

  async function startScan() {
    const p = S.project;
    if ($("#ev-name")) p.event_name = $("#ev-name").value;
    if ($("#ev-schedule")) p.schedule = $("#ev-schedule").value;
    S.stages = {};
    S.scan = null;
    S.analyzeResult = null;
    await call("start_scan", { path: p.root, event_type: p.event_type, event_name: p.event_name, schedule: p.schedule });
    setStage("scan", "run");
    go("analyze");
  }

  // ---------------- Scan & Analyze ----------------

  function setStage(stage, status, done, total) {
    const i = STAGES.indexOf(stage);
    STAGES.forEach((s, k) => {
      if (k < i && (!S.stages[s] || S.stages[s].status === "run" || S.stages[s].status === "wait"))
        S.stages[s] = { status: S.stages[s] && S.stages[s].status === "skip" ? "skip" : "done" };
    });
    S.stages[stage] = { status, done: done || 0, total: total || 0 };
  }

  function stageRows() {
    return STAGES.map((s) => {
      const st = S.stages[s] || { status: "wait" };
      const pct = st.status === "done" ? 100 : st.total ? Math.round((100 * st.done) / st.total) : 0;
      const count = st.status === "run" && st.total > 1 ? ` · ${st.done}/${st.total}` : "";
      return `<li class="stage ${st.status}">
        <span class="stage-name">${esc(t("stage." + s))}</span>
        <span class="stage-status">${esc(t("status." + st.status))}${count}</span>
        <span class="bar"><span style="width:${pct}%"></span></span></li>`;
    }).join("");
  }

  function updateStages() {
    const ul = $("#stages");
    if (ul) ul.innerHTML = stageRows();
  }

  function renderAnalyze() {
    const p = S.project;
    if (!p) {
      view.innerHTML = `<p class="muted">${esc(t("analyze.idle"))}</p>`;
      return;
    }
    const sc = S.scan;
    const running = HS.job && HS.job.status === "running";
    view.innerHTML = `
      <header class="view-head">
        <p class="eyebrow">${esc(t("analyze.eyebrow"))}</p>
        <h1>${esc(p.name)}</h1>
        ${sc ? `<p class="muted">${esc(t("analyze.clips", { videos: sc.videos, audio: sc.audio }))}</p>` : ""}
      </header>
      <ul class="stages" id="stages">${stageRows()}</ul>
      ${!sc && !running ? `<div class="actions"><button class="btn primary" id="start">${esc(t("analyze.start"))}</button></div>` : ""}
      ${sc ? devicesCard(sc) + checksCard(sc) + aiCard(sc, running) : ""}
      ${
        S.analyzeResult
          ? `<section class="card result"><p>${esc(
              t("analyze.result", { folders: S.analyzeResult.folders, review: S.analyzeResult.needs_review, cost: S.analyzeResult.cost.toFixed(2) })
            )}</p><div class="actions"><button class="btn primary" id="to-review">${esc(t("analyze.open_review"))}</button></div></section>`
          : ""
      }`;

    const start = $("#start");
    if (start) start.onclick = startScan;
    $$(".offset-form").forEach(
      (f) =>
        (f.onsubmit = async (e) => {
          e.preventDefault();
          const r = await call("set_offset", { device: f.dataset.dev, text: f.querySelector("input").value });
          S.scan.devices = r.devices;
          renderAnalyze();
        })
    );
    $$("input[name=model]").forEach((r) => (r.onchange = () => (S.model = r.value)));
    const run = $("#run-ai");
    if (run) run.onclick = () => startAnalyze(false);
    const off = $("#run-offline");
    if (off) off.onclick = () => startAnalyze(true);
    const rescan = $("#rescan");
    if (rescan) rescan.onclick = () => go("home");
    const tr = $("#to-review");
    if (tr) tr.onclick = () => go("review");
  }

  function devicesCard(sc) {
    const rows = sc.devices
      .map(
        (d) => `<tr>
        <td><strong>${esc(d.id)}</strong> <span class="muted">${esc(d.pattern)}</span></td>
        <td>${esc(t("kind." + d.kind))}${d.model ? ` <span class="muted">${esc(d.model)}</span>` : ""}</td>
        <td class="num">${d.clips}</td><td class="num">${esc(d.length)}</td>
        <td class="num offset">${esc(d.offset)}</td>
        <td><span class="pill ${esc(d.status)}">${esc(t("clock." + d.status))}</span></td>
        <td>${
          d.kind === "camera" || d.kind === "recorder"
            ? `<form class="offset-form" data-dev="${esc(d.id)}"><input aria-label="${esc(t("col.offset"))}" placeholder="+14:00" size="8"><button class="btn small">${esc(t("analyze.set"))}</button></form>`
            : ""
        }</td></tr>`
      )
      .join("");
    return `<section class="card">
      <h2 class="card-title">${esc(t("analyze.cameras"))}</h2>
      <table class="table"><thead><tr><th>${esc(t("col.device"))}</th><th>${esc(t("col.kind"))}</th><th class="num">${esc(t("col.clips"))}</th>
      <th class="num">${esc(t("col.length"))}</th><th class="num">${esc(t("col.offset"))}</th><th>${esc(t("col.status"))}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="hint">${esc(t("analyze.offset_hint"))}</p></section>`;
  }

  function checksCard(sc) {
    const n = sc.corrupt.length + sc.duplicates.length;
    const list = sc.corrupt.concat(sc.duplicates).map((x) => `<li><code>${esc(x.clip)}</code> <span class="muted">${esc(x.why)}</span></li>`).join("");
    return `<section class="card">
      <h2 class="card-title">${esc(t("analyze.checks"))}</h2>
      ${
        n
          ? `<p>${esc(t("analyze.corrupt", { n: sc.corrupt.length }))} · ${esc(t("analyze.dups", { n: sc.duplicates.length }))}</p><ul class="flag-list">${list}</ul>`
          : `<p class="muted">${esc(t("analyze.checks_ok"))}</p>`
      }</section>`;
  }

  function aiCard(sc, running) {
    if (!S.model) S.model = S.info.default_model;
    const opts = sc.estimates
      .map(
        (e) => `<label class="model ${S.model === e.model ? "on" : ""}">
        <input type="radio" name="model" value="${esc(e.model)}" ${S.model === e.model ? "checked" : ""}>
        <span class="model-name">${esc(t("model." + e.model) === "model." + e.model ? e.label : t("model." + e.model))}</span>
        <span class="muted">${esc(t("analyze.est", { cost: e.cost.toFixed(2), minutes: e.minutes }))}${
          e.cached ? " · " + esc(t("analyze.cached", { n: e.cached })) : ""
        }</span></label>`
      )
      .join("");
    return `<section class="card">
      <h2 class="card-title">${esc(t("analyze.ai"))}</h2>
      <div class="models">${opts}</div>
      <p class="hint">${esc(t("analyze.ai_hint"))}</p>
      <div class="actions">
        <button class="btn primary" id="run-ai" ${running ? "disabled" : ""}>${esc(t("analyze.run"))}</button>
        <button class="btn" id="run-offline" ${running ? "disabled" : ""}>${esc(t("analyze.offline"))}</button>
        <button class="btn quiet" id="rescan" ${running ? "disabled" : ""}>${esc(t("analyze.rescan"))}</button>
      </div></section>`;
  }

  async function startAnalyze(offline) {
    if (S.project.has_structure && !(await ask(t("analyze.replace")))) return;
    S.analyzeResult = null;
    S.review = null;
    if (offline) S.stages.describe = { status: "skip" };
    await call("start_analyze", { model: S.model, offline });
    setStage(offline ? "structure" : "describe", "run");
    renderAnalyze();
  }

  // ---------------- Review ----------------

  function folderName(c) {
    return c.folder.slice(c.folder.indexOf(" ") + 1);
  }

  function catOf(key) {
    return S.review.categories.find((c) => c.key === key);
  }

  function renderReview() {
    const R = S.review;
    if (!R || !R.categories.length) {
      view.innerHTML = `<p class="muted">${esc(t("review.empty"))}</p>`;
      return;
    }
    if (!S.current || !catOf(S.current)) S.current = R.categories[0].key;
    const nClips = Object.keys(R.clips).length;
    const flagged = new Set(R.needs_review);
    const items = R.categories
      .map((c) => {
        const nrev = c.clips.filter((x) => flagged.has(x)).length;
        const head = !c.sub && c.kind !== "unusable";
        return `<li class="folder ${c.key === S.current && !S.reviewOnly ? "active" : ""} ${c.sub ? "sub" : ""}" data-key="${esc(c.key)}">
          <span class="fnum">${c.number}${esc(c.sub)}</span>
          <span class="fname"><span>${esc(folderName(c))}</span><small>${esc(c.label)}</small></span>
          <span class="fcount">${c.clips.length}${nrev ? `<i class="dot" title="${esc(t("review.check"))}"></i>` : ""}</span>
          ${
            head
              ? `<span class="fmove"><button data-move="-1" title="${esc(t("review.up"))}" aria-label="${esc(t("review.up"))}">&#8593;</button><button data-move="1" title="${esc(
                  t("review.down")
                )}" aria-label="${esc(t("review.down"))}">&#8595;</button></span>`
              : `<span class="fmove"></span>`
          }</li>`;
      })
      .join("");

    view.innerHTML = `
      <header class="view-head review-head">
        <div>
          <p class="eyebrow">${esc(t("review.eyebrow"))} · ${esc(R.source === "offline" ? t("review.source_offline") : t("review.source_ai"))}${
      R.edited ? ` · <span class="gold">${esc(t("review.edited"))}</span>` : ""
    }</p>
          <h1>${esc(R.name)}</h1>
          <p class="muted">${esc(t("review.summary", { clips: nClips, folders: R.categories.length, review: R.needs_review.length }))}</p>
        </div>
        <div class="head-actions">
          <label class="toggle"><input type="checkbox" id="only" ${S.reviewOnly ? "checked" : ""}> ${esc(t("review.only"))} (${R.needs_review.length})</label>
          <button class="btn quiet" id="reset" ${R.edited ? "" : "disabled"}>${esc(t("review.reset"))}</button>
          <button class="btn primary" id="apply-open">${esc(t("apply.open"))}</button>
        </div>
      </header>
      <section class="card apply-card" id="apply-card" ${S.apply ? "" : "hidden"}>${S.apply ? applyCard() : ""}</section>
      ${R.notes ? `<details class="notes"><summary>${esc(t("review.notes"))}</summary><p>${esc(R.notes)}</p></details>` : ""}
      <p class="hint">${esc(t("review.hint"))}</p>
      <div class="review">
        <ol class="folders" id="folders">${items}</ol>
        <section class="panel" id="panel"></section>
      </div>`;

    $("#apply-open").onclick = openApply;
    bindApply();
    $("#only").onchange = (e) => {
      S.reviewOnly = e.target.checked;
      S.sel.clear();
      renderReview();
    };
    $("#reset").onclick = async () => {
      if (!(await ask(t("review.reset_q")))) return;
      S.review = await call("review_reset");
      S.sel.clear();
      renderReview();
    };
    $$("#folders .folder").forEach((li) => {
      li.onclick = (e) => {
        if (e.target.closest("[data-move]")) return;
        S.current = li.dataset.key;
        S.reviewOnly = false;
        S.sel.clear();
        renderReview();
      };
      li.ondragover = (e) => {
        if (!e.dataTransfer.types.includes("text/x-hs-clips")) return;
        e.preventDefault();
        li.classList.add("over");
      };
      li.ondragleave = () => li.classList.remove("over");
      li.ondrop = (e) => {
        e.preventDefault();
        li.classList.remove("over");
        const ids = JSON.parse(e.dataTransfer.getData("text/x-hs-clips") || "[]");
        if (ids.length) edit("move", { clips: ids, to: li.dataset.key }, true);
      };
    });
    $$("#folders [data-move]").forEach(
      (b) => (b.onclick = () => edit("move_group", { key: b.closest(".folder").dataset.key, delta: +b.dataset.move }))
    );
    renderPanel();
  }

  // ---------------- Apply / Undo ----------------

  async function openApply() {
    S.apply = await call("apply_plan");
    S.applyDone = null;
    renderReview();
    $("#apply-card").scrollIntoView({ block: "nearest" });
  }

  function jobRunning(...names) {
    return !!(HS.job && HS.job.status === "running" && names.includes(HS.job.name));
  }

  function applyCard() {
    const A = S.apply;
    const running = jobRunning("apply", "undo");
    const pr = S.applyProgress;
    let body = `<h2 class="card-title">${esc(t("apply.title"))}</h2>`;
    if (A.blocked) {
      body += `<p class="warn">${esc(A.blocked)}</p>`;
    } else if (!A.moves && !A.conflicts.length) {
      body += `<p>${esc(t("apply.nothing"))}</p>`;
    } else {
      body += `<p>${esc(t("apply.summary", { clips: A.clips, sidecars: A.sidecars, gb: A.gb, folders: A.folders, new: A.new_folders, in_place: A.in_place }))}</p>
        <p class="hint">${esc(t("apply.safe"))}</p>`;
      if (A.unassigned) body += `<p class="muted">${esc(t("apply.unassigned", { n: A.unassigned }))}</p>`;
      if (A.conflicts.length)
        body += `<p class="warn">${esc(t("apply.conflicts"))}</p><ul class="flag-list">${A.conflicts.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;
      body += `<div class="backup-row"><label class="toggle"><input type="checkbox" id="do-backup" ${S.backupDest ? "checked" : ""}> ${esc(t("apply.backup"))}</label>
        ${S.backupDest ? `<code>${esc(S.backupDest)}</code>` : ""}<button class="btn small quiet" id="pick-backup">${esc(t("apply.choose"))}</button></div>`;
    }
    if (running && pr) {
      const pct = pr.total ? Math.round((100 * pr.done) / pr.total) : 0;
      body += `<p class="progress-line">${esc(t("apply.progress_" + pr.stage, { done: pr.done, total: pr.total }))}</p><span class="bar"><span style="width:${pct}%"></span></span>`;
    }
    if (S.applyDone) body += `<p class="ok">${esc(S.applyDone)}</p>`;
    const canGo = !A.blocked && A.moves && !A.conflicts.length && !running;
    const last = A.last && A.last.status !== "undone" ? A.last : null;
    body += `<div class="actions">
      ${!A.blocked && A.moves ? `<button class="btn primary" id="apply-go" ${canGo ? "" : "disabled"}>${esc(t("apply.go"))}</button>` : ""}
      ${last ? `<span class="muted last-run">${esc(t("apply.last", { when: last.created, n: last.moved }))}</span><button class="btn" id="undo" ${running ? "disabled" : ""}>${esc(t("apply.undo"))}</button>` : ""}
      <button class="btn quiet" id="apply-close" ${running ? "disabled" : ""}>${esc(t("apply.close"))}</button></div>`;
    return body;
  }

  function renderApplyCard() {
    const card = $("#apply-card");
    if (!card || !S.apply) return;
    card.innerHTML = applyCard();
    bindApply();
  }

  function bindApply() {
    const close = $("#apply-close");
    if (close) close.onclick = () => ((S.apply = null), (S.applyDone = null), renderReview());
    const pick = $("#pick-backup");
    if (pick)
      pick.onclick = async () => {
        const d = await call("pick_folder");
        if (d) S.backupDest = d;
        renderApplyCard();
      };
    const cb = $("#do-backup");
    if (cb)
      cb.onchange = async () => {
        if (cb.checked && !S.backupDest) {
          const d = await call("pick_folder");
          S.backupDest = d || null;
        } else if (!cb.checked) S.backupDest = null;
        renderApplyCard();
      };
    const go = $("#apply-go");
    if (go)
      go.onclick = async () => {
        if (!(await ask(t("apply.confirm", { clips: S.apply.clips, folders: S.apply.folders })))) return;
        S.applyDone = null;
        S.applyProgress = { stage: S.backupDest ? "backup" : "move", done: 0, total: 0 };
        await call("start_apply", { backup_dest: S.backupDest });
        renderApplyCard();
      };
    const undo = $("#undo");
    if (undo)
      undo.onclick = async () => {
        if (!(await ask(t("apply.undo_q")))) return;
        S.applyDone = null;
        S.applyProgress = { stage: "undo", done: 0, total: 0 };
        await call("start_undo");
        renderApplyCard();
      };
  }

  async function afterApplyJob(message) {
    S.applyDone = message;
    S.applyProgress = null;
    S.review = await call("review");
    S.apply = await call("apply_plan");
    if (S.view === "review") renderReview();
  }

  function tile(cid) {
    const R = S.review;
    const c = R.clips[cid];
    const mid = c.frames.length ? c.frames[Math.floor(c.frames.length / 2)] : "";
    const starred = R.stars.includes(cid);
    const flagged = R.needs_review.includes(cid);
    return `<figure class="tile ${S.sel.has(cid) ? "selected" : ""} ${flagged ? "flagged" : ""}" data-clip="${esc(cid)}" draggable="true" title="${esc(c.desc || "")}">
      <div class="thumb">${mid ? `<img src="${esc(mid)}" alt="" loading="lazy" draggable="false">` : ""}
        <button class="star ${starred ? "on" : ""}" title="${esc(t("review.star"))}" aria-label="${esc(t("review.star"))}" aria-pressed="${starred}">${STAR_SVG}</button>
        ${flagged ? `<span class="badge">${esc(t("review.check"))}</span>` : ""}
        <span class="dur">${esc(c.duration)}</span>
      </div>
      <figcaption><span class="cname">${esc(c.name)}</span><span class="cmeta">${esc(c.time)} · ${esc(c.device)}</span>
      ${c.desc ? `<span class="cdesc">${esc(c.desc)}</span>` : ""}</figcaption></figure>`;
  }

  function selBar(clipIds) {
    const R = S.review;
    if (!S.sel.size) return "";
    const opts = R.categories.map((c) => `<option value="${esc(c.key)}">${esc(c.folder)}</option>`).join("");
    return `<div class="selbar">
      <strong>${esc(t("review.selected", { n: S.sel.size }))}</strong>
      <span class="sep"></span>
      <label>${esc(t("review.move"))} <select id="move-to">${opts}</select></label><button class="btn small" id="move">${esc(t("review.move"))}</button>
      <span class="sep"></span>
      ${S.reviewOnly ? "" : `<input id="split-label" placeholder="${esc(t("review.split_ph"))}"><button class="btn small" id="split">${esc(t("review.split"))}</button><span class="sep"></span>`}
      <button class="btn small" id="resolve">${esc(t("review.checked"))}</button>
      <button class="btn small quiet" id="clear-sel">${esc(t("review.clear"))}</button></div>`;
  }

  function renderPanel() {
    const R = S.review;
    const panel = $("#panel");
    let body;
    let order;
    if (S.reviewOnly) {
      const flagged = new Set(R.needs_review);
      order = [];
      const groups = R.categories
        .map((c) => {
          const ids = c.clips.filter((x) => flagged.has(x));
          order.push(...ids);
          return ids.length ? `<h3 class="group-title">${esc(c.folder)}</h3><div class="tiles">${ids.map(tile).join("")}</div>` : "";
        })
        .join("");
      body = `${selBar()}${groups || `<p class="muted">${esc(t("review.none_flagged"))}</p>`}`;
    } else {
      const c = catOf(S.current);
      order = c.clips;
      const others = R.categories.filter((x) => x.key !== c.key).map((x) => `<option value="${esc(x.key)}">${esc(x.folder)}</option>`).join("");
      body = `
        <div class="panel-head">
          <p class="eyebrow">${esc(t("review.folder"))} ${c.number}${esc(c.sub)}</p>
          <h2 class="folder-title">${esc(c.folder)}</h2>
          <p class="muted">${esc(t("review.meta", { n: c.clips.length, min: c.minutes }))}</p>
          <div class="panel-fields">
            <label class="field"><span class="label">${esc(t("review.label"))}</span><input id="f-label" value="${esc(c.label)}"></label>
            <label class="field"><span class="label">${esc(t("review.desc"))}</span><input id="f-desc" value="${esc(c.description)}"></label>
            <div class="field merge"><span class="label">${esc(t("review.merge"))}</span>
              <div class="inline"><select id="merge-to">${others}</select><button class="btn small" id="merge">${esc(t("review.merge"))}</button></div></div>
          </div>
        </div>
        ${selBar()}
        <div class="tiles">${c.clips.map(tile).join("")}</div>`;
    }
    panel.innerHTML = body;
    bindTiles(order);
    bindPanel();
  }

  function bindPanel() {
    const c = S.reviewOnly ? null : catOf(S.current);
    if (c) {
      const label = $("#f-label");
      const commitLabel = () => {
        if (document.body.contains(label) && label.value.trim() && label.value.trim().toUpperCase() !== c.label) edit("rename", { key: c.key, label: label.value });
      };
      label.onkeydown = (e) => e.key === "Enter" && label.blur();
      label.onblur = commitLabel;
      const desc = $("#f-desc");
      desc.onkeydown = (e) => e.key === "Enter" && desc.blur();
      desc.onblur = () => document.body.contains(desc) && desc.value !== c.description && edit("describe", { key: c.key, text: desc.value });
      $("#merge").onclick = async () => {
        const dst = catOf($("#merge-to").value);
        if (!dst || !(await ask(t("review.merge_q", { a: c.folder, b: dst.folder })))) return;
        S.current = dst.key;
        edit("merge", { src: c.key, dst: dst.key });
      };
    }
    const mv = $("#move");
    if (mv) {
      mv.onclick = () => edit("move", { clips: [...S.sel], to: $("#move-to").value }, true);
      const sp = $("#split");
      if (sp)
        sp.onclick = async () => {
          const r = await edit("split", { key: S.current, clips: [...S.sel], label: $("#split-label").value }, true);
          if (r && r.result) S.current = r.result;
          renderReview();
        };
      $("#resolve").onclick = () => edit("resolve", { clips: [...S.sel] }, true);
      $("#clear-sel").onclick = () => {
        S.sel.clear();
        renderPanel();
      };
    }
  }

  function bindTiles(order) {
    $$("#panel .tile").forEach((fig) => {
      const cid = fig.dataset.clip;
      const clip = S.review.clips[cid];
      const img = fig.querySelector("img");
      if (img && clip.frames.length > 1) {
        const mid = clip.frames[Math.floor(clip.frames.length / 2)];
        fig.querySelector(".thumb").onmousemove = (e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const i = Math.min(clip.frames.length - 1, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * clip.frames.length)));
          if (img.getAttribute("src") !== clip.frames[i]) img.src = clip.frames[i];
        };
        fig.querySelector(".thumb").onmouseleave = () => (img.src = mid);
      }
      fig.onclick = (e) => {
        if (e.target.closest(".star")) return;
        if (e.shiftKey && S.lastClick && order.includes(S.lastClick)) {
          const a = order.indexOf(S.lastClick);
          const b = order.indexOf(cid);
          order.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((x) => S.sel.add(x));
        } else if (S.sel.has(cid)) S.sel.delete(cid);
        else S.sel.add(cid);
        S.lastClick = cid;
        renderPanel();
      };
      fig.ondragstart = (e) => {
        const ids = S.sel.has(cid) ? [...S.sel] : [cid];
        e.dataTransfer.setData("text/x-hs-clips", JSON.stringify(ids));
        e.dataTransfer.effectAllowed = "move";
      };
      fig.querySelector(".star").onclick = async (e) => {
        e.stopPropagation();
        const r = await edit("star", { clip: cid }, false, true);
        if (r) renderPanel();
      };
    });
  }

  async function edit(op, args, clearSel, quiet) {
    const r = await call("review_edit", { op, args });
    S.review = r.review;
    if (clearSel) S.sel.clear();
    if (!quiet) renderReview();
    return r;
  }

  // ---------------- events from the core ----------------

  HS.on((ev) => {
    if (ev.type === "progress" && ["backup", "move", "undo"].includes(ev.stage)) {
      S.applyProgress = ev;
      renderApplyCard();
    } else if (ev.type === "progress") {
      setStage(ev.stage, "run", ev.done, ev.total);
      if (S.view === "analyze") updateStages();
    } else if (ev.type === "job_done" && ev.name === "apply") {
      afterApplyJob(t("apply.done", { moved: ev.result.moved }));
    } else if (ev.type === "job_done" && ev.name === "undo") {
      afterApplyJob(t("apply.undone", { n: ev.result.back }) + (ev.result.problems.length ? " " + ev.result.problems.join("; ") : ""));
    } else if (ev.type === "job_done" && ev.name === "scan") {
      ["scan", "sync", "frames"].forEach((s) => (S.stages[s] = { status: "done" }));
      S.scan = ev.result;
      S.project.has_structure = ev.result.has_structure;
      if (S.view === "analyze") renderAnalyze();
      refreshRecent();
    } else if (ev.type === "job_done" && ev.name === "analyze") {
      if (!S.stages.describe || S.stages.describe.status !== "skip") S.stages.describe = { status: "done" };
      S.stages.structure = { status: "done" };
      S.analyzeResult = ev.result;
      S.project.has_structure = true;
      S.review = null;
      if (S.view === "analyze") renderAnalyze();
      updateNav();
    } else if (ev.type === "job_error" && (ev.name === "apply" || ev.name === "undo")) {
      S.applyProgress = null;
      toast(t("common.error") + ": " + ev.error, true);
      call("apply_plan").then((a) => ((S.apply = a), renderApplyCard()));
    } else if (ev.type === "job_error") {
      const running = STAGES.find((s) => S.stages[s] && S.stages[s].status === "run");
      if (running) S.stages[running].status = "error";
      toast(t("common.error") + ": " + ev.error, true);
      if (S.view === "analyze") renderAnalyze();
    } else if (ev.type === "dropped") {
      selectFolder(ev.path);
    }
  });

  async function refreshRecent() {
    try {
      S.recent = await HS.call("recent");
    } catch (e) {}
    if (S.view === "home") renderHome();
  }

  // ---------------- start ----------------

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && S.sel.size && S.view === "review") {
      S.sel.clear();
      renderPanel();
    }
  });
  $$(".nav-item").forEach((b) => (b.onclick = () => go(b.dataset.view)));
  $$("[data-lang]").forEach(
    (b) =>
      (b.onclick = () => {
        HS.setLang(b.dataset.lang);
        render();
      })
  );

  (async function init() {
    await HS.loadStrings();
    HS.setLang(HS.lang);
    S.info = await call("info");
    $("#version").textContent = "v" + S.info.version;
    S.recent = await call("recent");
    render();
  })();
})();
