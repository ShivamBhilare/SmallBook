/**
 * SmallBook - In-Studio Notes Editor & WYSIWYG Scratchpad
 * Rich note editor supporting auto-save, Markdown & KaTeX rendering,
 * interactive task checkboxes, headings, blockquotes, and modal link/math insertion.
 */
    function openNewNoteInStudio() {
        activeNoteId = null;

        // Brief spinner animation on the Notes feature icon for instant feedback
        const noteFeatureIcon = document.querySelector('[onclick*="notes"] .material-symbols-outlined');
        if (noteFeatureIcon) {
            const originalIcon = noteFeatureIcon.innerText;
            noteFeatureIcon.innerText = 'progress_activity';
            noteFeatureIcon.classList.add('animate-spin');
            setTimeout(() => {
                noteFeatureIcon.innerText = originalIcon;
                noteFeatureIcon.classList.remove('animate-spin');
            }, 350);
        }

        const manualView = document.getElementById('manual-note-view');
        const readonlyView = document.getElementById('readonly-note-view');
        if (readonlyView) readonlyView.classList.add('hidden');
        if (manualView) manualView.classList.remove('hidden');

        const titleInput = document.getElementById('note-title-input');
        const contentInput = document.getElementById('note-content-input');
        const saveBtn = document.getElementById('note-btn-save');

        if (titleInput) titleInput.value = '';
        if (contentInput) contentInput.innerHTML = '';
        if (saveBtn) saveBtn.classList.remove('hidden');

        const styleLabel = document.getElementById('note-current-style-label');
        if (styleLabel) styleLabel.innerText = 'Normal';

        updateNoteStatus('New Note', 'bg-secondary dark:bg-dark-accent');
        updateWordCount();

        openStudioViewer('note', 'New Note');
        document.getElementById('studio-fc-container').classList.add('hidden');
        document.getElementById('studio-quiz-container').classList.add('hidden');
        document.getElementById('studio-notes-container').classList.remove('hidden');

        if (contentInput) {
            setTimeout(() => contentInput.focus(), 150);
        }
    }

    async function openNoteInStudio(noteId) {
        // 1. Immediate feedback on tile icon
        const iconContainer = document.getElementById(`note-item-icon-${noteId}`);
        const originalIconHtml = iconContainer ? iconContainer.innerHTML : null;
        if (iconContainer) {
            iconContainer.innerHTML = '<span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>';
        }

        // 2. Open viewer with loading spinner skeleton
        openStudioViewer('note', 'Loading Note...');
        document.getElementById('studio-fc-container').classList.add('hidden');
        document.getElementById('studio-quiz-container').classList.add('hidden');
        document.getElementById('studio-notes-container').classList.remove('hidden');

        const manualView = document.getElementById('manual-note-view');
        const readonlyView = document.getElementById('readonly-note-view');
        if (manualView) manualView.classList.add('hidden');
        if (readonlyView) {
            readonlyView.classList.remove('hidden');
            const titleEl = document.getElementById('readonly-note-title');
            const contentEl = document.getElementById('readonly-note-content');
            if (titleEl) titleEl.innerText = 'Loading...';
            if (contentEl) {
                contentEl.innerHTML = `
                    <div class="flex flex-col items-center justify-center gap-2 py-16">
                        <span class="material-symbols-outlined animate-spin text-[28px] text-secondary dark:text-dark-accent">progress_activity</span>
                        <span class="text-xs font-medium text-on-surface-variant dark:text-dark-text-muted">Loading note...</span>
                    </div>`;
            }
        }
        updateNoteStatus('Loading...', 'bg-amber-500 animate-pulse');

        // 3. Instant render if cached (with tiny visual delay to show click responsiveness)
        if (loadedNotesCache[noteId]) {
            const note = loadedNotesCache[noteId];
            activeNoteId = note.id;
            setTimeout(() => {
                renderNoteInViewer(note);
                if (iconContainer && originalIconHtml) {
                    iconContainer.innerHTML = originalIconHtml;
                }
            }, 120);
            return;
        }

        try {
            const res = await fetch(`/api/notes/${noteId}`);
            if (!res.ok) throw new Error('Could not load note.');
            const note = await res.json();

            loadedNotesCache[noteId] = note;
            activeNoteId = note.id;
            renderNoteInViewer(note);
        } catch (err) {
            console.error(err);
            showAppAlert('Failed to load note.', { title: 'Note Error', type: 'error' });
            closeStudioViewer();
        } finally {
            if (iconContainer && originalIconHtml) {
                iconContainer.innerHTML = originalIconHtml;
            }
        }
    }

    function renderNoteInViewer(note) {
        const isFromChat = Boolean(note.source_message_id);
        const manualView = document.getElementById('manual-note-view');
        const readonlyView = document.getElementById('readonly-note-view');

        openStudioViewer('note', note.title || 'Untitled Note');
        document.getElementById('studio-fc-container').classList.add('hidden');
        document.getElementById('studio-quiz-container').classList.add('hidden');
        document.getElementById('studio-notes-container').classList.remove('hidden');

        if (isFromChat) {
            // Read-only view for notes saved from chat
            if (manualView) manualView.classList.add('hidden');
            if (readonlyView) readonlyView.classList.remove('hidden');

            const titleEl = document.getElementById('readonly-note-title');
            const dateEl = document.getElementById('readonly-note-date');
            const contentEl = document.getElementById('readonly-note-content');

            if (titleEl) titleEl.innerText = note.title || 'Chat Note';
            if (dateEl) dateEl.innerText = formatDateSnippet(note.updated_at || note.created_at);
            if (contentEl) {
                contentEl.innerHTML = formatMarkdownText(note.content || '');
                renderMathSafely(contentEl);
            }
            
            const contentInput = document.getElementById('note-content-input');
            if (contentInput) {
                contentInput.innerHTML = formatMarkdownText(note.content || '');
                renderMathSafely(contentInput);
            }
        } else {
            // Editable WYSIWYG view with toolbar for manual notes
            if (readonlyView) readonlyView.classList.add('hidden');
            if (manualView) manualView.classList.remove('hidden');

            const titleInput = document.getElementById('note-title-input');
            const contentInput = document.getElementById('note-content-input');
            const saveBtn = document.getElementById('note-btn-save');

            if (titleInput) titleInput.value = note.title || '';
            if (contentInput) {
                const raw = note.content || '';
                if (raw.trim().startsWith('<') || raw.includes('</')) {
                    contentInput.innerHTML = raw;
                } else {
                    contentInput.innerHTML = formatMarkdownText(raw);
                    renderMathSafely(contentInput);
                }
            }
            if (saveBtn) saveBtn.classList.add('hidden'); // Auto-save enabled

            updateNoteStatus('Saved', 'bg-green-500');
            updateWordCount();
        }
    }

    function onNoteContentChanged() {
        updateWordCount();
        if (activeNoteId) {
            updateNoteStatus('Saving...', 'bg-amber-500 animate-pulse');
            if (noteAutoSaveTimeout) clearTimeout(noteAutoSaveTimeout);
            noteAutoSaveTimeout = setTimeout(() => {
                saveActiveNote(true);
            }, 800);
        } else {
            updateNoteStatus('New Note', 'bg-secondary dark:bg-dark-accent');
        }
    }

    function updateWordCount() {
        const contentInput = document.getElementById('note-content-input');
        const countEl = document.getElementById('note-word-count');
        if (!contentInput || !countEl) return;
        const text = (contentInput.innerText || '').trim();
        const words = text ? text.split(/\s+/).length : 0;
        countEl.innerText = `${words} word${words === 1 ? '' : 's'}`;
    }

    function updateNoteStatus(text, dotClass = 'bg-green-500') {
        const statusEl = document.getElementById('note-status-text');
        const dotEl = document.getElementById('note-status-indicator')?.firstElementChild;
        if (statusEl) statusEl.innerText = text;
        if (dotEl) dotEl.className = `w-1.5 h-1.5 rounded-full ${dotClass}`;
    }

    async function saveActiveNote(isAutoSave = false) {
        const notebookId = getNotebookIdFromUrl();
        if (!notebookId) return;

        const titleInput = document.getElementById('note-title-input');
        const contentInput = document.getElementById('note-content-input');
        const saveBtnText = document.getElementById('note-save-text');
        const saveIcon = document.getElementById('note-save-icon');

        const title = (titleInput ? titleInput.value.trim() : '') || 'Untitled Note';
        const content = contentInput ? contentInput.innerHTML : '';

        if (!isAutoSave) {
            if (saveBtnText) saveBtnText.innerText = 'Saving...';
            if (saveIcon) saveIcon.classList.add('animate-spin');
        }

        try {
            let note;
            if (activeNoteId) {
                // Update existing manual note
                const res = await fetch(`/api/notes/${activeNoteId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: title, content: content })
                });
                if (!res.ok) throw new Error('Failed to update note.');
                note = await res.json();
            } else {
                // Create new manual note
                const res = await fetch(`/notebooks/${notebookId}/notes`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: title, content: content })
                });
                if (!res.ok) throw new Error('Failed to create note.');
                note = await res.json();
                activeNoteId = note.id;
                
                // Hide manual Save Note button now that note is saved; auto-save takes over
                const saveBtn = document.getElementById('note-btn-save');
                if (saveBtn) saveBtn.classList.add('hidden');
            }

            loadedNotesCache[note.id] = note;
            document.getElementById('studio-viewer-title').innerText = note.title || 'Untitled Note';
            updateNoteStatus('Saved', 'bg-green-500');

            // Refresh study tools artifacts list
            loadNotebookStudyTools(false);
        } catch (err) {
            console.error("Save note error:", err);
            if (!isAutoSave) showAppAlert("Could not save note.", { title: 'Save Failed', type: 'error' });
            updateNoteStatus('Save failed', 'bg-error');
        } finally {
            if (!isAutoSave) {
                if (saveBtnText) saveBtnText.innerText = 'Save Note';
                if (saveIcon) saveIcon.classList.remove('animate-spin');
            }
        }
    }

    function promptDeleteCurrentNote() {
        if (!activeNoteId) return;
        const manualTitle = document.getElementById('note-title-input')?.value;
        const readonlyTitle = document.getElementById('readonly-note-title')?.innerText;
        const title = manualTitle || readonlyTitle || 'Untitled Note';
        promptDeleteStudyTool('note', activeNoteId, title);
    }

    function copyActiveNoteContent(btn) {
        const contentInput = document.getElementById('note-content-input');
        if (!contentInput) return;
        const text = contentInput.innerText || contentInput.textContent || '';
        if (!text) return;
        navigator.clipboard.writeText(text).catch(err => {
            console.error('Copy failed:', err);
        });
    }

    // ==========================================
    // TOOLBAR FORMATTING HELPERS (WYSIWYG)
    // ==========================================

    function updateActiveToolbarStates() {
        const editor = document.getElementById('note-content-input');
        if (!editor) return;

        // 1. Bold State
        const isBold = document.queryCommandState('bold');
        const btnBold = document.getElementById('note-btn-bold');
        if (btnBold) {
            if (isBold) {
                btnBold.classList.add('bg-secondary/15', 'dark:bg-dark-accent/25', 'text-secondary', 'dark:text-dark-accent', 'font-bold', 'ring-1', 'ring-secondary/30');
            } else {
                btnBold.classList.remove('bg-secondary/15', 'dark:bg-dark-accent/25', 'text-secondary', 'dark:text-dark-accent', 'font-bold', 'ring-1', 'ring-secondary/30');
            }
        }

        // 2. Italic State
        const isItalic = document.queryCommandState('italic');
        const btnItalic = document.getElementById('note-btn-italic');
        if (btnItalic) {
            if (isItalic) {
                btnItalic.classList.add('bg-secondary/15', 'dark:bg-dark-accent/25', 'text-secondary', 'dark:text-dark-accent', 'font-bold', 'ring-1', 'ring-secondary/30');
            } else {
                btnItalic.classList.remove('bg-secondary/15', 'dark:bg-dark-accent/25', 'text-secondary', 'dark:text-dark-accent', 'font-bold', 'ring-1', 'ring-secondary/30');
            }
        }

        // 3. Block Style State (Heading / List / Quote)
        const formatBlock = (document.queryCommandValue('formatBlock') || '').toLowerCase();
        const isBullet = document.queryCommandState('insertUnorderedList');
        const isNumber = document.queryCommandState('insertOrderedList');
        const styleLabel = document.getElementById('note-current-style-label');

        if (styleLabel) {
            if (isBullet) styleLabel.innerText = 'Bullet List';
            else if (isNumber) styleLabel.innerText = 'Numbered List';
            else if (formatBlock === 'h1' || formatBlock === 'heading 1') styleLabel.innerText = 'Heading 1';
            else if (formatBlock === 'h2' || formatBlock === 'heading 2') styleLabel.innerText = 'Heading 2';
            else if (formatBlock === 'h3' || formatBlock === 'heading 3') styleLabel.innerText = 'Heading 3';
            else if (formatBlock === 'blockquote') styleLabel.innerText = 'Quote';
            else styleLabel.innerText = 'Normal';
        }
    }

    function applyToolbarFormat(format) {
        const editor = document.getElementById('note-content-input');
        if (!editor) return;
        editor.focus();

        if (format === 'undo') {
            document.execCommand('undo', false, null);
        } else if (format === 'redo') {
            document.execCommand('redo', false, null);
        } else if (format === 'bold') {
            document.execCommand('bold', false, null);
        } else if (format === 'italic') {
            document.execCommand('italic', false, null);
        } else if (format === 'code') {
            const sel = window.getSelection();
            if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
                const range = sel.getRangeAt(0);
                const codeEl = document.createElement('code');
                codeEl.className = 'px-1.5 py-0.5 rounded bg-surface-variant/60 dark:bg-dark-border text-secondary dark:text-dark-accent font-mono text-xs';
                codeEl.textContent = range.toString();
                range.deleteContents();
                range.insertNode(codeEl);
            } else {
                document.execCommand('insertHTML', false, '<code class="px-1.5 py-0.5 rounded bg-surface-variant/60 dark:bg-dark-border text-secondary dark:text-dark-accent font-mono text-xs">code</code>&nbsp;');
            }
        } else if (format === 'codeblock') {
            document.execCommand('insertHTML', false, '<pre class="p-3 rounded-xl bg-surface-variant/70 dark:bg-dark-panel border border-paper dark:border-dark-border font-mono text-xs my-2"><code>// code block here\n</code></pre><p><br></p>');
        } else if (format === 'task') {
            const taskHtml = '<ul class="task-list pl-0 list-none my-1.5"><li class="task-list-item flex items-start gap-2 my-1"><input type="checkbox" onchange="toggleTaskCheckbox(this)" class="task-checkbox mt-1 w-4 h-4 rounded text-secondary focus:ring-secondary cursor-pointer" contenteditable="false"/><span class="task-text flex-1 outline-none">Task item</span></li></ul><p><br></p>';
            document.execCommand('insertHTML', false, taskHtml);
        } else if (format === 'hr') {
            document.execCommand('insertHorizontalRule', false, null);
        }

        onNoteContentChanged();
        updateActiveToolbarStates();
        closeAllNoteMenus();
    }

    function toggleTaskCheckbox(cb) {
        const textSpan = cb.parentElement?.querySelector('.task-text');
        if (textSpan) {
            if (cb.checked) {
                textSpan.classList.add('line-through', 'opacity-60');
            } else {
                textSpan.classList.remove('line-through', 'opacity-60');
            }
        }
        onNoteContentChanged();
    }

    function handleNoteEditorKeydown(e) {
        if (e.key === 'Enter') {
            const sel = window.getSelection();
            if (!sel || sel.rangeCount === 0) return;
            const node = sel.anchorNode;
            
            // Check if cursor is currently inside a task list item
            const taskItem = node.nodeType === Node.ELEMENT_NODE 
                ? node.closest('.task-list-item') 
                : node.parentElement?.closest('.task-list-item');
                
            if (taskItem) {
                e.preventDefault();
                const textSpan = taskItem.querySelector('.task-text');
                const text = textSpan ? textSpan.innerText.trim() : taskItem.innerText.trim();
                const parentUl = taskItem.closest('.task-list') || taskItem.parentElement;
                
                if (!text) {
                    // If task item was empty, break out to a normal paragraph
                    const p = document.createElement('p');
                    p.innerHTML = '<br>';
                    
                    if (parentUl && parentUl.nextSibling) {
                        parentUl.parentNode.insertBefore(p, parentUl.nextSibling);
                    } else if (parentUl) {
                        parentUl.parentNode.appendChild(p);
                    } else {
                        taskItem.parentNode.insertBefore(p, taskItem.nextSibling);
                    }
                    taskItem.remove();
                    
                    const range = document.createRange();
                    range.setStart(p, 0);
                    range.collapse(true);
                    sel.removeAllRanges();
                    sel.addRange(range);
                } else {
                    // Insert a new task item on the next line
                    const li = document.createElement('li');
                    li.className = 'task-list-item flex items-start gap-2 my-1';
                    li.innerHTML = '<input type="checkbox" onchange="toggleTaskCheckbox(this)" class="task-checkbox mt-1 w-4 h-4 rounded text-secondary focus:ring-secondary cursor-pointer" contenteditable="false"/><span class="task-text flex-1 outline-none"><br></span>';
                    
                    if (taskItem.nextSibling) {
                        taskItem.parentNode.insertBefore(li, taskItem.nextSibling);
                    } else {
                        taskItem.parentNode.appendChild(li);
                    }
                    
                    const newSpan = li.querySelector('.task-text');
                    const range = document.createRange();
                    range.setStart(newSpan, 0);
                    range.collapse(true);
                    sel.removeAllRanges();
                    sel.addRange(range);
                }
                onNoteContentChanged();
                return;
            }
        }
    }

    function selectStyleFormat(tag, label) {
        const editor = document.getElementById('note-content-input');
        const styleLabel = document.getElementById('note-current-style-label');
        if (styleLabel) styleLabel.innerText = label;
        if (!editor) return;
        editor.focus();

        if (tag === 'h1') {
            document.execCommand('formatBlock', false, '<h1>');
        } else if (tag === 'h2') {
            document.execCommand('formatBlock', false, '<h2>');
        } else if (tag === 'h3') {
            document.execCommand('formatBlock', false, '<h3>');
        } else if (tag === 'p') {
            document.execCommand('formatBlock', false, '<p>');
        } else if (tag === 'bullet') {
            document.execCommand('insertUnorderedList', false, null);
        } else if (tag === 'number') {
            document.execCommand('insertOrderedList', false, null);
        } else if (tag === 'quote') {
            document.execCommand('formatBlock', false, '<blockquote>');
        }

        onNoteContentChanged();
        updateActiveToolbarStates();
        closeAllNoteMenus();
    }

    function toggleStyleDropdown(event) {
        if (event) event.stopPropagation();
        const menu = document.getElementById('note-style-menu');
        const moreMenu = document.getElementById('note-more-menu');
        if (moreMenu) moreMenu.classList.add('hidden');
        if (menu) menu.classList.toggle('hidden');
    }

    function toggleMoreMenu(event) {
        if (event) event.stopPropagation();
        const menu = document.getElementById('note-more-menu');
        const styleMenu = document.getElementById('note-style-menu');
        if (styleMenu) styleMenu.classList.add('hidden');
        if (menu) menu.classList.toggle('hidden');
    }

    function closeAllNoteMenus() {
        const styleMenu = document.getElementById('note-style-menu');
        const moreMenu = document.getElementById('note-more-menu');
        if (styleMenu) styleMenu.classList.add('hidden');
        if (moreMenu) moreMenu.classList.add('hidden');
    }

    document.addEventListener('click', () => {
        closeAllNoteMenus();
    });

    document.addEventListener('selectionchange', () => {
        const sel = window.getSelection();
        const editor = document.getElementById('note-content-input');
        if (editor && sel.anchorNode && editor.contains(sel.anchorNode)) {
            updateActiveToolbarStates();
        }
    });

    // ==========================================
    // CUSTOM IN-APP LINK & MATH MODAL CONTROLLERS
    // ==========================================

    let savedNoteEditorRange = null;
    let savedSelectedText = '';

    function saveNoteSelectionRange() {
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
            savedNoteEditorRange = sel.getRangeAt(0).cloneRange();
            savedSelectedText = sel.toString();
        } else {
            savedNoteEditorRange = null;
            savedSelectedText = '';
        }
    }

    function restoreNoteSelectionRange() {
        const editor = document.getElementById('note-content-input');
        if (editor) editor.focus();
        if (savedNoteEditorRange) {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(savedNoteEditorRange);
        }
    }

    function openNoteLinkModal() {
        saveNoteSelectionRange();
        const modal = document.getElementById('note-link-modal');
        const textInput = document.getElementById('note-link-text-input');
        const urlInput = document.getElementById('note-link-url-input');
        
        if (textInput) textInput.value = savedSelectedText || '';
        if (urlInput) urlInput.value = '';
        
        if (modal) modal.classList.remove('hidden');
        if (urlInput) setTimeout(() => (savedSelectedText ? urlInput : textInput || urlInput).focus(), 100);
    }

    function closeNoteLinkModal() {
        const modal = document.getElementById('note-link-modal');
        if (modal) modal.classList.add('hidden');
    }

    function confirmInsertLink() {
        const textInput = document.getElementById('note-link-text-input');
        const urlInput = document.getElementById('note-link-url-input');
        
        let url = (urlInput ? urlInput.value.trim() : '');
        if (!url) {
            closeNoteLinkModal();
            return;
        }
        if (!/^https?:\/\//i.test(url) && !url.startsWith('#') && !url.startsWith('/')) {
            url = 'https://' + url;
        }
        
        const displayText = (textInput ? textInput.value.trim() : '') || savedSelectedText || url;
        
        closeNoteLinkModal();
        restoreNoteSelectionRange();
        
        const linkHtml = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="text-secondary dark:text-dark-accent underline font-medium hover:opacity-80">${escapeHtml(displayText)}</a>&nbsp;`;
        document.execCommand('insertHTML', false, linkHtml);
        
        onNoteContentChanged();
        updateActiveToolbarStates();
    }

    function openNoteMathModal() {
        saveNoteSelectionRange();
        const modal = document.getElementById('note-math-modal');
        const input = document.getElementById('note-math-formula-input');
        if (input) {
            input.value = savedSelectedText || '';
        }
        updateNoteMathPreview();
        if (modal) modal.classList.remove('hidden');
        if (input) setTimeout(() => input.focus(), 100);
    }

    function closeNoteMathModal() {
        const modal = document.getElementById('note-math-modal');
        if (modal) modal.classList.add('hidden');
    }

    function updateNoteMathPreview() {
        const input = document.getElementById('note-math-formula-input');
        const preview = document.getElementById('note-math-preview');
        if (!preview) return;
        const formula = input ? input.value.trim() : '';
        if (!formula) {
            preview.innerHTML = '<span class="text-on-surface-variant/50 text-[11px]">Type formula above...</span>';
            return;
        }
        try {
            if (window.katex) {
                preview.innerHTML = window.katex.renderToString(formula, { throwOnError: false, displayMode: false });
            } else {
                preview.innerText = formula;
            }
        } catch (e) {
            preview.innerText = formula;
        }
    }

    function confirmInsertMath() {
        const input = document.getElementById('note-math-formula-input');
        const formula = (input ? input.value.trim() : '') || 'E = mc^2';
        closeNoteMathModal();
        restoreNoteSelectionRange();

        let mathRendered = '';
        if (window.katex) {
            try {
                mathRendered = window.katex.renderToString(formula, { throwOnError: false, displayMode: false });
            } catch (e) {
                mathRendered = escapeHtml(formula);
            }
        } else {
            mathRendered = escapeHtml(formula);
        }

        // Insert as an atomic rendered visual KaTeX chip
        const chipHtml = `<span class="katex-note-chip inline-block px-1.5 py-0.5 mx-0.5 rounded bg-secondary/10 dark:bg-dark-accent/15 border border-secondary/20 dark:border-dark-accent/20 align-middle font-sans text-xs" contenteditable="false" data-formula="${escapeHtml(formula)}" title="Formula: ${escapeHtml(formula)}">${mathRendered}</span>&nbsp;`;
        document.execCommand('insertHTML', false, chipHtml);

        onNoteContentChanged();
        updateActiveToolbarStates();
    }

