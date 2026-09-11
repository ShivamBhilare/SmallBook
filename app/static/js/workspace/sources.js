/**
 * SmallBook - Sources Management Controller
 * Handles PDF uploads, drag-and-drop, global library linking,
 * source document renaming, permanent deletion, sorting, and Celery status polling.
 */
    /* -------------------------------------------------------------------------
       UI & MODAL LOGIC (RESTORED)
    ------------------------------------------------------------------------- */
    let isUploading = false;

    function openUploadModal() {
        document.getElementById('upload-modal').classList.remove('hidden');
    }

    function closeUploadModal() {
        if (isUploading) return; 
        document.getElementById('upload-modal').classList.add('hidden');
        resetUploadUI();
    }

    function resetUploadUI() {
        document.getElementById('drop-zone-content').classList.remove('opacity-0', 'pointer-events-none');
        document.getElementById('upload-progress').classList.add('hidden');
        document.getElementById('upload-spinner').classList.remove('hidden');
        document.getElementById('upload-success-icon').classList.add('hidden');
        document.getElementById('upload-title').innerText = "Uploading...";
        document.getElementById('upload-subtitle').innerText = "Please wait";
        switchUploadTab('upload');
    }

    let librarySourcesData = [];

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

    function filterLibraryChecklist() {
        const existingSourceIds = new Set();
        document.querySelectorAll('.pdf-item[data-source-id]').forEach(el => {
            const sid = el.getAttribute('data-source-id');
            if (sid) existingSourceIds.add(sid);
        });
        renderLibraryChecklist(existingSourceIds);
    }

    function updateLibrarySelectedCount() {
        const checkboxes = document.querySelectorAll('.library-source-checkbox:not(:disabled):checked');
        const count = checkboxes.length;
        const countEl = document.getElementById('library-selected-count');
        const btn = document.getElementById('btn-submit-link-sources');
        
        if (countEl) countEl.innerText = `${count} source${count === 1 ? '' : 's'} selected`;
        if (btn) btn.disabled = count === 0;
    }

    function selectAllLibraryChecklist() {
        const unlinkedCheckboxes = document.querySelectorAll('.library-source-checkbox:not(:disabled)');
        const allChecked = Array.from(unlinkedCheckboxes).every(cb => cb.checked);
        unlinkedCheckboxes.forEach(cb => cb.checked = !allChecked);
        updateLibrarySelectedCount();
    }

    function buildSourceItemHtml(sourceId, filename, isPending = false, nowIso = new Date().toISOString(), isChecked = true) {
        const safeFilename = escapeHtml(filename);
        const checkedAttr = isChecked ? 'checked' : '';
        const statusHtml = isPending
            ? `<svg class="animate-spin h-5 w-5 text-secondary dark:text-dark-accent source-spinner" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <input type="checkbox" value="${sourceId}" class="hidden source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0">`
            : `<input ${checkedAttr} class="source-checkbox rounded border-outline-variant dark:border-dark-border dark:bg-dark-bg text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0" type="checkbox" value="${sourceId}">`;

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

    function formatBytesJs(bytes) {
        if (!bytes || bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

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

            document.getElementById('upload-title').innerText = `Uploading ${i + 1} of ${files.length}`;
            document.getElementById('upload-subtitle').innerText = file.name;

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await fetch(`/notebooks/${notebookId}/sources/upload`, {
                    method: 'POST',
                    body: formData
                });
                let result = await response.json();
                if (!response.ok) throw new Error(result.detail || 'Failed to upload source.');
                
                const filename = result.filename || file.name;
                const sourceId = result.source_id || '';
                const nowIso = new Date().toISOString();
                const sourcesList = document.getElementById('sources-list');
                if (sourcesList) {
                    sourcesList.insertAdjacentHTML('beforeend', buildSourceItemHtml(sourceId, filename, true, nowIso));
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

    // Source Item Menus
    function toggleSourceMenu(event, sourceId) {
        event.preventDefault();
        event.stopPropagation();
        const targetMenu = document.getElementById(`source-menu-${sourceId}`);
        document.querySelectorAll('.source-menu').forEach(menu => {
            if (menu !== targetMenu) menu.classList.add('hidden');
        });
        if (targetMenu) targetMenu.classList.toggle('hidden');
    }

    // Rename Source Logic
    let currentRenameSourceId = null;
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
    function closeRenameModal() {
        currentRenameSourceId = null;
        document.getElementById('rename-source-modal').classList.add('hidden');
    }
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

    // Delete Source Logic
    let currentDeleteSourceId = null;
    function promptDeleteSource(event, sourceId, filename) {
        event.preventDefault();
        event.stopPropagation();
        document.querySelectorAll('.source-menu').forEach(m => m.classList.add('hidden'));
        currentDeleteSourceId = sourceId;
        document.getElementById('delete-modal-filename').innerText = `"${filename}"`;
        document.getElementById('delete-source-modal').classList.remove('hidden');
    }
    function closeDeleteModal() {
        currentDeleteSourceId = null;
        document.getElementById('delete-source-modal').classList.add('hidden');
    }
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

    function toggleSelectAllSources() {
        const checkboxes = document.querySelectorAll('#sources-list input[type="checkbox"]');
        if (checkboxes.length === 0) return;
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);
        checkboxes.forEach(cb => cb.checked = !allChecked);
        updateSourcesCount();
    }

    function toggleSortMenu(e) {
        e.preventDefault();
        e.stopPropagation();
        const sortMenu = document.getElementById('sort-menu');
        if (sortMenu) sortMenu.classList.toggle('hidden');
    }

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


    // Polling logic for Celery source ingestion processing status
    function pollSourceStatus() {
        const spinners = document.querySelectorAll('.source-spinner');
        if (spinners.length === 0) return;

        const notebookId = getNotebookIdFromUrl();
        if (!notebookId) return;

        spinners.forEach(spinner => {
            const labelEl = spinner.closest('label');
            const sourceId = labelEl.dataset.sourceId;
            if (!sourceId) return;

            fetch(`/notebooks/${notebookId}/sources/${sourceId}/status`)
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'completed' || data.status === 'failed') {
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
                    }
                })
                .catch(err => console.error('Error polling status:', err));
        });
    }

    setInterval(pollSourceStatus, 3000);
 
    // Refresh Sources List on demand
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
                sourcesList.insertAdjacentHTML('beforeend', buildSourceItemHtml(sourceId, filename, isPending, createdIso, isChecked));
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
