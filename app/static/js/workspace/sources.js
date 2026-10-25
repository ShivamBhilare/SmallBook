/**
 * @fileoverview Sources Management Controller.
 * Handles PDF uploads via drag-and-drop or file input, cross-notebook library linking,
 * source document renaming, detachment from workspaces, permanent deletion, client-side
 * sorting, and asynchronous Celery ingestion status polling.
 */

/* ==========================================================================
   UPLOAD MODAL & TAB CONTROLLERS
   ========================================================================== */

let isUploading = false;

/**
 * Opens the upload/library modal dialog.
 */
function openUploadModal() {
    document.getElementById('upload-modal').classList.remove('hidden');
}

/**
 * Closes the upload modal dialog and resets state if an upload is not in progress.
 */
function closeUploadModal() {
    if (isUploading) return;
    document.getElementById('upload-modal').classList.add('hidden');
    resetUploadUI();
}

/**
 * Resets the drop-zone UI state and switches to the direct upload tab.
 */
function resetUploadUI() {
    document.getElementById('drop-zone-content').classList.remove('opacity-0', 'pointer-events-none');
    document.getElementById('upload-progress').classList.add('hidden');
    document.getElementById('upload-spinner').classList.remove('hidden');
    document.getElementById('upload-success-icon').classList.add('hidden');
    document.getElementById('upload-title').innerText = "Uploading...";
    document.getElementById('upload-subtitle').innerText = "Please wait";
    const pBar = document.getElementById('upload-progress-bar');
    if (pBar) pBar.style.width = '0%';
    switchUploadTab('upload');
}

let librarySourcesData = [];

/**
 * Switches modal view between Direct File Upload and User Document Library.
 *
 * @param {string} tab - Tab name ('upload' or 'library').
 */
function switchUploadTab(tab) {
    const uploadTabBtn = document.getElementById('tab-btn-upload');
    const libraryTabBtn = document.getElementById('tab-btn-library');
    const uploadContent = document.getElementById('tab-content-upload');
    const libraryContent = document.getElementById('tab-content-library');

    if (!uploadTabBtn || !libraryTabBtn) return;

    if (tab === 'upload') {
        uploadTabBtn.className = 'flex-1 py-1.5 sm:py-2 px-2.5 sm:px-4 rounded-lg font-label-md font-medium text-xs sm:text-sm transition-all flex items-center justify-center gap-1.5 sm:gap-2 bg-surface-container-lowest dark:bg-dark-panel text-on-surface dark:text-dark-text shadow-sm';
        libraryTabBtn.className = 'flex-1 py-1.5 sm:py-2 px-2.5 sm:px-4 rounded-lg font-label-md font-medium text-xs sm:text-sm transition-all flex items-center justify-center gap-1.5 sm:gap-2 text-on-surface-variant dark:text-dark-text-muted hover:text-on-surface dark:hover:text-dark-text';
        uploadContent.classList.remove('hidden');
        libraryContent.classList.add('hidden');
    } else {
        libraryTabBtn.className = 'flex-1 py-1.5 sm:py-2 px-2.5 sm:px-4 rounded-lg font-label-md font-medium text-xs sm:text-sm transition-all flex items-center justify-center gap-1.5 sm:gap-2 bg-surface-container-lowest dark:bg-dark-panel text-on-surface dark:text-dark-text shadow-sm';
        uploadTabBtn.className = 'flex-1 py-1.5 sm:py-2 px-2.5 sm:px-4 rounded-lg font-label-md font-medium text-xs sm:text-sm transition-all flex items-center justify-center gap-1.5 sm:gap-2 text-on-surface-variant dark:text-dark-text-muted hover:text-on-surface dark:hover:text-dark-text';
        uploadContent.classList.add('hidden');
        libraryContent.classList.remove('hidden');
        loadLibraryChecklist();
    }
}

/**
 * Loads all user documents across all notebooks to populate the link checklist.
 *
 * @returns {Promise<void>}
 */
async function loadLibraryChecklist() {
    const loadingEl = document.getElementById('library-checklist-loading');
    const emptyEl = document.getElementById('library-checklist-empty');
    const containerEl = document.getElementById('library-checklist-container');

    if (!loadingEl || !emptyEl || !containerEl) return;

    loadingEl.classList.remove('hidden');
    emptyEl.classList.add('hidden');
    containerEl.classList.add('hidden');

    const existingSourceIds = new Set();
    document.querySelectorAll('.pdf-item[data-source-id]').forEach(el => {
        const sid = el.getAttribute('data-source-id');
        if (sid) existingSourceIds.add(sid);
    });

    try {
        const notebookId = getNotebookIdFromUrl();

        let res = await fetch(notebookId ? `/notebooks/${notebookId}/sources/library` : '/api/sources/all');
        if (!res.ok) {
            res = await fetch('/api/sources/all');
        }

        if (!res.ok) throw new Error('Failed to fetch library sources');
        const data = await res.json();
        librarySourcesData = data.sources || [];

        loadingEl.classList.add('hidden');
        if (librarySourcesData.length === 0) {
            emptyEl.classList.remove('hidden');
            return;
        }

        renderLibraryChecklist(existingSourceIds);
        containerEl.classList.remove('hidden');
    } catch (err) {
        console.error('Error loading library checklist:', err);
        loadingEl.classList.add('hidden');
        emptyEl.classList.remove('hidden');
    }
}

/**
 * Renders library document rows with checkboxes and existing notebook indicators.
 *
 * @param {Set<string>} existingSourceIds - Set of source IDs already in active notebook.
 */
function renderLibraryChecklist(existingSourceIds) {
    const containerEl = document.getElementById('library-checklist-container');
    const searchInput = document.getElementById('library-checklist-search');
    const searchQuery = (searchInput ? searchInput.value : '').toLowerCase();

    if (!containerEl) return;
    containerEl.innerHTML = '';

    const filtered = librarySourcesData.filter(s =>
        (s.original_filename || '').toLowerCase().includes(searchQuery)
    );

    if (filtered.length === 0) {
        containerEl.innerHTML = '<div class="text-center py-8 text-sm text-on-surface-variant dark:text-dark-text-muted">No sources match your search.</div>';
        updateLibrarySelectedCount();
        return;
    }

    filtered.forEach(source => {
        const isAlreadyLinked = existingSourceIds.has(source.id);
        const itemHtml = `
            <div class="flex items-center justify-between p-3 rounded-xl border border-paper dark:border-dark-border bg-surface-bright/50 dark:bg-dark-bg hover:border-secondary dark:hover:border-dark-accent transition-colors group">
                <div class="flex items-center gap-3 min-w-0 flex-1">
                    <input type="checkbox" value="${source.id}" ${isAlreadyLinked ? 'checked disabled' : ''} onchange="updateLibrarySelectedCount()" class="library-source-checkbox rounded border-outline-variant dark:border-dark-border text-secondary dark:text-dark-accent focus:ring-secondary cursor-pointer disabled:opacity-50">
                    <span class="material-symbols-outlined text-[20px] text-error dark:text-red-400 shrink-0">picture_as_pdf</span>
                    <div class="min-w-0 flex-1">
                        <p class="text-sm font-semibold text-on-surface dark:text-dark-text truncate leading-tight">${escapeHtml(source.original_filename)}</p>
                        <p class="text-xs text-on-surface-variant dark:text-dark-text-muted mt-0.5">${formatBytesJs(source.file_size_bytes)}</p>
                    </div>
                </div>
                ${isAlreadyLinked ? '<span class="text-[11px] font-medium bg-surface-variant/80 dark:bg-dark-panel-hover text-on-surface-variant dark:text-dark-text-muted px-2.5 py-1 rounded-full shrink-0">Already in Notebook</span>' : ''}
            </div>
        `;
        containerEl.insertAdjacentHTML('beforeend', itemHtml);
    });

    updateLibrarySelectedCount();
}

/**
 * Filters the library checklist based on user input.
 */
function filterLibraryChecklist() {
    const existingSourceIds = new Set();
    document.querySelectorAll('.pdf-item[data-source-id]').forEach(el => {
        const sid = el.getAttribute('data-source-id');
        if (sid) existingSourceIds.add(sid);
    });
    renderLibraryChecklist(existingSourceIds);
}

/**
 * Updates selected counter and enables/disables the Link Selected button.
 */
function updateLibrarySelectedCount() {
    const checkboxes = document.querySelectorAll('.library-source-checkbox:not(:disabled):checked');
    const count = checkboxes.length;
    const countEl = document.getElementById('library-selected-count');
    const btn = document.getElementById('btn-submit-link-sources');

    if (countEl) countEl.innerText = `${count} source${count === 1 ? '' : 's'} selected`;
    if (btn) btn.disabled = count === 0;
}

/**
 * Toggles selection of all eligible unlinked documents in the checklist.
 */
function selectAllLibraryChecklist() {
    const unlinkedCheckboxes = document.querySelectorAll('.library-source-checkbox:not(:disabled)');
    const allChecked = Array.from(unlinkedCheckboxes).every(cb => cb.checked);
    unlinkedCheckboxes.forEach(cb => cb.checked = !allChecked);
    updateLibrarySelectedCount();
}

/* ==========================================================================
   SOURCE ITEM HTML FACTORY
   ========================================================================== */

/**
 * Generates HTML string representing a source document tile in the left panel.
 *
 * @param {string} sourceId - Source UUID.
 * @param {string} filename - Document filename.
 * @param {boolean} [isPending=false] - Whether ingestion is in-flight.
 * @param {string} [nowIso=new Date().toISOString()] - ISO creation timestamp.
 * @param {boolean} [isChecked=true] - Whether the source checkbox is initially checked.
 * @returns {string} HTML markup string.
 */
function buildSourceItemHtml(sourceId, filename, isPending = false, nowIso = new Date().toISOString(), isChecked = true, status = 'completed', errorMsg = '') {
    const safeFilename = escapeHtml(filename);
    const safeErrorMsg = escapeHtml(errorMsg || 'Processing failed');
    const checkedAttr = isChecked ? 'checked' : '';

    let statusHtml = '';
    if (isPending || ['pending', 'processing', 'queued'].includes(status)) {
        statusHtml = `
            <svg class="animate-spin h-5 w-5 text-secondary dark:text-dark-accent source-spinner" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <input type="checkbox" value="${sourceId}" class="hidden source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0">`;
    } else if (status === 'failed') {
        statusHtml = `
            <span class="material-symbols-outlined text-[20px] text-error dark:text-red-400 cursor-pointer source-error-icon hover:scale-110 transition-transform" onclick="showSourceError(event, '${sourceId}', '${safeErrorMsg}')" title="Ingestion Failed: ${safeErrorMsg}. Click to retry.">error</span>
            <input type="checkbox" value="${sourceId}" class="hidden source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0">`;
    } else {
        statusHtml = `<input ${checkedAttr} class="source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0" type="checkbox" value="${sourceId}">`;
    }

    return `
        <label onclick="openPanel('left')" title="${safeFilename}" class="pdf-item flex items-center gap-sm p-sm hover:bg-surface-variant dark:hover:bg-dark-panel-hover rounded-md cursor-pointer transition-colors group relative" data-source-id="${sourceId}" data-filename="${safeFilename}" data-created-at="${nowIso}">
            <span class="material-symbols-outlined text-[20px] text-error dark:text-red-400 flex-shrink-0">picture_as_pdf</span>
            <div class="pdf-item-content flex-1 min-w-0 flex items-center gap-sm justify-between">
                <div class="font-label-md truncate group-hover:text-primary dark:group-hover:text-dark-text dark:text-dark-text source-filename">${safeFilename}</div>
                <div class="flex items-center gap-1 flex-shrink-0 relative">
                    <button type="button" onclick="toggleSourceMenu(event, '${sourceId}')" class="opacity-0 group-hover:opacity-100 p-1 rounded-full hover:bg-surface-variant/80 dark:hover:bg-dark-panel-hover text-on-surface-variant dark:text-dark-text-muted transition-opacity flex items-center justify-center" title="Source options">
                        <span class="material-symbols-outlined text-[18px]">more_vert</span>
                    </button>
                    <div id="source-menu-${sourceId}" class="source-menu hidden absolute right-0 top-full mt-1 w-36 bg-surface-container-lowest dark:bg-dark-panel border border-paper dark:border-dark-border rounded-md shadow-lg z-50 py-1 text-sm">
                        <button type="button" onclick="retrySourceIngestion(event, '${sourceId}')" class="w-full px-3 py-1.5 text-left text-secondary dark:text-dark-accent hover:bg-surface-variant dark:hover:bg-dark-panel-hover flex items-center gap-2">
                            <span class="material-symbols-outlined text-[16px]">refresh</span> Retry Ingestion
                        </button>
                        <button type="button" onclick="promptRenameSource(event, '${sourceId}', '${safeFilename}')" class="w-full px-3 py-1.5 text-left text-on-surface dark:text-dark-text hover:bg-surface-variant dark:hover:bg-dark-panel-hover flex items-center gap-2">
                            <span class="material-symbols-outlined text-[16px]">edit</span> Rename Source
                        </button>
                        <button type="button" onclick="promptDeleteSource(event, '${sourceId}', '${safeFilename}')" class="w-full px-3 py-1.5 text-left text-error dark:text-red-400 hover:bg-surface-variant dark:hover:bg-dark-panel-hover flex items-center gap-2">
                            <span class="material-symbols-outlined text-[16px]">cancel</span> <span class="cancel-text">Remove / Cancel</span>
                        </button>
                    </div>
                    <div class="source-status-container flex items-center">
                        ${statusHtml}
                    </div>
                </div>
            </div>
        </label>
    `;
}

/* ==========================================================================
   LINKING SELECTED SOURCES
   ========================================================================== */

/**
 * Links checked documents from library checklist to current notebook.
 *
 * @returns {Promise<void>}
 */
async function submitLinkSources() {
    const notebookId = getNotebookIdFromUrl();

    if (!notebookId) {
        showAppAlert('Notebook ID not found.', { title: 'Navigation Error', type: 'error' });
        return;
    }

    const selectedCheckboxes = document.querySelectorAll('.library-source-checkbox:not(:disabled):checked');
    const sourceIds = Array.from(selectedCheckboxes).map(cb => cb.value);

    if (sourceIds.length === 0) return;

    const btn = document.getElementById('btn-submit-link-sources');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span> Linking...';
    }

    try {
        const res = await fetch(`/notebooks/${notebookId}/sources/link`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_ids: sourceIds })
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || 'Failed to link sources.');
        }

        const data = await res.json();
        const newlyLinked = data.linked_sources || [];

        const sourcesList = document.getElementById('sources-list') || document.querySelector('#panel-sources .overflow-y-auto');
        if (sourcesList) {
            newlyLinked.forEach(source => {
                const filename = source.original_filename || 'Untitled Source';
                const sourceId = source.id;
                const nowIso = new Date().toISOString();
                sourcesList.insertAdjacentHTML('beforeend', buildSourceItemHtml(sourceId, filename, false, nowIso));
            });
        }
        closeUploadModal();
        updateSourcesCount();
    } catch (err) {
        console.error(err);
        showAppAlert(err.message || 'Error linking sources.', { title: 'Linking Failed', type: 'error' });
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px] sm:text-[18px]">add_link</span><span>Link Selected Sources</span>';
        }
    }
}

/**
 * Formats byte count into localized size string.
 *
 * @param {number} bytes - Byte count.
 * @returns {string} Formatted size.
 */
function formatBytesJs(bytes) {
    if (!bytes || bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/* ==========================================================================
   DRAG-AND-DROP FILE UPLOAD LOGIC
   ========================================================================== */

// Modal Document Click Handlers
document.getElementById('upload-modal').addEventListener('click', function(e) {
    if (e.target === this && !isUploading) closeUploadModal();
});

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

dropZone.addEventListener('click', () => { if (!isUploading) fileInput.click(); });
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); if (!isUploading) dropZone.classList.add('border-secondary'); });
dropZone.addEventListener('dragleave', (e) => { e.preventDefault(); dropZone.classList.remove('border-secondary'); });
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('border-secondary');
    if (!isUploading && e.dataTransfer.files.length > 0) uploadFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', function() {
     if(this.files.length > 0 && !isUploading) uploadFiles(this.files);
});

/**
 * Performs a single file upload using XMLHttpRequest to track accurate upload progress
 * and support generous timeouts on low-speed internet connections.
 *
 * @param {string} notebookId - Notebook identifier.
 * @param {File} file - PDF file to upload.
 * @param {number} index - Current file index (0-based).
 * @param {number} total - Total files count.
 * @returns {Promise<Object>} Resolves to server JSON response on success.
 */
function uploadSingleFileWithProgress(notebookId, file, index, total) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', `/notebooks/${notebookId}/sources/upload`, true);
        xhr.timeout = 180000; // 3-minute timeout for slow internet

        const progressBar = document.getElementById('upload-progress-bar');
        const uploadTitle = document.getElementById('upload-title');
        const uploadSubtitle = document.getElementById('upload-subtitle');

        if (uploadTitle) uploadTitle.innerText = `Uploading ${index + 1} of ${total}`;
        if (uploadSubtitle) uploadSubtitle.innerText = `${file.name} (0%)`;
        if (progressBar) progressBar.style.width = '0%';

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                if (progressBar) progressBar.style.width = `${percent}%`;
                if (uploadSubtitle) {
                    uploadSubtitle.innerText = `${file.name} • ${percent}% (${formatBytesJs(e.loaded)} / ${formatBytesJs(e.total)})`;
                }
            }
        };

        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const result = JSON.parse(xhr.responseText);
                    resolve(result);
                } catch (e) {
                    resolve({});
                }
            } else {
                let errorMsg = 'Failed to upload source.';
                try {
                    const errData = JSON.parse(xhr.responseText);
                    if (errData.detail) errorMsg = errData.detail;
                } catch (_) {}
                reject(new Error(errorMsg));
            }
        };

        xhr.onerror = () => {
            reject(new Error('Network error during upload. Please check your internet connection.'));
        };

        xhr.ontimeout = () => {
            reject(new Error('Upload timed out after 3 minutes due to low connection speed. Please retry.'));
        };

        const formData = new FormData();
        formData.append('file', file);
        xhr.send(formData);
    });
}

/**
 * Uploads selected PDF files sequentially to the notebook upload API.
 *
 * @param {FileList|Array<File>} files - Files to upload.
 * @returns {Promise<void>}
 */
async function uploadFiles(files) {
    const notebookId = getNotebookIdFromUrl();
    if (!notebookId) {
        showAppAlert('Notebook ID not found.', { title: 'Upload Error', type: 'error' });
        return;
    }

    isUploading = true;
    document.getElementById('drop-zone-content').classList.add('opacity-0', 'pointer-events-none');
    document.getElementById('upload-progress').classList.remove('hidden');

    let successCount = 0;
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (file.type !== 'application/pdf') {
            showAppAlert(`File "${file.name}" is not a PDF. Only PDF files are supported.`, {
                title: 'Invalid File Type',
                type: 'warning'
            });
            continue;
        }

        try {
            const result = await uploadSingleFileWithProgress(notebookId, file, i, files.length);
            const filename = result.filename || file.name;
            const sourceId = result.source_id || '';
            const nowIso = new Date().toISOString();
            const sourcesList = document.getElementById('sources-list');
            if (sourcesList) {
                sourcesList.insertAdjacentHTML('beforeend', buildSourceItemHtml(sourceId, filename, true, nowIso, true, 'pending'));
            }
            successCount++;
        } catch (error) {
            showAppAlert(`Error uploading ${file.name}:\n${error.message}`, { title: 'Upload Failed', type: 'error' });
        }
    }
    isUploading = false;
    if (successCount > 0) closeUploadModal();
    else resetUploadUI();
}

/* ==========================================================================
   SOURCE ACTIONS: RENAMING & CONTEXT MENUS
   ========================================================================== */

/**
 * Toggles visibility of the action dropdown menu for a specific source tile.
 *
 * @param {Event} event - Mouse click event.
 * @param {string} sourceId - Source UUID.
 */
function toggleSourceMenu(event, sourceId) {
    event.preventDefault();
    event.stopPropagation();
    const targetMenu = document.getElementById(`source-menu-${sourceId}`);
    document.querySelectorAll('.source-menu').forEach(menu => {
        if (menu !== targetMenu) menu.classList.add('hidden');
    });
    if (targetMenu) targetMenu.classList.toggle('hidden');
}

let currentRenameSourceId = null;

/**
 * Opens the source renaming modal and populates current name.
 *
 * @param {Event} event - Mouse click event.
 * @param {string} sourceId - Source UUID.
 * @param {string} currentName - Current filename string.
 */
function promptRenameSource(event, sourceId, currentName) {
    event.preventDefault();
    event.stopPropagation();
    document.querySelectorAll('.source-menu').forEach(m => m.classList.add('hidden'));
    currentRenameSourceId = sourceId;
    const input = document.getElementById('rename-input');
    if (input) input.value = currentName || '';
    document.getElementById('rename-source-modal').classList.remove('hidden');
    setTimeout(() => input && input.focus(), 100);
}

/**
 * Closes source renaming dialog.
 */
function closeRenameModal() {
    currentRenameSourceId = null;
    document.getElementById('rename-source-modal').classList.add('hidden');
}

/**
 * Submits source rename patch request to backend and updates DOM tile title.
 *
 * @returns {Promise<void>}
 */
async function confirmRenameSource() {
    if (!currentRenameSourceId) return;
    const input = document.getElementById('rename-input');
    const newName = input ? input.value.trim() : '';
    if (!newName) {
        showAppAlert('Filename cannot be empty.', { title: 'Input Required', type: 'warning' });
        return;
    }

    const notebookId = getNotebookIdFromUrl();

    try {
        const response = await fetch(`/notebooks/${notebookId}/sources/${currentRenameSourceId}/rename`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: newName })
        });
        if (!response.ok) throw new Error('Failed to rename source');

        const updatedName = newName;
        const itemLabel = document.querySelector(`label[data-source-id="${currentRenameSourceId}"]`);
        if (itemLabel) {
            itemLabel.setAttribute('title', updatedName);
            itemLabel.setAttribute('data-filename', updatedName);
            const nameDiv = itemLabel.querySelector('.source-filename');
            if (nameDiv) nameDiv.innerText = updatedName;
            const renameBtn = itemLabel.querySelector('button[onclick^="promptRenameSource"]');
            if (renameBtn) renameBtn.setAttribute('onclick', `promptRenameSource(event, '${currentRenameSourceId}', '${escapeHtml(updatedName)}')`);
        }
        closeRenameModal();
    } catch (error) {
        showAppAlert(`Error renaming source: ${error.message}`, { title: 'Rename Failed', type: 'error' });
    }
}

/* ==========================================================================
   SOURCE ACTIONS: DELETION
   ========================================================================== */

let currentDeleteSourceId = null;

/**
 * Opens source deletion modal with scope choice.
 *
 * @param {Event} event - Mouse click event.
 * @param {string} sourceId - Source UUID.
 * @param {string} filename - Filename string.
 */
function promptDeleteSource(event, sourceId, filename) {
    event.preventDefault();
    event.stopPropagation();
    document.querySelectorAll('.source-menu').forEach(m => m.classList.add('hidden'));
    currentDeleteSourceId = sourceId;
    document.getElementById('delete-modal-filename').innerText = `"${filename}"`;
    document.getElementById('delete-source-modal').classList.remove('hidden');
}

/**
 * Closes source deletion modal.
 */
function closeDeleteModal() {
    currentDeleteSourceId = null;
    document.getElementById('delete-source-modal').classList.add('hidden');
}

/**
 * Executes source removal request.
 *
 * @param {string} mode - Removal scope ('notebook' to unlink, 'library' to delete permanently).
 * @returns {Promise<void>}
 */
async function confirmDeleteSource(mode) {
    if (!currentDeleteSourceId) return;
    const sourceId = currentDeleteSourceId;
    const notebookId = getNotebookIdFromUrl();

    try {
        const response = await fetch(`/notebooks/${notebookId}/sources/${sourceId}?mode=${mode}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to remove source');
        const itemLabel = document.querySelector(`label[data-source-id="${sourceId}"]`);
        if (itemLabel) itemLabel.remove();
        updateSourcesCount();
        closeDeleteModal();
    } catch (error) {
        showAppAlert(`Error removing source: ${error.message}`, { title: 'Remove Failed', type: 'error' });
    }
}

/* ==========================================================================
   SELECTION & CLIENT-SIDE SORTING
   ========================================================================== */

/**
 * Toggles selection state of all source document checkboxes in the panel.
 */
function toggleSelectAllSources() {
    const checkboxes = document.querySelectorAll('#sources-list input[type="checkbox"]');
    if (checkboxes.length === 0) return;
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    checkboxes.forEach(cb => cb.checked = !allChecked);
    updateSourcesCount();
}

/**
 * Toggles the sort criteria dropdown menu.
 *
 * @param {Event} e - Mouse click event.
 */
function toggleSortMenu(e) {
    e.preventDefault();
    e.stopPropagation();
    const sortMenu = document.getElementById('sort-menu');
    if (sortMenu) sortMenu.classList.toggle('hidden');
}

/**
 * Sorts document tiles in the panel by name (az), newest (recent), or oldest.
 *
 * @param {string} criteria - Metric key ('az', 'recent', 'oldest').
 */
function sortSources(criteria) {
    const sortMenu = document.getElementById('sort-menu');
    if (sortMenu) sortMenu.classList.add('hidden');
    const sourcesList = document.getElementById('sources-list');
    if (!sourcesList) return;
    const items = Array.from(sourcesList.querySelectorAll('.pdf-item'));

    items.sort((a, b) => {
        const filenameA = (a.dataset.filename || '').toLowerCase();
        const filenameB = (b.dataset.filename || '').toLowerCase();
        const dateA = new Date(a.dataset.createdAt || 0).getTime();
        const dateB = new Date(b.dataset.createdAt || 0).getTime();
        if (criteria === 'az') return filenameA.localeCompare(filenameB);
        if (criteria === 'recent') return dateB - dateA;
        if (criteria === 'oldest') return dateA - dateB;
        return 0;
    });
    items.forEach(item => sourcesList.appendChild(item));
}

/* ==========================================================================
   INGESTION STATUS POLLING (CELERY TASK DETECTOR)
   ========================================================================== */

/**
 * Polls backend for pending document ingestion status every 3 seconds.
 */
function pollSourceStatus() {
    const spinners = document.querySelectorAll('.source-spinner');
    if (spinners.length === 0) return;

    const notebookId = getNotebookIdFromUrl();
    if (!notebookId) return;

    spinners.forEach(spinner => {
        const labelEl = spinner.closest('label');
        const sourceId = labelEl ? labelEl.dataset.sourceId : null;
        if (!sourceId) return;

        fetch(`/notebooks/${notebookId}/sources/${sourceId}/status`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'completed') {
                    const container = spinner.closest('.source-status-container');
                    if (container) {
                        spinner.remove();
                        const checkbox = container.querySelector('input[type="checkbox"]');
                        if (checkbox) {
                            checkbox.classList.remove('hidden');
                            checkbox.checked = true;
                            updateSourcesCount();
                        }
                        const cancelSpan = labelEl.querySelector('.cancel-text');
                        if (cancelSpan) cancelSpan.innerText = "Remove Source";
                        const cancelIcon = labelEl.querySelector('button[onclick^="promptDelete"] .material-symbols-outlined');
                        if (cancelIcon) cancelIcon.innerText = "delete";
                    }
                } else if (data.status === 'failed') {
                    const container = spinner.closest('.source-status-container');
                    if (container) {
                        const filename = labelEl.dataset.filename || 'Document';
                        const errMsg = data.error_message || 'Processing timed out or failed';
                        const safeErr = escapeHtml(errMsg);
                        container.innerHTML = `
                            <span class="material-symbols-outlined text-[20px] text-error dark:text-red-400 cursor-pointer source-error-icon hover:scale-110 transition-transform" onclick="showSourceError(event, '${sourceId}', '${safeErr}')" title="Ingestion Failed: ${safeErr}. Click to retry.">error</span>
                            <input type="checkbox" value="${sourceId}" class="hidden source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0">
                        `;
                        const cancelSpan = labelEl.querySelector('.cancel-text');
                        if (cancelSpan) cancelSpan.innerText = "Remove Source";
                        const cancelIcon = labelEl.querySelector('button[onclick^="promptDelete"] .material-symbols-outlined');
                        if (cancelIcon) cancelIcon.innerText = "delete";

                        showAppAlert(`Document "${filename}" failed processing:\n${errMsg}\n\nYou can retry anytime from the options menu.`, {
                            title: 'Ingestion Failed',
                            type: 'error'
                        });
                    }
                }
            })
            .catch(err => console.error('Error polling status:', err));
    });
}

setInterval(pollSourceStatus, 3000);

/* ==========================================================================
   SOURCE LIST REFRESH
   ========================================================================== */

/**
 * Manually refreshes the sources list from the backend, preserving checkbox states.
 *
 * @returns {Promise<void>}
 */
async function refreshSourcesList() {
    const notebookId = getNotebookIdFromUrl();
    if (!notebookId) return;

    const refreshIcon = document.getElementById('refresh-sources-icon');
    if (refreshIcon) refreshIcon.classList.add('animate-spin');

    try {
        const res = await fetch(`/notebooks/${notebookId}/sources/list`);
        if (!res.ok) throw new Error('Failed to fetch sources');
        const data = await res.json();
        const sources = data.sources || [];

        const sourcesList = document.getElementById('sources-list');
        if (!sourcesList) return;

        // Preserve currently checked state of sources
        const checkedSourceIds = new Set(
            Array.from(document.querySelectorAll('.source-checkbox:checked')).map(cb => cb.value)
        );
        const hadSourcesBefore = document.querySelectorAll('.source-checkbox').length > 0;

        sourcesList.innerHTML = '';
        sources.forEach(source => {
            const sourceId = source.id;
            const filename = source.original_filename || 'Untitled Source';
            const isPending = ['pending', 'processing', 'queued'].includes(source.ingestion_status);
            const createdIso = source.created_at || new Date().toISOString();
            const isChecked = hadSourcesBefore ? checkedSourceIds.has(sourceId) : true;
            const status = source.ingestion_status || 'completed';
            const errorMsg = source.ingestion_error || '';
            sourcesList.insertAdjacentHTML('beforeend', buildSourceItemHtml(sourceId, filename, isPending, createdIso, isChecked, status, errorMsg));
        });

        if (typeof updateSourcesCount === 'function') {
            updateSourcesCount();
        }
        if (typeof populateStudySourcesList === 'function') {
            populateStudySourcesList();
        }
    } catch (err) {
        console.error('Error refreshing sources:', err);
    } finally {
        if (refreshIcon) {
            setTimeout(() => refreshIcon.classList.remove('animate-spin'), 350);
        }
    }
}
window.refreshSourcesList = refreshSourcesList;

/**
 * Retries ingestion for a document that failed or timed out.
 *
 * @param {Event|null} event - DOM event if triggered from a click.
 * @param {string} sourceId - Source UUID.
 * @returns {Promise<void>}
 */
async function retrySourceIngestion(event, sourceId) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const notebookId = getNotebookIdFromUrl();
    if (!notebookId || !sourceId) return;

    // Close any open menus
    document.querySelectorAll('.source-menu').forEach(m => m.classList.add('hidden'));

    const labelEl = document.querySelector(`.pdf-item[data-source-id="${sourceId}"]`);
    const container = labelEl ? labelEl.querySelector('.source-status-container') : null;
    if (container) {
        container.innerHTML = `
            <svg class="animate-spin h-5 w-5 text-secondary dark:text-dark-accent source-spinner" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <input type="checkbox" value="${sourceId}" class="hidden source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0">
        `;
    }

    try {
        const res = await fetch(`/notebooks/${notebookId}/sources/${sourceId}/retry`, {
            method: 'POST'
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || 'Failed to retry ingestion');
        }
        showAppAlert('Ingestion restarted for this document.', { title: 'Retry Triggered', type: 'info' });
    } catch (err) {
        console.error('Error retrying ingestion:', err);
        showAppAlert(err.message || 'Failed to retry ingestion.', { title: 'Retry Failed', type: 'error' });
        if (container) {
            container.innerHTML = `
                <span class="material-symbols-outlined text-[20px] text-error dark:text-red-400 cursor-pointer source-error-icon" onclick="showSourceError(event, '${sourceId}', '${escapeHtml(err.message)}')" title="Ingestion Failed">error</span>
                <input type="checkbox" value="${sourceId}" class="hidden source-checkbox rounded">
            `;
        }
    }
}
window.retrySourceIngestion = retrySourceIngestion;

/**
 * Prompts user with error details and provides one-click retry.
 *
 * @param {Event|null} event - Click event.
 * @param {string} sourceId - Source UUID.
 * @param {string} errorMsg - Ingestion failure description.
 */
async function showSourceError(event, sourceId, errorMsg) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const confirmed = await window.showAppConfirm(
        `This document encountered an error during processing:\n\n"${errorMsg || 'Timeout or connection failure'}"\n\nWould you like to retry processing now?`,
        {
            title: 'Ingestion Error',
            confirmText: 'Retry Processing',
            cancelText: 'Dismiss'
        }
    );
    if (confirmed) {
        retrySourceIngestion(null, sourceId);
    }
}
window.showSourceError = showSourceError;
