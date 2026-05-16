const API_BASE = "/api";

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadSection = document.getElementById('upload-section');
const mappingSection = document.getElementById('mapping-section');
const successSection = document.getElementById('success-section');
const loadingOverlay = document.getElementById('loading-overlay');
const loadingText = document.getElementById('loading-text');

let uploadedFiles = [];
let mergedMetadata = { layers: [], colors: [], linetypes: [] };
let currentMode = 'to-jww';

document.querySelectorAll('input[name="conversion-mode"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
        currentMode = e.target.value;
        const dzText = document.getElementById('drop-zone-text');
        const mDesc = document.getElementById('mode-desc');
        if (currentMode === 'to-jww') {
            dzText.textContent = "ここにDWG/DXFファイルをドラッグ＆ドロップ";
            mDesc.textContent = "標準的なDWG/DXFファイルをJw_cad向けDXF形式に変換します。";
            fileInput.accept = ".dxf,.dwg";
        } else {
            dzText.textContent = "ここにJWWファイルをドラッグ＆ドロップ";
            mDesc.textContent = "Jw_cadのJWWファイルを直接読み込み、AutoCAD DWG/DXF形式に変換します。";
            fileInput.accept = ".jww";
        }
    });
});

function getJwwLayerOptions() {
    let options = '';
    const groups = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F'];
    groups.forEach(g => {
        groups.forEach(l => {
            options += `<option value="${g}-${l}">${g}-${l}</option>`;
        });
    });
    return options;
}

function getJwwColorOptions() {
    const colors = [
        { val: '1', name: '1 (水色)' },
        { val: '2', name: '2 (黒/白 - 背景対応)' },
        { val: '3', name: '3 (緑)' },
        { val: '4', name: '4 (黄)' },
        { val: '5', name: '5 (紫)' },
        { val: '6', name: '6 (青)' },
        { val: '7', name: '7 (水色)' },
        { val: '8', name: '8 (赤)' },
        { val: '9', name: '9 (ピンク)' }
    ];
    return colors.map(c => `<option value="${c.val}">${c.name}</option>`).join('');
}

function getJwwLinetypeOptions() {
    const linetypes = [
        { val: '1', name: '1 (実線 / Continuous)' },
        { val: '2', name: '2 (点線1 / Dotted)' },
        { val: '3', name: '3 (点線2)' },
        { val: '4', name: '4 (点線3)' },
        { val: '5', name: '5 (一点鎖線1 / Dash-Dot)' },
        { val: '6', name: '6 (一点鎖線2)' },
        { val: '7', name: '7 (二点鎖線1 / Dash-Dot-Dot)' },
        { val: '8', name: '8 (二点鎖線2)' },
        { val: '9', name: '9 (補助線)' }
    ];
    return linetypes.map(c => `<option value="${c.val}">${c.name}</option>`).join('');
}

function getDwgLayerOptions() {
    const layers = ['0', 'A-WALL', 'A-DOOR', 'A-GLAZ', 'A-FLOR', 'A-ROOF', 'A-ANNO-DIMS', 'A-ANNO-TEXT', 'S-GRID', 'S-STR'];
    return layers.map(l => `<option value="${l}">${l}</option>`).join('');
}

function getDwgColorOptions() {
    const colors = [
        { val: '256', name: 'BYLAYER (256/画層色)' },
        { val: '1', name: '1 (赤)' },
        { val: '2', name: '2 (黄)' },
        { val: '3', name: '3 (緑)' },
        { val: '4', name: '4 (水色)' },
        { val: '5', name: '5 (青)' },
        { val: '6', name: '6 (マゼンタ)' },
        { val: '7', name: '7 (白/黒)' }
    ];
    return colors.map(c => `<option value="${c.val}">${c.name}</option>`).join('');
}

function getDwgLinetypeOptions() {
    const linetypes = [
        {val: 'Continuous', name: 'Continuous (実線)'},
        {val: 'DASHED', name: 'DASHED (破線)'},
        {val: 'HIDDEN', name: 'HIDDEN (隠線)'},
        {val: 'CENTER', name: 'CENTER (中心線)'},
        {val: 'DASHDOT', name: 'DASHDOT (一点鎖線)'},
        {val: 'DIVIDE', name: 'DIVIDE (二点鎖線)'}
    ];
    return linetypes.map(l => `<option value="${l.val}">${l.name}</option>`).join('');
}

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
});

dropZone.addEventListener('drop', handleDrop, false);
fileInput.addEventListener('change', function () {
    if (this.files.length) handleMultipleFiles(this.files);
});

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length) handleMultipleFiles(files);
}

async function handleMultipleFiles(fileList) {
    const files = Array.from(fileList);
    const validExts = ['dxf', 'dwg', 'jww'];
    const validFiles = files.filter(f => {
        const ext = f.name.toLowerCase().split('.').pop();
        return validExts.includes(ext);
    });

    if (validFiles.length === 0) {
        alert("DXF、DWG、またはJWWファイルのみ対応しています。");
        return;
    }

    const firstExt = validFiles[0].name.toLowerCase().split('.').pop();
    if (firstExt === 'jww' && currentMode === 'to-jww') {
        currentMode = 'jww-to-dwg';
        document.getElementById('mode-jww-to-dwg').checked = true;
        document.getElementById('mode-desc').textContent = "Jw_cadのJWWファイルを直接読み込み、AutoCAD DWG/DXF形式に変換します。";
    }

    showLoading(`${validFiles.length}件のファイルをアップロード中...`);

    uploadedFiles = [];
    mergedMetadata = { layers: [], colors: [], linetypes: [] };
    const layerSet = new Set();
    const colorSet = new Set();
    const linetypeSet = new Set();

    try {
        for (let i = 0; i < validFiles.length; i++) {
            const file = validFiles[i];
            showLoading(`アップロード中... (${i + 1}/${validFiles.length}) ${file.name}`);

            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch(`${API_BASE}/upload`, {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || `${file.name} のアップロードに失敗しました`);
            }

            uploadedFiles.push({
                file_id: data.file_id,
                filename: data.filename,
                source_format: data.source_format,
                metadata: data.metadata
            });

            (data.metadata.layers || []).forEach(l => layerSet.add(l));
            (data.metadata.colors || []).forEach(c => colorSet.add(String(c)));
            (data.metadata.linetypes || []).forEach(lt => linetypeSet.add(String(lt)));
        }

        mergedMetadata = {
            layers: [...layerSet].sort(),
            colors: [...colorSet].sort(),
            linetypes: [...linetypeSet].sort()
        };

        renderFileList();

        const displayName = uploadedFiles.length === 1
            ? uploadedFiles[0].filename
            : `${uploadedFiles.length}件のファイル`;
        document.getElementById('filename-display').textContent = displayName;

        const badge = document.getElementById('source-format-badge');
        badge.textContent = `入力: ${uploadedFiles[0].source_format.toUpperCase()} (${uploadedFiles.length}件)`;
        badge.classList.remove('hidden');

        renderMappingTables(mergedMetadata);
        switchSection(mappingSection);
    } catch (error) {
        alert(error.message);
    } finally {
        hideLoading();
    }
}

function renderFileList() {
    const list = document.getElementById('file-list');
    list.innerHTML = '';
    uploadedFiles.forEach((f, i) => {
        const li = document.createElement('li');
        li.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:0.4rem 0.6rem; border-bottom:1px solid rgba(255,255,255,0.1);';
        li.innerHTML = `
            <span style="color:#e2e8f0;">${i + 1}. ${f.filename}</span>
            <span style="font-size:0.8rem; color:#94a3b8;">${f.source_format.toUpperCase()}</span>
        `;
        list.appendChild(li);
    });
}

function renderMappingTables(metadata) {
    const layerTbody = document.querySelector('#layer-table tbody');
    const colorTbody = document.querySelector('#color-table tbody');
    const linetypeTbody = document.querySelector('#linetype-table tbody');

    layerTbody.innerHTML = ''; colorTbody.innerHTML = ''; linetypeTbody.innerHTML = '';

    const layerSrc = document.getElementById('th-layer-src');
    const layerTgt = document.getElementById('th-layer-tgt');
    const colorSrc = document.getElementById('th-color-src');
    const colorTgt = document.getElementById('th-color-tgt');
    const lineSrc = document.getElementById('th-linetype-src');
    const lineTgt = document.getElementById('th-linetype-tgt');

    const isToJww = currentMode === 'to-jww';

    if (isToJww) {
        layerSrc.textContent = "DWG レイヤー"; layerTgt.textContent = "JWW 変換先グループ-レイヤー";
        colorSrc.textContent = "DWG 色"; colorTgt.textContent = "JWW 変換先色";
        lineSrc.textContent = "DWG 線種"; lineTgt.textContent = "JWW 変換先線種";
    } else {
        layerSrc.textContent = "JWW レイヤー"; layerTgt.textContent = "DWG 変換先レイヤー";
        colorSrc.textContent = "JWW 色"; colorTgt.textContent = "DWG 変換先色 (ACI)";
        lineSrc.textContent = "JWW 線種"; lineTgt.textContent = "DWG 変換先線種";
    }

    if (isToJww) {
        const layerOptions = getJwwLayerOptions();
        metadata.layers.forEach((layer, i) => {
            const defaultTarget = `0-${(i % 16).toString(16).toUpperCase()}`;
            layerTbody.insertAdjacentHTML('beforeend', `<tr><td>${layer}</td><td><select data-type="layer" data-orig="${layer}">${layerOptions}</select></td></tr>`);
            const select = layerTbody.lastElementChild.querySelector('select');
            if (select.querySelector(`option[value="${defaultTarget}"]`)) select.value = defaultTarget;
        });
    } else {
        metadata.layers.forEach((layer) => {
            layerTbody.insertAdjacentHTML('beforeend', `<tr><td>${layer}</td><td><input type="text" data-type="layer" data-orig="${layer}" value="${layer}" class="mapping-input"></td></tr>`);
        });
    }

    const colorOptions = isToJww ? getJwwColorOptions() : getDwgColorOptions();
    metadata.colors.forEach((color) => {
        let defaultColor = isToJww ? "2" : "256";
        if (isToJww) {
            if (color == "1") defaultColor = "8"; else if (color == "2") defaultColor = "4"; else if (color == "3") defaultColor = "3"; else if (color == "4") defaultColor = "1"; else if (color == "5") defaultColor = "6";
        }
        const colorLabel = color == 256 ? 'BYLAYER' : color;
        colorTbody.insertAdjacentHTML('beforeend', `<tr><td>色 ${colorLabel}</td><td><select data-type="color" data-orig="${color}">${colorOptions}</select></td></tr>`);
        colorTbody.lastElementChild.querySelector('select').value = defaultColor;
    });

    const linetypeOptions = isToJww ? getJwwLinetypeOptions() : getDwgLinetypeOptions();
    metadata.linetypes.forEach((linetype) => {
        let defaultLinetype = isToJww ? "1" : "Continuous";
        if (isToJww) {
            const lName = String(linetype).toLowerCase();
            if (lName.includes("dash") || lName === "2" || lName === "3") defaultLinetype = "2";
            if (lName.includes("dot") || lName === "5" || lName === "6") defaultLinetype = "5";
        }
        linetypeTbody.insertAdjacentHTML('beforeend', `<tr><td>${linetype}</td><td><select data-type="linetype" data-orig="${linetype}">${linetypeOptions}</select></td></tr>`);
        linetypeTbody.lastElementChild.querySelector('select').value = defaultLinetype;
    });
}

document.getElementById('btn-ai-suggest').addEventListener('click', async () => {
    if (!mergedMetadata || mergedMetadata.layers.length === 0) return;

    showLoading("AIが画層を解析し、最適なマッピングを提案しています...");
    try {
        const direction = currentMode === 'jww-to-dwg' ? 'to-dwg' : currentMode;
        const response = await fetch(`${API_BASE}/ai-suggest-mapping`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                direction: direction,
                layers: mergedMetadata.layers,
                colors: mergedMetadata.colors.map(String)
            })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "AIの提案に失敗しました");

        if (data.layer_mapping) {
            Object.entries(data.layer_mapping).forEach(([orig, target]) => {
                const el = document.querySelector(`[data-type="layer"][data-orig="${orig}"]`);
                if (el) {
                    if (el.tagName === 'SELECT') {
                        let targetVal = target.length === 1 ? `0-${target.toUpperCase()}` : target;
                        if (el.querySelector(`option[value="${targetVal}"]`)) {
                            el.value = targetVal;
                        }
                    } else {
                        el.value = target;
                    }
                    el.classList.add('ai-suggested');
                }
            });
        }

        if (data.color_mapping) {
            Object.entries(data.color_mapping).forEach(([orig, target]) => {
                const sel = document.querySelector(`select[data-type="color"][data-orig="${orig}"]`);
                if (sel && sel.querySelector(`option[value="${target}"]`)) {
                    sel.value = target;
                    sel.classList.add('ai-suggested');
                }
            });
        }

    } catch (error) {
        alert(error.message);
    } finally {
        hideLoading();
    }
});

document.getElementById('btn-convert').addEventListener('click', async () => {
    if (uploadedFiles.length === 0) return;

    const mapping = { layers: {}, colors: {}, linetypes: {} };

    document.querySelectorAll('[data-type="layer"]').forEach(el => {
        mapping.layers[el.dataset.orig] = el.value;
    });

    document.querySelectorAll('[data-type="color"]').forEach(el => {
        mapping.colors[el.dataset.orig] = el.value;
    });

    document.querySelectorAll('[data-type="linetype"]').forEach(el => {
        mapping.linetypes[el.dataset.orig] = el.value;
    });

    showLoading(`${uploadedFiles.length}件のファイルを変換中...`);

    try {
        if (uploadedFiles.length === 1) {
            const response = await fetch(`${API_BASE}/convert`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: uploadedFiles[0].file_id, mapping, direction: currentMode })
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "変換に失敗しました");

            showSingleResult(data);
        } else {
            const fileIds = uploadedFiles.map(f => f.file_id);
            const response = await fetch(`${API_BASE}/convert-batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_ids: fileIds, mapping, direction: currentMode })
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "変換に失敗しました");

            showBatchResult(data);
        }

        switchSection(successSection);
    } catch (error) {
        alert(error.message);
    } finally {
        hideLoading();
    }
});

function showSingleResult(data) {
    const downloadUrl = data.download_url;
    const downloadLink = document.getElementById('download-link');
    downloadLink.href = downloadUrl;

    const outputFmt = (data.output_format || 'dxf').toUpperCase();
    const origBase = uploadedFiles[0].filename.replace(/\.[^.]+$/, '');
    const downloadFilename = `${origBase}.${data.output_format || 'dxf'}`;
    downloadLink.setAttribute('download', downloadFilename);

    downloadLink.onclick = async (e) => {
        if (window.showSaveFilePicker) {
            e.preventDefault();
            try {
                const resp = await fetch(downloadUrl);
                const blob = await resp.blob();
                const ext = data.output_format || 'dxf';
                const handle = await window.showSaveFilePicker({
                    suggestedName: downloadFilename,
                    types: [{
                        description: `${ext.toUpperCase()} File`,
                        accept: { 'application/octet-stream': [`.${ext}`] }
                    }]
                });
                const writable = await handle.createWritable();
                await writable.write(blob);
                await writable.close();
            } catch (err) {
                if (err.name !== 'AbortError') {
                    window.location.href = downloadUrl;
                }
            }
        }
    };

    const successMsg = document.getElementById('success-message');
    downloadLink.textContent = `${outputFmt}ファイルをダウンロード`;

    if (currentMode === 'jww-to-dwg') {
        if (outputFmt === 'DWG') {
            successMsg.textContent = "JWWファイルをAutoCAD DWG形式に変換しました。";
        } else {
            successMsg.textContent = "JWWファイルをAutoCAD互換DXF形式に変換しました。（ODA File Converterが利用可能な環境ではDWG出力されます）";
        }
    } else if (currentMode === 'to-jww') {
        successMsg.textContent = "Jw_cad互換DXFファイルの準備ができました。";
    } else {
        successMsg.textContent = "AutoCAD互換DXFファイルの準備ができました。";
    }
}

function showBatchResult(data) {
    const downloadUrl = data.download_url;
    const downloadLink = document.getElementById('download-link');
    downloadLink.href = downloadUrl;
    downloadLink.setAttribute('download', 'converted_files.zip');

    const successCount = data.results.length;
    const errorCount = data.errors.length;

    downloadLink.onclick = async (e) => {
        if (window.showSaveFilePicker) {
            e.preventDefault();
            try {
                const resp = await fetch(downloadUrl);
                const blob = await resp.blob();
                const handle = await window.showSaveFilePicker({
                    suggestedName: 'converted_files.zip',
                    types: [{
                        description: 'ZIP File',
                        accept: { 'application/zip': ['.zip'] }
                    }]
                });
                const writable = await handle.createWritable();
                await writable.write(blob);
                await writable.close();
            } catch (err) {
                if (err.name !== 'AbortError') {
                    window.location.href = downloadUrl;
                }
            }
        }
    };

    const successMsg = document.getElementById('success-message');
    downloadLink.textContent = `ZIPファイルをダウンロード (${successCount}件)`;

    let msg = `${successCount}件のファイルを変換しました。`;
    if (errorCount > 0) {
        msg += ` ${errorCount}件のエラーが発生しました。`;
    }
    successMsg.textContent = msg;
}

document.getElementById('btn-cancel').addEventListener('click', () => {
    switchSection(uploadSection);
    resetState();
});

document.getElementById('btn-restart').addEventListener('click', () => {
    switchSection(uploadSection);
    resetState();
});

function resetState() {
    uploadedFiles = [];
    mergedMetadata = { layers: [], colors: [], linetypes: [] };
    fileInput.value = '';
    document.getElementById('source-format-badge').classList.add('hidden');
    document.getElementById('file-list').innerHTML = '';
}

function switchSection(section) {
    [uploadSection, mappingSection, successSection].forEach(s => s.classList.add('hidden'));
    section.classList.remove('hidden');
}

function showLoading(text) {
    loadingText.textContent = text;
    loadingOverlay.classList.remove('hidden');
}

function hideLoading() {
    loadingOverlay.classList.add('hidden');
}
