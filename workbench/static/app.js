const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="workbench-token"]').content;
const state = { files: [], sample: false, jobs: [], selected: new Set(), filter: "all", settings: {} };
const form = $("#jobForm");
const files = $("#files");

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "X-Workbench": token, ...options.headers } });
  let body;
  try { body = await response.json(); } catch { throw new Error("工作台未返回有效响应。"); }
  if (!response.ok) throw new Error(body.error || "请求失败，请重试。");
  return body;
}

function post(path, data) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

function message(node, text = "", ok = false) {
  node.textContent = text;
  node.classList.toggle("ok", ok);
}

function tab(showFiles) {
  $("#linksPanel").hidden = showFiles;
  $("#filesPanel").hidden = !showFiles;
  for (const [button, open] of [[$("#linkTab"), !showFiles], [$("#fileTab"), showFiles]]) {
    button.classList.toggle("active", open);
    button.setAttribute("aria-pressed", String(open));
  }
}
$("#linkTab").onclick = () => tab(false);
$("#fileTab").onclick = () => tab(true);
$("#drop").onclick = () => files.click();
$("#drop").ondragover = (event) => { event.preventDefault(); $("#drop").classList.add("drag"); };
$("#drop").ondragleave = () => $("#drop").classList.remove("drag");
$("#drop").ondrop = (event) => {
  event.preventDefault();
  $("#drop").classList.remove("drag");
  addFiles(event.dataTransfer.files);
};

function addFiles(incoming) {
  for (const file of incoming) {
    if (!state.files.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) state.files.push(file);
  }
  renderInput();
}

files.onchange = () => { addFiles(files.files); files.value = ""; };
$("#links").oninput = renderInput;
$("#captionY").oninput = () => { $("#captionOutput").textContent = $("#captionY").value + "%"; };
$("#addSample").onclick = () => {
  state.sample = true;
  renderInput();
  $("#create").scrollIntoView({ block: "nearest" });
};

function links() {
  return [...new Set($("#links").value.trim().split(/\r?\n/).map((x) => x.trim()).filter(Boolean))];
}

function renderInput() {
  const nodes = state.files.map((file, i) => [file.name, () => { state.files.splice(i, 1); renderInput(); }]);
  if (state.sample) nodes.push(["二虎示例 · 原片", () => { state.sample = false; renderInput(); }]);
  const selected = $("#selected");
  selected.replaceChildren(...nodes.map(([name, remove]) => {
    const row = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = name;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "×";
    button.setAttribute("aria-label", "移除 " + name);
    button.onclick = remove;
    row.append(label, button);
    return row;
  }));
  selected.hidden = !nodes.length;
  const linkCount = links().length;
  const count = linkCount + nodes.length;
  $("#inputCount").textContent = count + " / 30 条";
  $("#submit").disabled = !count || count > 30 || state.submitting;
  $("#downloadSource").disabled = !linkCount || linkCount > 30 || state.submitting;
}

form.onsubmit = async (event) => {
  event.preventDefault();
  if (state.submitting) return;
  const sourceOnly = event.submitter?.id === "downloadSource";
  state.submitting = true;
  form.inert = true;
  renderInput();
  message($("#formMessage"), "正在提交…", true);
  const body = new FormData();
  body.set("links", links().join("\n"));
  body.set("source_only", sourceOnly ? "1" : "0");
  body.set("sample", !sourceOnly && state.sample ? "1" : "0");
  body.set("options", JSON.stringify({
    provider: $("#provider").value, caption_mode: $("#captionMode").value,
    caption_y: +$("#captionY").value, note: $("#note").value.trim(),
    watermark: $("#watermark").checked, lipsync: $("#lipsync").checked,
  }));
  if (!sourceOnly) {
    for (const file of state.files) body.append("files", file);
  }
  try {
    const result = await api("/api/jobs", { method: "POST", body });
    $("#links").value = "";
    if (!sourceOnly) {
      state.files = [];
      state.sample = false;
    }
    setFilter("all");
    message($("#formMessage"), result.ids.length + " 条视频已加入队列", true);
    await refresh();
    $("#queue").scrollIntoView({ block: "nearest" });
  } catch (error) {
    message($("#formMessage"), error.message);
  } finally {
    state.submitting = false;
    form.inert = false;
    renderInput();
  }
};

function cell(text = "") {
  const node = document.createElement("td");
  node.textContent = text;
  return node;
}

function jobRow(job) {
  const row = document.createElement("tr");
  const checkboxCell = cell();
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.selected.has(job.id);
  checkbox.disabled = job.state !== "done";
  checkbox.setAttribute("aria-label", "选择 " + job.title);
  checkbox.onchange = () => {
    if (checkbox.checked) state.selected.add(job.id); else state.selected.delete(job.id);
    renderJobs();
  };
  checkboxCell.append(checkbox);

  const name = cell();
  const title = document.createElement("div");
  title.className = "job-title";
  title.textContent = job.title;
  name.append(title);
  if (job.message) {
    const detail = document.createElement("div");
    detail.className = "job-message";
    detail.textContent = job.message;
    if (job.state === "queued" && job.retry_at) {
      const next = new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"
      }).format(job.retry_at * 1000);
      detail.textContent += " 预计 " + next + "（北京时间）。";
    }
    name.append(detail);
  }

  const status = cell(job.stage);
  status.className = "state " + job.state;

  const progressCell = cell();
  const progress = document.createElement("div");
  progress.className = "progress";
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.value = job.percent;
  bar.setAttribute("aria-label", job.title + " 处理进度");
  progress.append(bar, job.percent + "%");
  progressCell.append(progress);

  const linksCell = cell();
  const actions = document.createElement("div");
  actions.className = "file-actions";
  const base = "/api/jobs/" + job.id;
  const downloadLink = (path, label) => {
    const link = document.createElement("a");
    link.href = base + path;
    link.download = "";
    link.textContent = label;
    actions.append(link);
  };
  if (job.source_ready) downloadLink("/source", "原片");
  if (job.state === "done" && !job.source_only) {
    const preview = document.createElement("button");
    preview.textContent = "预览";
    preview.onclick = () => play(base + "/preview", job.title);
    actions.append(preview);
    for (const [path, label] of [["/video", "MP4"], ["/subs", "SRT"]]) {
      downloadLink(path, label);
    }
  } else if (job.state === "failed") {
    const button = document.createElement("button");
    const offline = state.settings.local_voice && /HeyGen HTTP 402/.test(job.message);
    button.textContent = offline ? "用离线配音重试" : "重试";
    button.onclick = async () => {
      button.disabled = true;
      try { await post(base + "/retry", offline ? { provider: "local" } : {}); await refresh(); }
      catch (error) { message($("#queueMessage"), error.message); button.disabled = false; }
    };
    actions.append(button);
  }
  if (!actions.childElementCount) actions.textContent = "—";
  linksCell.append(actions);
  row.append(checkboxCell, name, status, progressCell, linksCell);
  return row;
}

function visibleJobs() {
  if (state.filter === "all") return state.jobs;
  if (state.filter === "running") return state.jobs.filter(({ state }) => ["queued", "running"].includes(state));
  return state.jobs.filter((job) => job.state === state.filter);
}

function renderJobs() {
  const visible = visibleJobs();
  $("#jobs").replaceChildren(...visible.map(jobRow));
  $("#empty").hidden = !!visible.length;
  $("#empty").textContent = state.jobs.length ? "当前筛选下没有任务。" : "添加视频后，可在这里查看处理进度。";
  const active = state.jobs.filter((job) => ["queued", "running"].includes(job.state)).length;
  const done = state.jobs.filter((job) => job.state === "done").length;
  $("#queueSummary").textContent = state.jobs.length ? `${state.jobs.length} 条任务 · ${active} 条待完成 · ${done} 条已导出` : "还没有任务";
  const displayed = visible.filter((job) => job.state === "done");
  const marked = displayed.filter((job) => state.selected.has(job.id)).length;
  $("#selectAll").checked = !!displayed.length && marked === displayed.length;
  $("#selectAll").indeterminate = marked > 0 && marked < displayed.length;
  $("#selectAll").disabled = !displayed.length;
  $("#batchDownload").disabled = !state.selected.size || state.downloading;
  $("#downloadCount").textContent = state.selected.size ? "· " + state.selected.size : "";
}

function setFilter(filter) {
  state.filter = filter;
  for (const button of document.querySelectorAll("[data-filter]")) {
    const active = button.dataset.filter === filter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  renderJobs();
}

document.querySelectorAll("[data-filter]").forEach((button) => { button.onclick = () => setFilter(button.dataset.filter); });
$("#selectAll").onchange = (event) => {
  for (const job of visibleJobs().filter((job) => job.state === "done")) {
    if (event.target.checked) state.selected.add(job.id); else state.selected.delete(job.id);
  }
  renderJobs();
};

let lastSnapshot = "";
async function refresh() {
  try {
    const jobs = await api("/api/jobs");
    const snapshot = JSON.stringify(jobs);
    if (snapshot !== lastSnapshot) {
      state.jobs = jobs;
      lastSnapshot = snapshot;
      renderJobs();
    }
  } catch (error) { message($("#queueMessage"), error.message); }
}

$("#batchDownload").onclick = async () => {
  if (state.selected.size > 30) {
    message($("#queueMessage"), "一次最多打包 30 条成片。");
    return;
  }
  state.downloading = true;
  renderJobs();
  message($("#queueMessage"), "正在准备批量下载…");
  try {
    const result = await post("/api/archive", { ids: [...state.selected] });
    const link = document.createElement("a");
    link.href = result.url;
    link.download = "";
    link.click();
    message($("#queueMessage"), "已开始打包下载。");
  } catch (error) { message($("#queueMessage"), error.message); }
  finally { state.downloading = false; renderJobs(); }
};

const settingsDialog = $("#settingsDialog");
const previewDialog = $("#previewDialog");
const player = $("#player");
function play(url, title) {
  $("#previewTitle").textContent = title;
  player.src = url;
  previewDialog.showModal();
  player.play().catch(() => {});
}
$("#playSample").onclick = () => play("/api/example", "二虎的职场电话");
previewDialog.onclose = () => { player.pause(); player.removeAttribute("src"); player.load(); };
for (const button of document.querySelectorAll("[data-close]")) {
  button.onclick = () => button.closest("dialog").close();
}

async function loadSettings() {
  const config = await api("/api/settings");
  state.settings = config;
  $("#provider").querySelector('[value="heygen"]').disabled = !config.heygen;
  $("#provider").querySelector('[value="local"]').disabled = !config.local_voice;
  $("#provider").querySelector('[value="local"]').textContent = config.server ? "服务器离线韩语试听" : "本机韩语音色";
  if (!config.local_voice) $("#provider").value = "heygen";
  else if (!config.heygen) $("#provider").value = "local";
  $(".online-label").textContent = config.server ? "服务器运行" : "本机运行";
  $("#openFolder").hidden = config.server;
  $("#keyStorage").textContent = config.server ? "密钥保存在服务器私有目录。使用配音或口型时会调用 HeyGen。" : "密钥保存在本机。仅当选择 HeyGen 配音或口型时会调用 API。";
  $("#lipsync").disabled = !config.heygen;
  if (!config.heygen) $("#lipsync").checked = false;
  $("#lipHint").textContent = config.heygen ? "成片导出后请预览" : "需连接 HeyGen";
  $("#playSample").disabled = !config.example;
  $("#addSample").hidden = !config.example_source;
  $("#disconnect").disabled = !config.heygen || config.env_key;
  $("#apiKey").disabled = config.env_key;
  $("#connect").disabled = config.env_key;
  renderJobs();
  $("#health").replaceChildren(...[
    ["普通话识别", config.whisper ? "Whisper 已就绪" : "缺少 Whisper 模型", config.whisper],
    ["韩语翻译", config.ollama ? config.model + " 已就绪" : "翻译模型未就绪", config.ollama],
    ["链接下载", config.kuku ? "KuKuTool 已就绪" : "缺少 ego-browser", config.kuku],
    ["HeyGen API", config.heygen ? "已连接" : "未配置", config.heygen],
  ].map(([name, value, ok]) => {
    const item = document.createElement("span");
    const label = document.createElement("strong");
    label.textContent = value;
    if (!ok) label.className = "off";
    item.append(name, label);
    return item;
  }));
}

$("#settingsButton").onclick = () => {
  settingsDialog.showModal();
  loadSettings().catch((error) => message($("#settingsMessage"), error.message));
};

async function saveKey(key) {
  $("#connect").disabled = true;
  $("#disconnect").disabled = true;
  message($("#settingsMessage"), "正在验证…", true);
  try {
    await post("/api/settings", { key });
    $("#apiKey").value = "";
    await loadSettings();
    message($("#settingsMessage"), key ? "HeyGen 已连接。" : "HeyGen 已断开。", true);
  } catch (error) {
    message($("#settingsMessage"), error.message);
    $("#connect").disabled = false;
    $("#disconnect").disabled = !state.settings.heygen || state.settings.env_key;
  }
}

$("#settingsForm").onsubmit = (event) => {
  event.preventDefault();
  const key = $("#apiKey").value.trim();
  if (key) saveKey(key); else message($("#settingsMessage"), "请填写 API Key。");
};
$("#disconnect").onclick = () => saveKey("");
$("#openFolder").onclick = () => post("/api/output", {}).catch((error) => message($("#formMessage"), error.message));

renderInput();
renderJobs();
loadSettings().catch((error) => message($("#formMessage"), error.message));
refresh();
setInterval(refresh, 2200);
