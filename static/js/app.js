/**
 * 身份证信息自动提取工具 — 前端交互逻辑
 */

// ====== 全局状态 ======
let currentFrontFile = null;
let currentBackFile = null;
let currentResult = null;
let batchResults = [];
let currentBatchDir = "";
// 用于模板选择回调的临时存储
let _pendingFillRecords = null;
// 历史记录缓存（供选中导出/填模板使用）
let _cachedHistoryRecords = [];
// 原始 OCR 弹窗当前上下文（"single" | “batch”）
let _rawOcrContext = null;
let _rawOcrBatchIndex = -1;

// ====== 初始化 ======
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initUploadZones();
    checkOcrStatus();
    setInterval(checkOcrStatus, 30000);
});

// ====== 导航 ======
function initNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", () => {
            const page = item.dataset.page;
            document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
            item.classList.add("active");
            document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
            document.getElementById(`page-${page}`).classList.add("active");
            if (page === "templates") loadTemplates();
            if (page === "export") loadHistory();
        });
    });
}

// ====== OCR 状态 ======
async function checkOcrStatus() {
    try {
        const resp = await fetch("/api/ocr/status");
        const data = await resp.json();
        const dot = document.getElementById("ocrStatusDot");
        const text = document.getElementById("ocrStatusText");
        if (data.online) {
            dot.classList.add("online");
            text.textContent = "OCR 服务在线";
        } else {
            dot.classList.remove("online");
            text.textContent = "OCR 服务离线";
        }
    } catch {
        document.getElementById("ocrStatusDot").classList.remove("online");
        document.getElementById("ocrStatusText").textContent = "OCR 服务离线";
    }
}

// ====== 上传区域初始化 ======
function initUploadZones() {
    // 单张识别上传
    const uploadZone = document.getElementById("uploadZone");
    const fileInput = document.getElementById("fileInput");

    uploadZone.addEventListener("click", () => fileInput.click());
    uploadZone.addEventListener("dragover", e => {
        e.preventDefault();
        uploadZone.classList.add("dragover");
    });
    uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
    uploadZone.addEventListener("drop", e => {
        e.preventDefault();
        uploadZone.classList.remove("dragover");
        handleFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener("change", e => handleFiles(e.target.files));

    // 批量上传
    const batchZone = document.getElementById("batchUploadZone");
    const batchInput = document.getElementById("batchFileInput");

    batchZone.addEventListener("click", () => batchInput.click());
    batchZone.addEventListener("dragover", e => {
        e.preventDefault();
        batchZone.classList.add("dragover");
    });
    batchZone.addEventListener("dragleave", () => batchZone.classList.remove("dragover"));
    batchZone.addEventListener("drop", e => {
        e.preventDefault();
        batchZone.classList.remove("dragover");
        handleBatchFiles(e.dataTransfer.files);
    });
    batchInput.addEventListener("change", e => handleBatchFiles(e.target.files));

    // 模板上传
    const tplZone = document.getElementById("templateUploadZone");
    const tplInput = document.getElementById("templateFileInput");

    tplZone.addEventListener("click", () => tplInput.click());
    tplZone.addEventListener("dragover", e => {
        e.preventDefault();
        tplZone.classList.add("dragover");
    });
    tplZone.addEventListener("dragleave", () => tplZone.classList.remove("dragover"));
    tplZone.addEventListener("drop", e => {
        e.preventDefault();
        tplZone.classList.remove("dragover");
        if (e.dataTransfer.files[0]) uploadTemplate(e.dataTransfer.files[0]);
    });
    tplInput.addEventListener("change", e => {
        if (e.target.files[0]) uploadTemplate(e.target.files[0]);
    });
}

// ====== 单张识别: 文件处理 ======
function handleFiles(files) {
    for (const file of files) {
        if (!file.type.startsWith("image/")) continue;

        if (!currentFrontFile) {
            currentFrontFile = file;
            showPreview("frontPreview", file, "正面（人像面）");
        } else if (!currentBackFile) {
            currentBackFile = file;
            showPreview("backPreview", file, "反面（国徽面）");
        }
    }
    updateRecognizeBtn();
}

function showPreview(slotId, file, label) {
    const slot = document.getElementById(slotId);
    const reader = new FileReader();
    reader.onload = e => {
        slot.innerHTML = `
            <div class="label">${label}</div>
            <img src="${e.target.result}" alt="${label}">
            <button class="remove-btn" onclick="remove${slotId === 'frontPreview' ? 'Front' : 'Back'}()">✕</button>
        `;
        slot.classList.add("has-image");
    };
    reader.readAsDataURL(file);
}

function removeFront() {
    currentFrontFile = null;
    const slot = document.getElementById("frontPreview");
    slot.innerHTML = `
        <div class="label">正面（人像面）</div>
        <div class="upload-hint">未选择</div>
        <button class="remove-btn" onclick="removeFront()">✕</button>
    `;
    slot.classList.remove("has-image");
    updateRecognizeBtn();
}

function removeBack() {
    currentBackFile = null;
    const slot = document.getElementById("backPreview");
    slot.innerHTML = `
        <div class="label">反面（国徽面）</div>
        <div class="upload-hint">未选择（可选）</div>
        <button class="remove-btn" onclick="removeBack()">✕</button>
    `;
    slot.classList.remove("has-image");
    updateRecognizeBtn();
}

function updateRecognizeBtn() {
    document.getElementById("btnRecognize").disabled = !currentFrontFile && !currentBackFile;
}

// ====== 单张识别 ======
async function recognize() {
    if (!currentFrontFile && !currentBackFile) return;

    showLoading("正在识别身份证...");
    const formData = new FormData();
    if (currentFrontFile) formData.append("front", currentFrontFile);
    if (currentBackFile) formData.append("back", currentBackFile);

    try {
        const resp = await fetch("/api/ocr/recognize", { method: "POST", body: formData });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            currentResult = data.data;
            displayResult(data.data);
            showToast("识别成功！", "success");
        } else {
            showToast(data.error || "识别失败", "error");
            if (data.warnings) {
                data.warnings.forEach(w => showWarning(w));
            }
        }
    } catch (err) {
        hideLoading();
        showToast("请求失败: " + err.message, "error");
    }

    // 重置文件输入框，允许再次选择同一文件
    document.getElementById("fileInput").value = "";
    // 清空已选图片，准备下一组
    currentFrontFile = null;
    currentBackFile = null;
    removeFront();
    removeBack();
}

function displayResult(data) {
    const fields = [
        { key: "name", label: "姓名" },
        { key: "gender", label: "性别" },
        { key: "ethnicity", label: "民族" },
        { key: "birthday", label: "出生日期" },
        { key: "age", label: "年龄" },
        { key: "id_number", label: "身份证号码", fullWidth: true },
        { key: "address", label: "住址", fullWidth: true },
        { key: "authority", label: "签发机关" },
        { key: "validity", label: "有效期限" },
    ];

    let html = '<div class="result-grid">';
    for (const f of fields) {
        const value = data[f.key] || "";
        const cls = f.fullWidth ? "result-item full-width" : "result-item";
        const valCls = value ? "value" : "value empty";
        html += `<div class="${cls}">
            <span class="label">${f.label}</span>
            <span class="${valCls}">${value || "未识别"}</span>
        </div>`;
    }
    html += "</div>";

    document.getElementById("resultArea").innerHTML = html;
    document.getElementById("resultActions").style.display = "flex";

    // 显示警告
    const warningArea = document.getElementById("warningArea");
    warningArea.innerHTML = "";
    if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach(w => {
            warningArea.innerHTML += `<div class="alert alert-warning">⚠️ ${w}</div>`;
        });
    }

    // 显示原始 OCR 按钮（仅当有原始文本时）
    if (data.raw_ocr_front || data.raw_ocr_back) {
        const actionsEl = document.getElementById("resultActions");
        // 避免重复添加
        if (!actionsEl.querySelector(".btn-raw-ocr")) {
            const btn = document.createElement("button");
            btn.className = "btn btn-raw-ocr";
            btn.innerHTML = `<span>📜</span> 查看原始 OCR`;
            btn.onclick = () => showRawOcrModal("single");
            actionsEl.appendChild(btn);
        }
    }
}

// ====== 批量处理 ======
async function handleBatchFiles(files) {
    if (!files || files.length === 0) return;

    showLoading("正在上传文件...");
    const formData = new FormData();
    for (const f of files) {
        formData.append("files", f);
    }

    try {
        const resp = await fetch("/api/batch/upload", { method: "POST", body: formData });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            currentBatchDir = data.batch_dir;
            displayGroupPreview(data.groups);
            showToast(`已上传 ${data.total_files} 个文件，分为 ${data.groups.length} 组`, "success");
        } else {
            showToast(data.error, "error");
        }
    } catch (err) {
        hideLoading();
        showToast("上传失败: " + err.message, "error");
    }
}

function displayGroupPreview(groups) {
    const card = document.getElementById("batchGroupCard");
    const preview = document.getElementById("groupPreview");
    card.style.display = "block";

    let html = "";
    for (const g of groups) {
        html += `<div class="group-item">
            <span class="group-name">👤 ${g.name}</span>
            <span class="group-files">${g.files.join(", ")} (${g.count} 张)</span>
        </div>`;
    }
    preview.innerHTML = html;
}

async function batchRecognize() {
    if (!currentBatchDir) return;

    showLoading("正在批量识别...");
    document.getElementById("batchProgress").style.display = "block";
    document.getElementById("batchProgressFill").style.width = "30%";

    try {
        const resp = await fetch("/api/batch/recognize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ batch_dir: currentBatchDir })
        });
        document.getElementById("batchProgressFill").style.width = "100%";
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            batchResults = data.results;
            displayBatchResults(data.results);
            showToast(`批量识别完成，共 ${data.count} 条记录`, "success");
        } else {
            showToast(data.error, "error");
        }
    } catch (err) {
        hideLoading();
        showToast("批量识别失败: " + err.message, "error");
    }
}

function displayBatchResults(results) {
    const card = document.getElementById("batchResultCard");
    const tbody = document.getElementById("batchResultBody");
    card.style.display = "block";

    // 增加"操作"列头（如果还没有）
    const thead = document.querySelector("#batchResultTable thead tr");
    if (!thead.querySelector(".th-raw-ocr")) {
        const th = document.createElement("th");
        th.className = "th-raw-ocr";
        th.textContent = "原始";
        thead.appendChild(th);
    }

    let html = "";
    results.forEach((r, i) => {
        const hasRaw = r.raw_ocr_front || r.raw_ocr_back;
        html += `<tr>
            <td class="checkbox-cell"><input type="checkbox" class="batch-check" data-index="${i}" checked></td>
            <td>${r.name || "-"}</td>
            <td>${r.gender || "-"}</td>
            <td>${r.ethnicity || "-"}</td>
            <td>${r.birthday || "-"}</td>
            <td>${r.age || "-"}</td>
            <td>${r.id_number || "-"}</td>
            <td title="${r.address || ""}">${r.address || "-"}</td>
            <td>${r.authority || "-"}</td>
            <td>${r.validity || "-"}</td>
            <td>${hasRaw ? `<button class="btn-raw-ocr-sm" onclick="showRawOcrModal('batch', ${i})">📜 原始</button>` : "-"}</td>
        </tr>`;
    });
    tbody.innerHTML = html;
}

function toggleSelectAll() {
    const checked = document.getElementById("selectAll").checked;
    document.querySelectorAll(".batch-check").forEach(cb => cb.checked = checked);
}

function getSelectedBatchRecords() {
    const selected = [];
    document.querySelectorAll(".batch-check:checked").forEach(cb => {
        const idx = parseInt(cb.dataset.index);
        selected.push(batchResults[idx]);
    });
    return selected;
}

// ====== Excel 导出 ======
async function exportSingleExcel() {
    if (!currentResult) return;
    await exportRecords([currentResult]);
}

async function exportBatchExcel() {
    const records = getSelectedBatchRecords();
    if (records.length === 0) {
        showToast("请至少选择一条记录", "warning");
        return;
    }
    await exportRecords(records);
}

async function exportSelectedHistory() {
    // 导出历史记录中选中的项
    const checkboxes = document.querySelectorAll(".history-check:checked");
    if (checkboxes.length === 0) {
        showToast("请至少选择一条记录", "warning");
        return;
    }
    try {
        const resp = await fetch("/api/history");
        const data = await resp.json();
        const records = [];
        checkboxes.forEach(cb => {
            const idx = parseInt(cb.dataset.index);
            if (data.records[idx]) records.push(data.records[idx]);
        });
        await exportRecords(records);
    } catch (err) {
        showToast("获取历史失败: " + err.message, "error");
    }
}

async function exportRecords(records) {
    showLoading("正在导出 Excel...");
    try {
        const resp = await fetch("/api/export/excel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ records })
        });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast("导出成功！", "success");
            const a = document.createElement("a");
            a.href = data.path;
            a.download = data.filename || "export.xlsx";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } else {
            showToast(data.error, "error");
        }
    } catch (err) {
        hideLoading();
        showToast("导出失败: " + err.message, "error");
    }
}

// ====== 模板管理 ======
async function uploadTemplate(file) {
    if (!file) return;
    const formData = new FormData();
    formData.append("template", file);

    try {
        const resp = await fetch("/api/template/upload", { method: "POST", body: formData });
        const data = await resp.json();
        if (data.success) {
            showToast(`模板 "${data.filename}" 上传成功`, "success");
            // 【修复问题2】重置 file input，确保再次上传同名文件时 change 事件仍能触发
            document.getElementById("templateFileInput").value = "";
            loadTemplates();
        } else {
            showToast(data.error, "error");
        }
    } catch (err) {
        showToast("上传失败: " + err.message, "error");
    }
}

async function loadTemplates() {
    try {
        const resp = await fetch("/api/template/list");
        const data = await resp.json();
        const list = document.getElementById("templateList");

        if (data.templates.length === 0) {
            list.innerHTML = `<div class="empty-state"><div class="icon">📄</div><p>暂无模板，请上传</p></div>`;
            return;
        }

        let html = "";
        for (const t of data.templates) {
            const badgeCls = t.type === "Word" ? "word" : "excel";
            const size = (t.size / 1024).toFixed(1);
            html += `<div class="template-item">
                <div class="info">
                    <span class="type-badge ${badgeCls}">${t.type}</span>
                    <span>${t.filename}</span>
                    <span style="color:var(--text-muted); font-size:12px;">${size} KB</span>
                </div>
                <button class="btn btn-danger" style="padding:6px 12px; font-size:12px;" onclick="deleteTemplate('${t.filename}')">
                    🗑️ 删除
                </button>
            </div>`;
        }
        list.innerHTML = html;
    } catch (err) {
        console.error("加载模板列表失败:", err);
    }
}

async function deleteTemplate(filename) {
    if (!confirm(`确定删除模板 "${filename}"？`)) return;
    try {
        const resp = await fetch("/api/template/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename })
        });
        const data = await resp.json();
        if (data.success) {
            showToast("模板已删除", "success");
            // 【修复问题2】重置 file input
            document.getElementById("templateFileInput").value = "";
            loadTemplates();
        } else {
            showToast(data.error, "error");
        }
    } catch (err) {
        showToast("删除失败: " + err.message, "error");
    }
}

// ====== 模板填充 ======
async function fillTemplate() {
    if (!currentResult) {
        showToast("请先识别身份证", "warning");
        return;
    }
    showTemplateSelector([currentResult]);
}

async function fillTemplateBatch() {
    const records = getSelectedBatchRecords();
    if (records.length === 0) {
        showToast("请至少选择一条记录", "warning");
        return;
    }
    showTemplateSelector(records);
}

// 【修复问题3】不再在 onclick 中内联 JSON，改用全局变量 + 数据索引
async function showTemplateSelector(records) {
    _pendingFillRecords = records;

    try {
        const resp = await fetch("/api/template/list");
        const data = await resp.json();

        if (data.templates.length === 0) {
            showToast("请先上传模板文件", "warning");
            return;
        }

        const modal = document.getElementById("templateModal");
        const list = document.getElementById("templateSelectList");

        let html = "";
        data.templates.forEach((t, i) => {
            const badgeCls = t.type === "Word" ? "word" : "excel";
            html += `<div class="template-item" style="cursor:pointer;" data-tpl-name="${t.filename}" onclick="onTemplateSelected(this)">
                <div class="info">
                    <span class="type-badge ${badgeCls}">${t.type}</span>
                    <span>${t.filename}</span>
                </div>
                <span style="color:var(--accent-cyan);">选择 →</span>
            </div>`;
        });
        list.innerHTML = html;
        modal.style.display = "flex";
    } catch (err) {
        showToast("获取模板列表失败", "error");
    }
}

function onTemplateSelected(el) {
    const templateName = el.getAttribute("data-tpl-name");
    if (templateName && _pendingFillRecords) {
        doFillTemplate(templateName, _pendingFillRecords);
    }
}

function closeTemplateModal() {
    document.getElementById("templateModal").style.display = "none";
    _pendingFillRecords = null;
}

async function doFillTemplate(templateName, records) {
    closeTemplateModal();
    showLoading("正在填充模板...");

    try {
        const resp = await fetch("/api/template/fill", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template: templateName, records })
        });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            showToast(`模板填充成功，生成 ${data.files.length} 个文件`, "success");
            // 逐个延迟下载，避免浏览器拦截
            for (let i = 0; i < data.files.length; i++) {
                setTimeout(() => {
                    const a = document.createElement("a");
                    a.href = data.files[i].path;
                    a.download = data.files[i].filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                }, i * 500); // 每个文件间隔 500ms
            }
            // 显示生成文件列表
            if (data.files.length > 1) {
                let msg = "已生成以下文件：\n";
                data.files.forEach(f => msg += `📄 ${f.filename}\n`);
                showToast(msg, "success");
            }
        } else {
            showToast(data.error, "error");
        }
    } catch (err) {
        hideLoading();
        showToast("模板填充失败: " + err.message, "error");
    }
}

// ====== 历史记录 ======
// 【修复问题4】增加序号、OCR时间、全选框
async function loadHistory() {
    try {
        const resp = await fetch("/api/history");
        const data = await resp.json();
        const area = document.getElementById("historyArea");
        const actions = document.getElementById("exportActions");

        if (!data.records || data.records.length === 0) {
            area.innerHTML = `<div class="empty-state"><div class="icon">📭</div><p>暂无识别记录</p></div>`;
            actions.style.display = "none";
            _cachedHistoryRecords = [];
            return;
        }

        _cachedHistoryRecords = data.records;
        actions.style.display = "flex";
        let html = `<div style="overflow-x:auto;"><table class="data-table">
            <thead><tr>
                <th class="checkbox-cell"><input type="checkbox" id="historySelectAll" onchange="toggleHistorySelectAll()" checked></th>
                <th>序号</th>
                <th>识别时间</th>
                <th>姓名</th>
                <th>性别</th>
                <th>民族</th>
                <th>出生日期</th>
                <th>年龄</th>
                <th>身份证号码</th>
                <th>住址</th>
                <th>签发机关</th>
                <th>有效期限</th>
            </tr></thead><tbody>`;

        data.records.forEach((r, i) => {
            html += `<tr>
                <td class="checkbox-cell"><input type="checkbox" class="history-check" data-index="${i}" checked></td>
                <td>${i + 1}</td>
                <td>${r.timestamp || "-"}</td>
                <td>${r.name || "-"}</td>
                <td>${r.gender || "-"}</td>
                <td>${r.ethnicity || "-"}</td>
                <td>${r.birthday || "-"}</td>
                <td>${r.age || "-"}</td>
                <td>${r.id_number || "-"}</td>
                <td title="${r.address || ""}">${r.address || "-"}</td>
                <td>${r.authority || "-"}</td>
                <td>${r.validity || "-"}</td>
            </tr>`;
        });
        html += "</tbody></table></div>";
        area.innerHTML = html;
    } catch (err) {
        console.error("加载历史失败:", err);
    }
}

function toggleHistorySelectAll() {
    const checked = document.getElementById("historySelectAll").checked;
    document.querySelectorAll(".history-check").forEach(cb => cb.checked = checked);
}

function getSelectedHistoryRecords() {
    const selected = [];
    const checkboxes = document.querySelectorAll(".history-check:checked");
    // 需要从服务器获取完整数据，暂使用缓存
    checkboxes.forEach(cb => {
        const idx = parseInt(cb.dataset.index);
        if (_cachedHistoryRecords && _cachedHistoryRecords[idx]) {
            selected.push(_cachedHistoryRecords[idx]);
        }
    });
    return selected;
}

async function fillTemplateFromHistory() {
    const records = getSelectedHistoryRecords();
    if (records.length === 0) {
        showToast("请至少选择一条记录", "warning");
        return;
    }
    showTemplateSelector(records);
}

async function clearHistory() {
    if (!confirm("确定清空所有识别历史？")) return;
    try {
        await fetch("/api/history/clear", { method: "POST" });
        showToast("历史已清空", "success");
        loadHistory();
    } catch (err) {
        showToast("清空失败: " + err.message, "error");
    }
}

// ====== UI 辅助 ======
function showLoading(text) {
    document.getElementById("loadingText").textContent = text || "处理中...";
    document.getElementById("loadingOverlay").classList.add("show");
}

function hideLoading() {
    document.getElementById("loadingOverlay").classList.remove("show");
}

function showToast(message, type = "success") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icons = { success: "✅", error: "❌", warning: "⚠️" };
    toast.textContent = `${icons[type] || ""} ${message}`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function showWarning(message) {
    const area = document.getElementById("warningArea");
    area.innerHTML += `<div class="alert alert-warning">⚠️ ${message}</div>`;
}

// ====== 原始 OCR 查看/编辑 ======
function showRawOcrModal(context, batchIndex) {
    _rawOcrContext = context;
    _rawOcrBatchIndex = batchIndex !== undefined ? batchIndex : -1;

    let frontLines = [];
    let backLines = [];

    if (context === "single" && currentResult) {
        frontLines = currentResult.raw_ocr_front || [];
        backLines = currentResult.raw_ocr_back || [];
    } else if (context === "batch" && batchResults[batchIndex]) {
        frontLines = batchResults[batchIndex].raw_ocr_front || [];
        backLines = batchResults[batchIndex].raw_ocr_back || [];
    }

    document.getElementById("rawOcrFront").value = frontLines.join("\n");
    document.getElementById("rawOcrBack").value = backLines.join("\n");
    document.getElementById("rawOcrModal").style.display = "flex";
}

function closeRawOcrModal() {
    document.getElementById("rawOcrModal").style.display = "none";
    _rawOcrContext = null;
    _rawOcrBatchIndex = -1;
}

async function reparseFromModal() {
    const frontText = document.getElementById("rawOcrFront").value.trim();
    const backText = document.getElementById("rawOcrBack").value.trim();

    const frontLines = frontText ? frontText.split("\n").filter(l => l.trim()) : [];
    const backLines = backText ? backText.split("\n").filter(l => l.trim()) : [];

    if (frontLines.length === 0 && backLines.length === 0) {
        showToast("请输入至少一行 OCR 文本", "warning");
        return;
    }

    showLoading("正在重新解析...");

    try {
        const resp = await fetch("/api/ocr/reparse", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ front_lines: frontLines, back_lines: backLines })
        });
        const data = await resp.json();
        hideLoading();

        if (data.success) {
            if (_rawOcrContext === "single") {
                currentResult = data.data;
                displayResult(data.data);
                showToast("重新解析成功！", "success");
            } else if (_rawOcrContext === "batch" && _rawOcrBatchIndex >= 0) {
                // 更新批量结果中对应的记录
                batchResults[_rawOcrBatchIndex] = {
                    ...batchResults[_rawOcrBatchIndex],
                    ...data.data
                };
                displayBatchResults(batchResults);
                showToast(`第 ${_rawOcrBatchIndex + 1} 条记录重新解析成功！`, "success");
            }
            closeRawOcrModal();
        } else {
            showToast(data.error || "解析失败", "error");
        }
    } catch (err) {
        hideLoading();
        showToast("重新解析失败: " + err.message, "error");
    }
}
