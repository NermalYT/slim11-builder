"use strict";

const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || sessionStorage.getItem("slim11-token") || "";
try { sessionStorage.setItem("slim11-token", TOKEN); } catch (_) { /* storage may be blocked */ }
history.replaceState(null, "", location.pathname);

const PAGES = ["welcome", "source", "components", "settings", "build"];
const $ = (sel) => document.querySelector(sel);
const state = {
  page: "welcome", previous: "welcome", status: null, catalog: null,
  preset: null, editions: [], edition: null,
  selection: { apps: [], files: [], tweaks: [], extra_packages: [] },
  logLength: 0, polling: null, job: "idle",
};

async function api(path, body) {
  const opts = { headers: { "X-Slim11-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

const gib = (n) => (n / 1024 ** 3).toFixed(2) + " GiB";

/* ---------- navigation ---------- */

function show(page) {
  if (page !== "about") state.previous = page;
  state.page = page;
  document.querySelectorAll("[data-page]").forEach((s) => (s.hidden = s.dataset.page !== page));
  const idx = PAGES.indexOf(page);
  document.querySelectorAll("#steps li").forEach((li, i) => {
    li.classList.toggle("active", li.dataset.step === page);
    li.classList.toggle("done", idx > i || (page === "build" && state.job === "done" && i === 4));
  });
  if (page === "settings") renderSummary();
  updateActions();
  $("#main").scrollTop = 0;
  window.scrollTo(0, 0);
}

function updateActions() {
  const back = $("#back"), next = $("#next");
  const idx = PAGES.indexOf(state.page);
  back.hidden = false;
  next.className = "";
  if (state.page === "about") {
    back.textContent = "Back"; back.disabled = false; next.hidden = true; return;
  }
  next.hidden = false;
  back.textContent = "Back";
  back.disabled = idx === 0 || state.job === "running";
  if (state.page === "build") {
    if (state.job === "running") { next.textContent = "Cancel build"; next.className = "danger"; next.disabled = false; }
    else if (state.job === "done") { next.textContent = "Build another"; next.disabled = false; }
    else { next.textContent = state.job === "idle" ? "Start build" : "Try again"; next.disabled = false; }
    return;
  }
  next.textContent = "Next";
  next.disabled = !canLeave(state.page);
}

function canLeave(page) {
  if (page === "welcome") return !!state.preset;
  if (page === "source") return state.edition != null;
  if (page === "settings") return $("#output").value.trim().length > 0;
  return true;
}

$("#back").addEventListener("click", () => {
  if (state.page === "about") return show(state.previous);
  const idx = PAGES.indexOf(state.page);
  if (idx > 0) show(PAGES[idx - 1]);
});

$("#next").addEventListener("click", async () => {
  if (state.page === "build") {
    if (state.job === "running") { await api("/api/cancel", {}); return; }
    if (state.job === "done") { state.job = "idle"; resetBuildPage(); return show("welcome"); }
    return startBuild();
  }
  if (state.page === "settings" && !(await confirmOverwrite())) return;
  const idx = PAGES.indexOf(state.page);
  show(PAGES[idx + 1]);
});

document.querySelector("[data-goto=about]").addEventListener("click", () => show("about"));

/* ---------- welcome ---------- */

function renderPresets() {
  const box = $("#presets");
  box.replaceChildren(...state.catalog.presets.map((p) => el("button", {
    type: "button", class: "card" + (state.preset === p.id ? " selected" : ""),
    onclick: () => choosePreset(p),
  }, el("strong", {}, p.title), el("span", {}, p.description))));
}

function choosePreset(p) {
  state.preset = p.id;
  state.selection = JSON.parse(JSON.stringify(p.selection));
  renderPresets();
  renderComponents();
  updateActions();
}

/* ---------- source ---------- */

$("#source").addEventListener("input", () => { state.edition = null; state.editions = []; renderEditions(); updateActions(); });
$("#source").addEventListener("keydown", (e) => { if (e.key === "Enter") inspect(); });
$("#inspect").addEventListener("click", inspect);

async function inspect() {
  const iso = $("#source").value.trim();
  const status = $("#source-status");
  if (!iso) return;
  status.className = "status"; status.textContent = "Reading the image…";
  $("#inspect").disabled = true;
  try {
    const { editions } = await api("/api/inspect", { iso });
    state.editions = editions;
    state.edition = editions.find((e) => /pro$/i.test(e.name))?.index ?? editions[0]?.index ?? null;
    status.textContent = `${editions.length} edition${editions.length === 1 ? "" : "s"} found.`;
    if (!$("#output").value) $("#output").value = suggestOutput(iso);
  } catch (err) {
    state.editions = []; state.edition = null;
    status.className = "status error"; status.textContent = err.message;
  } finally {
    $("#inspect").disabled = false;
    renderEditions(); updateActions();
  }
}

function suggestOutput(iso) {
  const sep = state.status?.sep || "/";
  const cut = Math.max(iso.lastIndexOf("/"), iso.lastIndexOf("\\"));
  const dir = cut >= 0 ? iso.slice(0, cut) : "";
  const base = (cut >= 0 ? iso.slice(cut + 1) : iso).replace(/\.iso$/i, "");
  return (dir ? dir + sep : "") + base + "-slim11.iso";
}

function renderEditions() {
  $("#editions-wrap").hidden = state.editions.length === 0;
  $("#editions").replaceChildren(...state.editions.map((e) => el("label", { class: "item" },
    el("input", { type: "radio", name: "edition", value: e.index, checked: e.index === state.edition,
      onchange: () => { state.edition = e.index; updateActions(); } }),
    el("div", {}, el("strong", {}, e.display_name || e.name),
      el("small", {}, [e.architecture, e.build && "build " + e.build, e.language, e.size_bytes && gib(e.size_bytes) + " installed"].filter(Boolean).join(" · "))))));
}

/* ---------- components ---------- */

function toggle(kind, id, on) {
  const list = state.selection[kind];
  const i = list.indexOf(id);
  if (on && i < 0) list.push(id);
  if (!on && i >= 0) list.splice(i, 1);
}

function renderComponents() {
  if (!state.catalog) return;
  const c = state.catalog;
  const row = (kind, item, extra) => el("label", { class: "item" },
    el("input", { type: "checkbox", checked: state.selection[kind].includes(item.id),
      onchange: (ev) => toggle(kind, item.id, ev.target.checked) }),
    el("div", {}, el("strong", {}, item.title), el("small", {}, item.description), extra));
  $("#apps").replaceChildren(...c.apps.map((a) => row("apps", a,
    el("details", {}, el("summary", {}, `${a.packages.length} packages`), a.packages.join(", ")))));
  $("#files").replaceChildren(...c.files.map((f) => row("files", f, f.risky ? el("span", { class: "risky" }, "Can break apps") : null)));
  $("#tweaks").replaceChildren(...c.tweaks.map((t) => row("tweaks", t)));
  $("#extra").value = state.selection.extra_packages.join("\n");
}

$("#extra").addEventListener("input", (e) => {
  state.selection.extra_packages = e.target.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
});

/* ---------- settings ---------- */

$("#output").addEventListener("input", updateActions);

function renderSummary() {
  const s = state.selection, c = state.catalog;
  const edition = state.editions.find((e) => e.index === state.edition);
  const names = (kind) => c[kind].filter((x) => s[kind].includes(x.id)).map((x) => x.title);
  const parts = [
    ["Edition", edition ? `${edition.name} (${edition.architecture})` : "—"],
    ["Apps", names("apps").join(", ") || "none"],
    ["Files", names("files").join(", ") || "none"],
    ["Settings", names("tweaks").join(", ") || "none"],
  ];
  if (s.extra_packages.length) parts.push(["Extra apps", s.extra_packages.join(", ")]);
  $("#summary").replaceChildren(...parts.map(([k, v]) => el("div", {}, el("strong", {}, k + ": "), v)));
}

async function confirmOverwrite() {
  const out = $("#output").value.trim();
  if (!/\.iso$/i.test(out)) $("#output").value = out + ".iso";
  try {
    const { exists } = await api("/api/exists", { path: $("#output").value.trim() });
    return !exists || confirm("That file already exists. Replace it when the build finishes?");
  } catch (_) { return true; }
}

/* ---------- build ---------- */

function resetBuildPage() {
  $("#build-title").textContent = "Ready to build";
  $("#bar").style.width = "0";
  $("#build-status").textContent = "";
  $("#build-status").className = "status";
  $("#log").textContent = "";
  state.logLength = 0;
}

async function startBuild() {
  resetBuildPage();
  try {
    await api("/api/build", {
      source: $("#source").value.trim(), edition: state.edition, output: $("#output").value.trim(),
      selection: state.selection, format: document.querySelector("input[name=format]:checked").value,
      compact: $("#compact").checked, workDir: $("#workdir").value.trim() || null,
    });
    state.job = "running";
    $("#build-title").textContent = "Building…";
    updateActions();
    poll();
  } catch (err) {
    $("#build-status").className = "status error";
    $("#build-status").textContent = err.message;
  }
}

const STAGE_TEXT = {
  prepare: "Checking tools and space", extract: "Copying installation media", export: "Extracting the chosen edition",
  modify: "Removing files and adding setup scripts", compress: "Compressing the image (the longest step)", iso: "Writing the ISO", done: "Finished",
};

async function poll() {
  clearTimeout(state.polling);
  let job;
  try { job = await api("/api/job?since=" + state.logLength); }
  catch (_) { state.polling = setTimeout(poll, 2000); return; }
  if (job.log.length) {
    const log = $("#log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.append(job.log.join("\n") + "\n");
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  state.logLength = job.logLength;
  $("#bar").style.width = (job.progress * 100).toFixed(1) + "%";
  const mins = Math.floor(job.elapsed / 60), secs = Math.floor(job.elapsed % 60);
  const status = $("#build-status");
  if (job.state === "running") {
    status.className = "status";
    status.textContent = `${STAGE_TEXT[job.stage] || job.stage} · ${Math.round(job.progress * 100)}% · ${mins}:${String(secs).padStart(2, "0")}`;
    state.polling = setTimeout(poll, 700);
  } else {
    state.job = job.state;
    if (job.state === "done") {
      $("#build-title").textContent = "Your ISO is ready";
      status.className = "status ok"; status.textContent = job.output;
    } else if (job.state === "cancelled") {
      $("#build-title").textContent = "Build cancelled";
      status.className = "status"; status.textContent = "Temporary files were removed.";
    } else if (job.state === "failed") {
      $("#build-title").textContent = "Build failed";
      status.className = "status error"; status.textContent = job.error;
    }
    show("build");
  }
}

/* ---------- file picker ---------- */

const picker = { target: null, mode: "open", path: "", selected: null };

document.querySelectorAll("[data-browse]").forEach((b) => b.addEventListener("click", () => {
  const target = b.dataset.browse;
  openPicker(target, target === "source" ? "open" : target === "output" ? "save" : "folder");
}));

async function openPicker(target, mode) {
  picker.target = target; picker.mode = mode; picker.selected = null;
  $("#picker-title").textContent = mode === "open" ? "Choose a Windows ISO" : mode === "save" ? "Save the new ISO" : "Choose a folder";
  $("#picker-name-row").hidden = mode !== "save";
  const current = $("#" + target).value.trim();
  if (mode === "save") {
    const cut = Math.max(current.lastIndexOf("/"), current.lastIndexOf("\\"));
    $("#picker-name").value = cut >= 0 ? current.slice(cut + 1) : (current || "windows-slim11.iso");
  }
  await loadDir(current || state.status?.home);
  $("#picker").showModal();
}

async function loadDir(path) {
  let data;
  try { data = await api("/api/browse", { path }); } catch (err) { alert(err.message); return; }
  picker.path = data.path; picker.sep = data.sep;
  $("#picker-path").value = data.path;
  $("#picker-roots").replaceChildren(...data.roots.map((r) => el("option", { value: r, selected: r === data.path }, r)));
  const items = [];
  if (data.parent) items.push(el("li", { ondblclick: () => loadDir(data.parent), onclick: () => loadDir(data.parent) }, "⬑ ..", ""));
  for (const e of data.entries) {
    if (picker.mode === "folder" && !e.dir) continue;
    const li = el("li", {}, (e.dir ? "📁 " : "💿 ") + e.name, e.dir ? null : el("span", { class: "size" }, gib(e.size)));
    li.addEventListener("click", () => {
      if (e.dir) return loadDir(e.path);
      document.querySelectorAll("#picker-list li").forEach((x) => x.classList.remove("sel"));
      li.classList.add("sel"); picker.selected = e.path;
      if (picker.mode === "save") $("#picker-name").value = e.name;
    });
    li.addEventListener("dblclick", () => { if (!e.dir) { picker.selected = e.path; finishPicker(); } });
    items.push(li);
  }
  $("#picker-list").replaceChildren(...items);
}

$("#picker-roots").addEventListener("change", (e) => loadDir(e.target.value));
$("#picker-path").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); loadDir(e.target.value); } });
$("#picker-ok").addEventListener("click", (e) => { e.preventDefault(); finishPicker(); });

function finishPicker() {
  let value = null;
  const join = (dir, name) => dir.endsWith(picker.sep) ? dir + name : dir + picker.sep + name;
  if (picker.mode === "open") value = picker.selected;
  else if (picker.mode === "save") { const name = $("#picker-name").value.trim(); if (name) value = join(picker.path, name); }
  else value = picker.path;
  if (!value) return;
  const input = $("#" + picker.target);
  input.value = value;
  input.dispatchEvent(new Event("input"));
  $("#picker").close();
  if (picker.target === "source") inspect();
}

/* ---------- start ---------- */

(async function init() {
  try {
    const [status, catalog] = await Promise.all([api("/api/status"), api("/api/catalog")]);
    state.status = status; state.catalog = catalog;
    $("#version").textContent = status.version;
    $("#host").textContent = `${status.platform} · Python ${status.python}`;
    if (!status.wimlib) {
      const b = $("#tool-banner");
      b.hidden = false;
      b.textContent = "wimlib was not found, so builds cannot run yet. " + status.hint;
    }
    renderPresets();
    renderComponents();
    const job = await api("/api/job?since=0");
    if (job.state !== "idle") { state.job = job.state; show("build"); poll(); return; }
  } catch (err) {
    document.body.replaceChildren(el("p", { class: "status error", style: "padding:24px" },
      "Could not reach the Slim11 builder. Start it again with `slim11` and open the link it prints. (" + err.message + ")"));
    return;
  }
  show("welcome");
})();
