/* HyperShutter screens beyond the core flow: Onboarding, Ingest, Export, Drives, Accuracy Lab,
   Settings, Features, Help & Support, About — plus the sidebar's background-jobs and drive status. */
(function () {
  const HS = window.HS;
  const U = () => HS.ui;
  const t = (k, v) => HS.t(k, v);
  const esc = (s) => U().esc(s);
  const $ = (s, r) => U().$(s, r);
  const $$ = (s, r) => U().$$(s, r);
  const call = (n, a) => U().call(n, a);
  const view = () => U().view;

  const X = {
    cards: [],
    card: null, // chosen card {path, …}
    label: "",
    project: "",
    dests: [],
    pre: null,
    ingest: null, // {progress, report, error}
    drives: [],
    jobs: null,
    settings: null,
    presets: [],
    exp: { preset: null, folders: [], dest: "", plan: null },
    lab: { reports: [], open: null, text: "" },
    onb: 0,
  };

  const gb = (b) => (b / 1e9).toFixed(b >= 1e11 ? 0 : 1);
  const pct = (x) => (100 * x).toFixed(1) + "%";
  const head = (eyebrow, title, sub) =>
    `<header class="view-head"><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1>${sub ? `<p class="muted">${esc(sub)}</p>` : ""}</header>`;

  function meter(used, total, status) {
    const p = total ? Math.min(100, Math.round((100 * used) / total)) : 0;
    return `<span class="meter ${status || ""}"><span style="width:${p}%"></span></span>`;
  }

  // ---------------- Onboarding ----------------

  HS.screens.onboarding = {
    canGo: () => true,
    async load() {
      X.settings = await call("settings");
    },
    render() {
      const s = X.settings || {};
      const steps = [
        `<img class="hero-mark" src="/ui/img/mark.svg" alt=""><h2 class="card-title">${esc(t("onb.welcome_title"))}</h2><p>${esc(t("onb.welcome"))}</p>
         <div class="segs" id="onb-lang"><button class="seg ${HS.lang === "en" ? "on" : ""}" data-l="en">English</button><button class="seg ${HS.lang === "el" ? "on" : ""}" data-l="el">Ελληνικά</button></div>`,
        `<h2 class="card-title">${esc(t("onb.ffmpeg_title"))}</h2>${
          s.ffmpeg ? `<p class="ok">${esc(t("onb.ffmpeg_ok"))}</p>` : `<p class="warn">${esc(t("onb.ffmpeg_missing"))}</p><pre class="code">brew install ffmpeg</pre>`
        }`,
        `<h2 class="card-title">${esc(t("onb.dest_title"))}</h2><p>${esc(t("onb.dest"))}</p>${destList(s.destinations || [], "onb-dest")}`,
      ];
      view().innerHTML = `${head(t("onb.eyebrow"), t("onb.title"))}
        <section class="card onboarding"><div class="steps">${steps.map((_, i) => `<span class="step ${i === X.onb ? "on" : i < X.onb ? "done" : ""}"></span>`).join("")}</div>
        ${steps[X.onb]}
        <div class="actions">${X.onb ? `<button class="btn quiet" id="onb-back">${esc(t("onb.back"))}</button>` : ""}
          <button class="btn primary" id="onb-next">${esc(X.onb === steps.length - 1 ? t("onb.finish") : t("onb.next"))}</button></div></section>`;
      $$("#onb-lang .seg").forEach((b) => (b.onclick = async () => {
        HS.setLang(b.dataset.l);
        await call("save_settings", { changes: { language: b.dataset.l } });
        HS.screens.onboarding.render();
      }));
      bindDestList("onb-dest", s.destinations || [], async (list) => {
        X.settings = await call("save_settings", { changes: { destinations: list } });
        HS.screens.onboarding.render();
      });
      const back = $("#onb-back");
      if (back) back.onclick = () => ((X.onb -= 1), HS.screens.onboarding.render());
      $("#onb-next").onclick = async () => {
        if (X.onb < steps.length - 1) {
          X.onb += 1;
          HS.screens.onboarding.render();
        } else {
          await call("save_settings", { changes: { onboarded: true } });
          U().S.info.onboarded = true;
          U().go("home");
        }
      };
    },
  };

  function destList(list, id, free) {
    return `<ul class="dest-list" id="${id}">${list
      .map((d, i) => {
        const f = free && free.find((x) => x.path === d);
        return `<li><code>${esc(d)}</code>${f ? ` <span class="muted">${esc(t("ingest.free", { gb: f.free_gb }))}</span>` : ""}
          <button class="btn small quiet" data-rm="${i}">${esc(t("ingest.remove"))}</button></li>`;
      })
      .join("")}</ul><button class="btn small" id="${id}-add">${esc(t("ingest.add_dest"))}</button>`;
  }

  function bindDestList(id, list, save) {
    const add = $("#" + id + "-add");
    if (add)
      add.onclick = async () => {
        const d = await call("pick_dest");
        if (d && !list.includes(d)) save(list.concat([d]));
      };
    $$(`#${id} [data-rm]`).forEach((b) => (b.onclick = () => save(list.filter((_, i) => i !== +b.dataset.rm))));
  }

  // ---------------- Ingest ----------------

  HS.screens.ingest = {
    canGo: () => true,
    async load() {
      X.cards = await call("cards");
      X.settings = await call("settings");
      if (!X.dests.length) X.dests = (X.settings.destinations || []).slice();
      X.history = await call("ingest_history");
      const st = await call("ingest_state");
      if (st && st.status === "done" && !X.ingest) X.ingest = { report: st.report };
    },
    render() {
      const S = U().S;
      if (!X.project) X.project = suggestedEvent();
      const running = X.ingest && X.ingest.progress && !X.ingest.report && !X.ingest.error;
      const cardsHtml = X.cards.length
        ? `<ul class="card-list">${X.cards
            .map(
              (c) => `<li><button class="card-item ${X.card && X.card.path === c.path ? "on" : ""}" data-path="${esc(c.path)}">
            <span class="card-name">${esc(c.name)}</span><span class="muted">${esc(t("ingest.kind." + c.kind))}${c.camera ? " · " + esc(c.camera) : ""}</span>
            <span class="muted">${c.clips} ${esc(t("ingest.clips"))} · ${c.gb} GB${c.label ? " · " + esc(c.label) : ""}</span></button></li>`
            )
            .join("")}</ul>`
        : `<p class="muted">${esc(t("ingest.no_cards"))}</p>`;
      view().innerHTML = `${head(t("ingest.eyebrow"), t("ingest.title"), t("ingest.sub"))}
        <section class="card"><h2 class="card-title">${esc(t("ingest.cards"))}</h2>${cardsHtml}
          <div class="actions"><button class="btn small quiet" id="rescan">${esc(t("ingest.rescan"))}</button>
          <button class="btn small quiet" id="as-card">${esc(t("ingest.folder_as_card"))}</button></div></section>
        ${X.card ? setupCard() : ""}
        ${X.ingest ? progressCard() : ""}
        ${historyCard()}`;
      $$(".card-item").forEach((b) => (b.onclick = () => chooseCard(X.cards.find((c) => c.path === b.dataset.path))));
      $("#rescan").onclick = async () => ((X.cards = await call("cards")), HS.screens.ingest.render());
      $("#as-card").onclick = async () => {
        const p = await call("pick_dest");
        if (p) chooseCard(await call("read_folder_as_card", { path: p }));
      };
      if (X.card) bindSetup(running);
      const ej = $("#eject");
      if (ej)
        ej.onclick = async () => {
          await call("eject_card", { path: X.ingest.card_path });
          U().toast(t("ingest.ejected"));
          X.cards = await call("cards");
          X.card = null;
          X.ingest = null;
          HS.screens.ingest.render();
        };
    },
  };

  function suggestedEvent() {
    const open = U().S.project;
    const onCard = open && [...(X.cards || []), X.card].some((c) => c && open.root.startsWith(c.path + "/"));
    return open && !onCard ? open.name : "";       // a folder opened on the card itself is not an event
  }

  async function chooseCard(c) {
    X.card = c;
    X.label = c.label || X.label;
    X.pre = null;
    await preflight();
    HS.screens.ingest.render();
  }

  async function preflight() {
    if (!X.card) return;
    X.pre = await call("ingest_preflight", { card: X.card.path, project: X.project, label: X.label, dests: X.dests });
  }

  function problemText(p) {
    return t("ingest.p_" + p.code, { path: p.path, need: p.need_gb, free: p.free_gb });
  }

  function setupCard() {
    const P = X.pre || { problems: [], targets: [], drives: [] };
    const ready = X.project && X.label && X.dests.length && !P.problems.length;
    const space = P.card_gb != null && X.dests.length
      ? `<p class="muted">${esc(P.make_proxies
          ? t("ingest.need_with", { card: P.card_gb, proxies: P.proxies_gb, margin: P.margin_gb })
          : t("ingest.need_without", { card: P.card_gb, margin: P.margin_gb }))}</p>`
      : "";
    const noProxyHint = P.make_proxies && P.problems.some((p) => p.code === "space")
      ? `<p class="hint">${esc(t("ingest.hint_no_proxies", { gb: P.without_proxies_gb }))}</p>` : "";
    return `<section class="card"><h2 class="card-title">${esc(t("ingest.setup", { card: X.card.name }))}</h2>
      <label class="field"><span class="label">${esc(t("ingest.label"))}</span><input id="in-label" value="${esc(X.label)}" placeholder="cam apos"><span class="hint">${esc(t("ingest.label_hint"))}</span></label>
      <label class="field"><span class="label">${esc(t("ingest.project"))}</span><input id="in-project" value="${esc(X.project)}" placeholder="074 Γ15-11-2026"><span class="hint">${esc(t("ingest.project_hint"))}</span></label>
      <div class="field"><span class="label">${esc(t("ingest.dests"))}</span>${destList(X.dests, "in-dest", P.drives)}</div>
      <label class="toggle"><input type="checkbox" id="in-proxies" ${P.make_proxies ? "checked" : ""}> ${esc(t("set.make_proxies"))}</label>
      ${P.targets.length ? `<p class="muted">${esc(t("ingest.into"))} ${P.targets.map((x) => `<code>${esc(x)}</code>`).join(" · ")}</p>` : ""}
      ${space}
      ${P.problems.map((x) => `<p class="warn">${esc(problemText(x))}</p>`).join("")}
      ${noProxyHint}
      <p class="hint">${esc(t("ingest.rules"))}</p>
      <div class="actions"><button class="btn primary" id="in-start" ${ready ? "" : "disabled"}>${esc(t("ingest.start", { n: X.card.files, gb: X.card.gb }))}</button></div></section>`;
  }

  function bindSetup(running) {
    const upd = async () => {
      X.label = $("#in-label").value.trim();
      X.project = $("#in-project").value.trim();
      await preflight();
      HS.screens.ingest.render();
    };
    $("#in-label").onchange = upd;
    $("#in-project").onchange = upd;
    $("#in-proxies").onchange = async (e) => {
      await call("save_settings", { changes: { make_proxies: e.target.checked } });
      await preflight();
      HS.screens.ingest.render();
    };
    bindDestList("in-dest", X.dests, async (list) => {
      X.dests = list;
      await preflight();
      HS.screens.ingest.render();
    });
    const go = $("#in-start");
    if (go) {
      go.disabled = go.disabled || running;
      go.onclick = async () => {
        X.ingest = { progress: { phase: "copy", done: 0, total: X.card.files, dests: [] } };
        await call("start_ingest", { card: X.card.path, project: X.project, label: X.label, dests: X.dests });
        HS.screens.ingest.render();
      };
    }
  }

  function progressCard() {
    const I = X.ingest;
    if (I.error) return `<section class="card"><p class="warn">${esc(I.error)}</p></section>`;
    if (I.report) {
      const R = I.report;
      return `<section class="card ${R.safe ? "safe" : "unsafe"}"><h2 class="card-title">${esc(R.safe ? t("ingest.safe") : t("ingest.not_safe"))}</h2>
        <p>${esc(t("ingest.summary", { files: R.files, gb: R.gb, copied: R.copied, skipped: R.skipped, s: Math.round(R.seconds) }))}</p>
        <table class="table"><thead><tr><th>${esc(t("ingest.dest"))}</th><th class="num">${esc(t("ingest.verified"))}</th><th class="num">${esc(t("ingest.write"))}</th><th class="num">${esc(t("ingest.verify"))}</th></tr></thead><tbody>${R.dests
          .map((d) => `<tr><td><code>${esc(d.root)}</code></td><td class="num">${d.verified}/${R.files}</td><td class="num">${d.write_mb_s ?? "–"} MB/s</td><td class="num">${d.verify_mb_s ?? "–"} MB/s</td></tr>`)
          .join("")}</tbody></table>
        ${R.failed.map((f) => `<p class="warn">${esc(f.dest)}: ${esc(f.file)} (${esc(f.why)})</p>`).join("")}
        ${R.safe && I.card_path ? `<div class="actions"><button class="btn" id="eject">${esc(t("ingest.eject"))}</button></div>` : ""}</section>`;
    }
    const P = I.progress || {};
    return `<section class="card"><h2 class="card-title">${esc(t("ingest.phase." + (P.phase || "copy")))} · ${P.done || 0}/${P.total || 0}</h2>
      <p class="muted">${esc(P.file || "")}</p>
      ${(P.dests || [])
        .map(
          (d) => `<div class="dest-progress"><code>${esc(d.root)}</code> ${meter(d.written, d.total || 1)}
          <span class="muted">${gb(d.written)}/${gb(d.total || 0)} GB · ${d.mb_s} MB/s${d.eta_s ? " · " + t("ingest.eta", { s: d.eta_s }) : ""}</span></div>`
        )
        .join("")}</section>`;
  }

  function historyCard() {
    const H = X.history || [];
    if (!H.length) return "";
    return `<section class="card"><h2 class="card-title">${esc(t("ingest.history"))}</h2><table class="table"><tbody>${H.map(
      (h) => `<tr><td>${esc(h.session)}</td><td>${esc(h.card)} → ${esc(h.project)}/${esc(h.label)}</td><td class="num">${h.files} · ${h.gb} GB</td><td>${h.safe ? `<span class="pill ok">${esc(t("ingest.safe_short"))}</span>` : `<span class="pill unresolved">${esc(t("ingest.check"))}</span>`}</td></tr>`
    ).join("")}</tbody></table></section>`;
  }

  // ---------------- Export ----------------

  HS.screens.export = {
    canGo: (S) => !!S.project,
    async load() {
      X.presets = await call("export_presets");
      X.settings = await call("settings");
      if (!X.exp.preset) X.exp.preset = X.settings.export_preset;
      await planExport();
      X.jobs = await call("jobs_status");
    },
    render() {
      const E = X.exp;
      const P = E.plan || { folders: [], problems: [] };
      view().innerHTML = `${head(t("export.eyebrow"), U().S.project.name, t("export.sub"))}
        <section class="card"><div class="field"><span class="label">${esc(t("export.preset"))}</span><div class="segs" id="presets">${X.presets
          .map((p) => `<button class="seg ${p.id === E.preset ? "on" : ""}" data-p="${esc(p.id)}">${esc(p.name)}</button>`)
          .join("")}</div></div>
        ${P.folders.length ? `<div class="field"><span class="label">${esc(t("export.folders"))}</span><div class="checks">${P.folders
          .map((f) => `<label class="toggle"><input type="checkbox" data-f="${esc(f.key)}" ${E.folders.includes(f.key) ? "checked" : ""}><span>${esc(f.folder)} <span class="muted">(${f.clips})</span></span></label>`)
          .join("")}</div><span class="hint">${esc(t("export.folders_hint"))}</span></div>` : ""}
        <div class="field"><span class="label">${esc(t("export.dest"))}</span><div class="inline"><code>${esc(E.dest || t("export.dest_default"))}</code>
          <button class="btn small quiet" id="ex-dest">${esc(t("export.choose"))}</button></div></div>
        <p>${esc(t("export.plan", { clips: P.clips || 0, gb: P.gb || 0 }))}</p>
        ${(P.space ? [t("export.p_space", { path: P.space.path, need: P.space.need_gb, free: P.space.free_gb, choose: t("export.choose") })] : P.problems || [])
          .map((x) => `<p class="warn">${esc(x)}</p>`).join("")}
        <div class="actions"><button class="btn primary" id="ex-go" ${P.clips && !(P.problems || []).length ? "" : "disabled"}>${esc(t("export.go"))}</button></div></section>
        ${queueCard("export")}`;
      $$("#presets .seg").forEach((b) => (b.onclick = async () => ((E.preset = b.dataset.p), await planExport(), HS.screens.export.render())));
      $$("[data-f]").forEach((c) => (c.onchange = async () => {
        E.folders = $$("[data-f]").filter((x) => x.checked).map((x) => x.dataset.f);
        await planExport();
        HS.screens.export.render();
      }));
      $("#ex-dest").onclick = async () => {
        const d = await call("pick_dest");
        if (d) {
          E.dest = d;
          await planExport();
          HS.screens.export.render();
        }
      };
      $("#ex-go").onclick = async () => {
        const r = await call("start_export", { preset: E.preset, folders: E.folders, dest: E.dest || null });
        U().toast(t("export.queued", { n: r.queued }));
        X.jobs = await call("jobs_status");
        HS.screens.export.render();
      };
      bindQueue();
    },
  };

  async function planExport() {
    try {
      X.exp.plan = await HS.call("export_plan", { preset: X.exp.preset, folders: X.exp.folders, dest: X.exp.dest || null });
    } catch (e) {
      X.exp.plan = { clips: 0, gb: 0, problems: [e.message], folders: [] };
    }
  }

  function queueCard(kind) {
    const J = X.jobs;
    if (!J) return "";
    const rows = J.recent.filter((j) => !kind || j.kind === kind).slice(0, 25);
    const c = J.counts[kind] || {};
    return `<section class="card"><h2 class="card-title">${esc(t("jobs.title_" + kind))}</h2>
      <p class="muted">${["queued", "running", "done", "failed"].map((s) => `${esc(t("jobs." + s))}: ${c[s] || 0}`).join(" · ")}${J.paused ? " · " + esc(t("jobs.paused")) : ""}</p>
      <div class="actions"><button class="btn small" id="q-toggle">${esc(J.paused ? t("jobs.resume") : t("jobs.pause"))}</button>
      ${c.failed ? `<button class="btn small quiet" id="q-retry">${esc(t("jobs.retry"))}</button>` : ""}</div>
      ${rows.length ? `<table class="table"><tbody>${rows
        .map((j) => `<tr><td>${esc(j.rel)}</td><td>${esc(t("jobs." + j.status))}</td><td class="num">${j.status === "running" ? Math.round(100 * j.progress) + "%" : ""}</td><td class="muted">${esc(j.error || "")}</td></tr>`)
        .join("")}</tbody></table>` : ""}</section>`;
  }

  function bindQueue() {
    const tg = $("#q-toggle");
    if (tg) tg.onclick = async () => ((X.jobs = await call(X.jobs.paused ? "jobs_resume" : "jobs_pause")), U().render());
    const rt = $("#q-retry");
    if (rt) rt.onclick = async () => ((X.jobs = await call("jobs_retry")), U().render());
  }

  // ---------------- Drives ----------------

  HS.screens.drives = {
    canGo: () => true,
    async load() {
      X.drives = await call("drives");
      X.jobs = await call("jobs_status");
    },
    render() {
      view().innerHTML = `${head(t("drives.eyebrow"), t("drives.title"), t("drives.sub"))}
        <section class="card wide"><table class="table drives"><thead><tr><th>${esc(t("drives.drive"))}</th><th>${esc(t("drives.space"))}</th>
          <th class="num">${esc(t("drives.free"))}</th><th class="num">${esc(t("drives.after"))}</th><th>${esc(t("drives.status"))}</th></tr></thead><tbody>${X.drives
          .map(
            (d) => `<tr><td><strong>${esc(d.name)}</strong>${d.is_card ? ` <span class="pill">${esc(t("drives.card"))}</span>` : ""}
            ${d.projects.map((p) => `<div class="muted small">${esc(p.name)}: ${gb(p.footage_bytes)} GB${p.proxies_bytes ? ` + ${gb(p.proxies_bytes)} GB proxies` : ""}</div>`).join("")}</td>
            <td>${meter(d.used, d.total, d.status)} <span class="muted small">${gb(d.used)} / ${gb(d.total)} GB</span></td>
            <td class="num">${gb(d.free)} GB</td><td class="num">${d.planned ? gb(d.free_after) + " GB" : "–"}</td>
            <td><span class="pill ${d.status}">${esc(t("drives." + d.status))}</span> ${d.status === "ok" ? "" : `<span class="muted small drive-left">${esc(t("drives.left", { gb: (d.free_after / 1e9).toFixed(1), pct: d.total ? Math.round((100 * d.free_after) / d.total) : 0 }))}</span>`}</td></tr>`
          )
          .join("")}</tbody></table>
          <p class="hint">${esc(t("drives.hint"))}</p></section>
        ${queueCard("proxy")}`;
      bindQueue();
    },
  };

  // ---------------- Accuracy Lab ----------------

  HS.screens.lab = {
    canGo: () => true,
    async load() {
      X.lab.reports = await call("lab_reports");
    },
    render() {
      const L = X.lab;
      const S = U().S;
      view().innerHTML = `${head(t("lab.eyebrow"), t("lab.title"), t("lab.sub"))}
        <section class="card"><h2 class="card-title">${esc(t("lab.run"))}</h2><p class="hint">${esc(t("lab.run_hint"))}</p>
          <div class="actions"><button class="btn primary" id="lab-run" ${S.project ? "" : "disabled"}>${esc(S.project ? t("lab.run_on", { name: S.project.name }) : t("lab.open_first"))}</button></div></section>
        <section class="card wide"><h2 class="card-title">${esc(t("lab.reports"))}</h2>${
          L.reports.length
            ? `<table class="table"><thead><tr><th>${esc(t("lab.report"))}</th><th class="num">${esc(t("lab.acc"))}</th><th class="num">F1</th><th class="num">ARI</th><th class="num">${esc(t("lab.folders"))}</th><th class="num">${esc(t("lab.cost"))}</th></tr></thead><tbody>${L.reports
                .map((r) => `<tr class="clickable" data-r="${esc(r.name)}"><td>${esc(r.name)}</td><td class="num">${pct(r.accuracy)}</td><td class="num">${r.f1.toFixed(3)}</td><td class="num">${r.ari.toFixed(3)}</td><td class="num">${esc(r.folders)}</td><td class="num">$${(r.cost || 0).toFixed(2)}</td></tr>`)
                .join("")}</tbody></table>`
            : `<p class="muted">${esc(t("lab.none"))}</p>`
        }</section>
        ${L.open ? `<section class="card wide"><h2 class="card-title">${esc(L.open)}</h2><pre class="report">${esc(L.text)}</pre></section>` : ""}`;
      $("#lab-run").onclick = async () => {
        if (!(await U().ask(t("lab.confirm")))) return;
        await call("start_eval", {});
        U().toast(t("lab.started"));
      };
      $$("[data-r]").forEach((tr) => (tr.onclick = async () => {
        L.open = tr.dataset.r;
        L.text = await call("lab_report", { name: L.open });
        HS.screens.lab.render();
      }));
    },
  };

  // ---------------- Settings ----------------

  HS.screens.settings = {
    canGo: () => true,
    async load() {
      X.settings = await call("settings");
    },
    render() {
      const s = X.settings;
      const sel = (id, opts, val) => `<select id="${id}">${opts.map((o) => `<option value="${esc(o.id)}" ${String(o.id) === String(val) ? "selected" : ""}>${esc(o.label || o.name)}</option>`).join("")}</select>`;
      view().innerHTML = `${head(t("set.eyebrow"), t("set.title"))}
        <section class="card"><h2 class="card-title">${esc(t("set.general"))}</h2>
          <div class="field"><span class="label">${esc(t("set.language"))}</span>${sel("s-language", [{ id: "en", label: "English" }, { id: "el", label: "Ελληνικά" }], HS.lang)}</div>
          </section>
        <section class="card"><h2 class="card-title">${esc(t("set.sorting"))}</h2>
          <div class="field"><span class="label">${esc(t("set.density"))}</span>${sel("s-density", [{ id: 1, label: t("set.every", { s: 1 }) }, { id: 2, label: t("set.every", { s: 2 }) }, { id: 4, label: t("set.every", { s: 4 }) }], s.frame_interval)}</div>
          <label class="toggle"><input type="checkbox" id="s-sound" ${s.use_sound ? "checked" : ""}> ${esc(t("set.sound"))}</label>
          <label class="field"><span class="label">${esc(t("set.rename"))}</span><input id="s-rename" value="${esc(s.rename_pattern)}" placeholder="{num}_{n:03d}_{name}"><span class="hint">${esc(t("set.rename_hint"))}</span></label>
          <p class="hint">${esc(t("set.offsets_hint"))}</p></section>
        <section class="card"><h2 class="card-title">${esc(t("set.ingest"))}</h2>
          <div class="field"><span class="label">${esc(t("set.hash"))}</span><span>xxHash64 (ASC MHL)</span></div>
          <div class="field"><span class="label">${esc(t("set.dests"))}</span>${destList(s.destinations || [], "s-dest")}</div>
          <label class="toggle"><input type="checkbox" id="s-proxies" ${s.make_proxies ? "checked" : ""}> ${esc(t("set.make_proxies"))}</label>
          <div class="field"><span class="label">${esc(t("set.proxy_preset"))}</span>${sel("s-proxy", s.proxy_presets, s.proxy_preset)}</div>
          <div class="field"><span class="label">${esc(t("set.export_preset"))}</span>${sel("s-export", s.export_presets, s.export_preset)}<span class="hint">${esc(t("set.presets_hint"))}</span></div></section>
        <section class="card"><h2 class="card-title">${esc(t("set.drives"))}</h2>
          <div class="inline3"><label class="field"><span class="label">${esc(t("set.warn_gb"))}</span><input id="s-wgb" type="number" min="1" value="${s.warn_gb}"></label>
          <label class="field"><span class="label">${esc(t("set.warn_pct"))}</span><input id="s-wpct" type="number" min="1" max="90" value="${s.warn_percent}"></label>
          <label class="field"><span class="label">${esc(t("set.crit_gb"))}</span><input id="s-cgb" type="number" min="1" value="${s.critical_gb}"></label></div></section>`;
      const save = async (changes) => {
        X.settings = await call("save_settings", { changes });
        U().toast(t("set.saved"));
      };
      $("#s-language").onchange = async (e) => {
        HS.setLang(e.target.value);
        await save({ language: e.target.value });
        U().render();
      };
      $("#s-density").onchange = (e) => save({ frame_interval: +e.target.value });
      $("#s-sound").onchange = (e) => save({ use_sound: e.target.checked });
      $("#s-rename").onchange = (e) => save({ rename_pattern: e.target.value.trim() });
      $("#s-proxies").onchange = (e) => save({ make_proxies: e.target.checked });
      $("#s-proxy").onchange = (e) => save({ proxy_preset: e.target.value });
      $("#s-export").onchange = (e) => save({ export_preset: e.target.value });
      $("#s-wgb").onchange = (e) => save({ warn_gb: +e.target.value });
      $("#s-wpct").onchange = (e) => save({ warn_percent: +e.target.value });
      $("#s-cgb").onchange = (e) => save({ critical_gb: +e.target.value });
      bindDestList("s-dest", s.destinations || [], async (list) => {
        X.settings = await call("save_settings", { changes: { destinations: list } });
        HS.screens.settings.render();
      });
    },
  };

  // ---------------- Features, Help, About ----------------

  HS.screens.features = {
    canGo: () => true,
    render() {
      const items = ["ingest", "proxies", "sort", "review", "organize", "drives", "export", "lab"];
      view().innerHTML = `${head(t("feat.eyebrow"), t("feat.title"), t("feat.sub"))}
        <section class="features">${items
          .map((k, i) => `<article class="feature"><span class="fnum">${String(i + 1).padStart(2, "0")}</span><h2>${esc(t("feat." + k))}</h2><p>${esc(t("feat." + k + "_text"))}</p></article>`)
          .join("")}</section>`;
    },
  };

  HS.screens.help = {
    canGo: () => true,
    render() {
      const faq = [1, 2, 3, 4, 5, 6];
      view().innerHTML = `${head(t("help.eyebrow"), t("help.title"))}
        <section class="card"><h2 class="card-title">${esc(t("help.faq"))}</h2>${faq
          .map((n) => `<details class="faq"><summary>${esc(t("help.q" + n))}</summary><p>${esc(t("help.a" + n))}</p></details>`)
          .join("")}</section>
        <section class="card"><h2 class="card-title">${esc(t("help.support"))}</h2>
          <div class="actions"><button class="btn" id="h-mail">${esc(t("help.contact"))}</button>
          <button class="btn" id="h-bug">${esc(t("help.bug"))}</button>
          <button class="btn quiet" id="h-diag">${esc(t("help.diag"))}</button></div>
          <p class="hint">${esc(t("help.diag_hint"))}</p></section>`;
      $("#h-mail").onclick = () => call("open_link", { kind: "mail" });
      $("#h-bug").onclick = () => call("open_link", { kind: "issues" });
      $("#h-diag").onclick = async () => {
        const r = await call("export_diagnostics");
        U().toast(t("help.diag_done", { path: r.path }));
      };
    },
  };

  HS.screens.about = {
    canGo: () => true,
    render() {
      const v = (U().S.info || {}).version || "";
      view().innerHTML = `${head(t("about.eyebrow"), "HyperShutter", t("about.version", { v }))}
        <section class="card"><img class="hero-mark" src="/ui/img/mark.svg" alt=""><p>${esc(t("about.text"))}</p><p class="muted">${esc(t("about.credits"))}</p></section>
        <section class="card"><h2 class="card-title">${esc(t("about.licenses"))}</h2><ul class="flag-list">${[
          "pywebview — BSD-3-Clause", "FFmpeg — LGPL/GPL (separate install)", "NumPy, SciPy — BSD-3-Clause",
          "OpenCV — Apache-2.0", "Pillow — MIT-CMU", "xxHash — BSD-2-Clause", "PyYAML — MIT",
        ].map((x) => `<li>${esc(x)}</li>`).join("")}</ul><p class="hint">${esc(t("about.licenses_more"))}</p></section>`;
    },
  };

  // ---------------- sidebar status and live events ----------------

  async function sidebar() {
    try {
      X.jobs = await HS.call("jobs_status");
      if (!sidebar.n || sidebar.n % 5 === 0) X.drives = await HS.call("drives");
      sidebar.n = (sidebar.n || 0) + 1;
    } catch (e) {
      return;
    }
    const J = X.jobs;
    const lines = [];
    for (const kind of ["proxy", "export"]) {
      const c = J.counts[kind] || {};
      const left = (c.queued || 0) + (c.running || 0);
      if (left) lines.push(`<div class="job-line"><span class="dot run"></span>${esc(t("jobs.left_" + kind, { n: left }))}${J.paused ? " · " + esc(t("jobs.paused")) : ""}</div>`);
    }
    if (X.ingest && X.ingest.progress && !X.ingest.report) lines.push(`<div class="job-line"><span class="dot run"></span>${esc(t("jobs.ingest"))}</div>`);
    const warn = (X.drives || []).filter((d) => !d.is_card && (d.status === "critical" || (d.status === "warn" && d.projects.length)));
    for (const d of warn.slice(0, 3)) lines.push(`<div class="job-line"><span class="dot ${d.status}"></span>${esc(d.name)}: ${gb(d.free)} GB</div>`);
    const el = document.getElementById("side-status");
    if (el) el.innerHTML = lines.join("");
    if (U().S.view === "drives" && sidebar.n % 5 === 1) HS.screens.drives.render();
  }
  setInterval(sidebar, 3000);
  setTimeout(sidebar, 500);

  HS.on((ev) => {
    if (ev.type === "ingest") {
      X.ingest = { progress: ev };
      if (U().S.view === "ingest") HS.screens.ingest.render();
    } else if (ev.type === "ingest_done") {
      X.ingest = { report: ev.report, card_path: ev.card_path };
      HS.call("ingest_history").then((h) => ((X.history = h), U().S.view === "ingest" && HS.screens.ingest.render()));
      U().toast(ev.report.safe ? t("ingest.safe") : t("ingest.not_safe"), !ev.report.safe);
    } else if (ev.type === "ingest_error") {
      X.ingest = { error: ev.error };
      if (U().S.view === "ingest") HS.screens.ingest.render();
    } else if (ev.type === "job_done" && ev.name === "eval") {
      U().toast(t("lab.done", { acc: pct(ev.result.accuracy) }));
      HS.screens.lab.load().then(() => U().S.view === "lab" && HS.screens.lab.render());
    }
  });
})();
