/**
 * @fileoverview Studio Tools Hub Controller for SmallBook.
 * Coordinates Flashcard and Quiz generation dispatch, Celery background task polling,
 * unified artifacts list rendering (notes, flashcard decks, quizzes), optimistic deletion,
 * right studio panel viewer transitions, and chat message save-to-note actions.
 */

/* =========================================================================
   STUDY TOOLS & GENERATOR CONTROLLER (FLASHCARDS & QUIZZES)
   ========================================================================= */

/** @type {string} Active study generation type ('flashcards' | 'quiz'). */
let activeStudyType = 'flashcards';

/** @type {number} Active target count of items to generate. */
let activeStudyCount = 10;

/** @type {boolean} Flag tracking whether a generation request is currently inflight. */
let isGeneratingStudyTool = false;

// Flashcard Viewer State
/** @type {Object|null} Currently active flashcard deck object being practiced. */
let currentDeck = null;

/** @type {number} Zero-based index of the card currently displayed in the deck viewer. */
let currentCardIndex = 0;

/** @type {boolean} State tracking whether the current flashcard is flipped to reveal its back. */
let isCardFlipped = false;

// Quiz Player State
/** @type {Object|null} Currently active practice quiz object. */
let currentQuiz = null;

/** @type {number} Zero-based index of the question currently displayed in the quiz player. */
let currentQuizQuestionIndex = 0;

/** @type {Object<number, number>} Map of question index to user selected option index. */
let userQuizAnswers = {};

/** @type {boolean} Whether the quiz has been submitted and scored. */
let isQuizSubmitted = false;

/**
 * Opens the study tool generation modal for flashcards or practice quizzes.
 * Immediately renders the modal with available sources without waiting on network roundtrips.
 *
 * @param {string} [toolType='flashcards'] - Generation tool type ('flashcards' or 'quiz').
 */
function openStudyModal(toolType = 'flashcards') {
    // 1. Immediately open modal without blocking on network roundtrip
    setStudyType(toolType);
    populateStudySourcesList();
    document.getElementById('study-custom-prompt').value = '';
    const hintEl = document.getElementById('study-lock-hint');
    if (hintEl) hintEl.innerText = 'Free developer tier';
    document.getElementById('study-generator-modal').classList.remove('hidden');

    // 2. Non-blocking asynchronous cooldown check to update footer hint if active
    checkStudyModalCooldownAsync(toolType);
}

/**
 * Queries the background cooldown API asynchronously to update the modal footer hint.
 *
 * @async
 * @param {string} toolType - Generation tool type ('flashcards' | 'quiz').
 * @returns {Promise<void>}
 */
async function checkStudyModalCooldownAsync(toolType) {
    const hintEl = document.getElementById('study-lock-hint');
    const notebookId = getNotebookIdFromUrl();
    if (!notebookId || !hintEl) return;

    try {
        const res = await fetch(`/notebooks/${notebookId}/study/cooldown?tool_type=${toolType}`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.active && data.remaining_seconds > 0) {
            const remMins = data.remaining_minutes || Math.max(1, Math.round(data.remaining_seconds / 60));
            hintEl.innerHTML = `<span class="text-amber-600 dark:text-amber-400 font-medium flex items-center gap-1"><span class="material-symbols-outlined text-[14px]">hourglass_top</span>Cooldown: ${remMins}m remaining</span>`;
        }
    } catch (e) {
        // Ignore background check errors
    }
}

/**
 * Closes the study tool generation modal if generation is not actively inflight.
 */
function closeStudyModal() {
    if (isGeneratingStudyTool) return;
    document.getElementById('study-generator-modal').classList.add('hidden');
}

/**
 * Toggles the modal configuration between flashcard and quiz generation modes.
 *
 * @param {string} type - 'flashcards' or 'quiz'.
 */
function setStudyType(type) {
    activeStudyType = type;
    const btnText = document.getElementById('study-btn-text');
    const icon = document.getElementById('study-gen-icon');
    const title = document.getElementById('study-gen-title');
    const subtitle = document.getElementById('study-gen-subtitle');
    const promptInput = document.getElementById('study-custom-prompt');

    if (type === 'flashcards') {
        if (btnText) btnText.innerText = "Generate Flashcards";
        if (icon) icon.innerText = "style";
        if (title) title.innerText = "Create Flashcards";
        if (subtitle) subtitle.innerText = "Auto-generate grounded flashcards from document";
        if (promptInput) promptInput.placeholder = "e.g. Focus on definitions, key concepts, formulas...";
    } else {
        if (btnText) btnText.innerText = "Generate Quiz";
        if (icon) icon.innerText = "school";
        if (title) title.innerText = "Create Practice Quiz";
        if (subtitle) subtitle.innerText = "Auto-generate comprehensive MCQs with explanations";
        if (promptInput) promptInput.placeholder = "e.g. Focus on multiple choice questions from Chapter 3, high difficulty...";
    }
}

/**
 * Populates the modal source selection radio list by reading uploaded document nodes from the DOM.
 */
function populateStudySourcesList() {
    const listEl = document.getElementById('study-sources-radio-list');
    if (!listEl) return;

    const sourceItems = document.querySelectorAll('#sources-list .pdf-item');
    if (sourceItems.length === 0) {
        listEl.innerHTML = `
            <div class="text-center py-4 text-xs text-on-surface-variant dark:text-dark-text-muted">
                No documents uploaded yet. Please add a PDF source first.
            </div>`;
        return;
    }

    let html = '';
    sourceItems.forEach((item, index) => {
        const sid = item.dataset.sourceId;
        const sname = item.dataset.filename || 'Document';
        const checked = index === 0 ? 'checked' : '';
        html += `
            <label class="flex items-center justify-between p-2.5 rounded-xl border border-paper dark:border-dark-border hover:bg-surface-variant/40 dark:hover:bg-dark-panel-hover cursor-pointer transition-colors group">
                <div class="flex items-center gap-2 min-w-0 pr-2">
                    <input type="radio" name="study_source_selection" value="${sid}" ${checked} class="text-secondary dark:text-dark-accent focus:ring-secondary dark:focus:ring-dark-accent flex-shrink-0">
                    <span class="text-xs font-medium text-on-surface dark:text-dark-text truncate">${escapeHtml(sname)}</span>
                </div>
                <span class="material-symbols-outlined text-[16px] text-error dark:text-red-400 flex-shrink-0">picture_as_pdf</span>
            </label>
        `;
    });
    listEl.innerHTML = html;
}

/** @type {Set<string>} Tracked IDs of flashcard sets to detect newly completed background generations. */
let knownFlashcardIds = new Set();

/** @type {Set<string>} Tracked IDs of practice quizzes to detect newly completed background generations. */
let knownQuizIds = new Set();

/** @type {Set<string>} Tracked IDs of notes. */
let knownNoteIds = new Set();

/** @type {{notes: Array<Object>, flashcard_sets: Array<Object>, quizzes: Array<Object>, artifacts?: Array<Object>}} In-memory cached artifacts. */
let cachedStudyToolsData = { notes: [], flashcard_sets: [], quizzes: [] };

/** @type {Object<string, {type: string, sourceId: string, docName: string, timestamp: number}>} Active background generation tracking map. */
let pendingStudyGenerations = {};

/** @type {number|null} Interval ID for polling background Celery generation progress. */
let studyToolsPollInterval = null;

/** @type {{type: string, id: string}|null} Item pending delete confirmation. */
let itemPendingDelete = null;

/**
 * Submits a study tool generation request to the API backend.
 * Upon 202 Accepted response, registers an optimistic pending tile and initiates Celery polling.
 *
 * @async
 * @returns {Promise<void>}
 */
async function submitGenerateStudyTool() {
    const selectedRadio = document.querySelector('input[name="study_source_selection"]:checked');
    if (!selectedRadio) {
        showAppAlert('Please select a source document first to generate study tools.', {
            title: 'Document Required',
            type: 'info',
            icon: 'description'
        });
        return;
    }

    const sourceId = selectedRadio.value;
    const customPrompt = document.getElementById('study-custom-prompt').value.trim();
    const notebookId = getNotebookIdFromUrl();
    const toolType = activeStudyType;

    // Find selected source name for UI display
    const radioLabel = selectedRadio.closest('label');
    const docName = radioLabel ? radioLabel.querySelector('span.truncate')?.innerText || 'Document' : 'Document';

    const btn = document.getElementById('btn-generate-study');
    const spinner = document.getElementById('study-btn-spinner');
    if (btn) btn.disabled = true;
    if (spinner) spinner.classList.remove('hidden');

    try {
        const response = await fetch(`/notebooks/${notebookId}/study/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_id: sourceId,
                tool_type: toolType,
                custom_prompt: customPrompt || null,
                num_items: activeStudyCount || 10
            })
        });

        if (btn) btn.disabled = false;
        if (spinner) spinner.classList.add('hidden');

        if (response.status === 429) {
            const errData = await response.json().catch(() => ({}));
            closeStudyModal();
            showAppAlert(errData.detail || "Cooldown active: Please wait before generating another set.", {
                title: "Cooldown Active",
                type: "warning",
                icon: "hourglass_top",
                buttonText: "Understood"
            });
            return;
        }

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            closeStudyModal();
            showAppAlert(errData.detail || "Generation failed to start.", {
                title: "Generation Failed",
                type: "error"
            });
            return;
        }

        // Confirmed 202 Accepted: Close modal and add pending spinner tile
        closeStudyModal();
        const genKey = `${toolType}_${sourceId}_${Date.now()}`;
        pendingStudyGenerations[genKey] = { type: toolType, sourceId: sourceId, docName: docName, timestamp: Date.now() };
        renderStudyTools(cachedStudyToolsData);

        // Start background polling to detect when generated artifact appears
        startStudyToolsPolling();

    } catch (error) {
        console.error("Study generation dispatch error:", error);
        if (btn) btn.disabled = false;
        if (spinner) spinner.classList.add('hidden');
        closeStudyModal();
        showAppAlert(error.message || 'Generation failed to start.', {
            title: "Generation Error",
            type: "error"
        });
    }
}

/**
 * Starts periodic polling (every 2.5s) to detect completed study tool generations.
 */
function startStudyToolsPolling() {
    if (studyToolsPollInterval) return;
    studyToolsPollInterval = setInterval(async () => {
        if (Object.keys(pendingStudyGenerations).length === 0) {
            clearInterval(studyToolsPollInterval);
            studyToolsPollInterval = null;
            return;
        }
        await loadNotebookStudyTools(true);
    }, 2500);
}

/**
 * Formats an ISO datetime string into a concise human-readable relative date label.
 *
 * @param {string} isoStr - ISO timestamp string.
 * @returns {string} Formatted date snippet ('Just now', 'Recently', or 'MMM D').
 */
function formatDateSnippet(isoStr) {
    if (!isoStr) return 'Just now';
    try {
        const d = new Date(isoStr);
        if (isNaN(d.getTime())) return 'Recently';
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
        return 'Recently';
    }
}

/**
 * Fetches and updates all study tools (notes, flashcard decks, quizzes) for the active notebook.
 *
 * @async
 * @param {boolean} [isFromPolling=false] - Whether this invocation originated from the background poller.
 * @returns {Promise<void>}
 */
async function loadNotebookStudyTools(isFromPolling = false) {
    const notebookId = getNotebookIdFromUrl();
    const container = document.getElementById('study-tools-container');
    if (!container) return;

    try {
        const response = await fetch(`/notebooks/${notebookId}/study/items`);
        if (!response.ok) return;
        const data = await response.json();

        const notes = data.notes || [];
        const flashcardSets = data.flashcard_sets || [];
        const quizzes = data.quizzes || [];

        if (!isFromPolling) {
            // Initial load: populate known IDs
            notes.forEach(n => knownNoteIds.add(n.id));
            flashcardSets.forEach(s => knownFlashcardIds.add(s.id));
            quizzes.forEach(q => knownQuizIds.add(q.id));
        } else {
            notes.forEach(n => knownNoteIds.add(n.id));
            // Polling: detect new items
            for (const deck of flashcardSets) {
                if (!knownFlashcardIds.has(deck.id)) {
                    knownFlashcardIds.add(deck.id);
                    // Find matching pending generation to clear
                    for (const [key, gen] of Object.entries(pendingStudyGenerations)) {
                        if (gen.type === 'flashcards' && gen.sourceId === deck.source_id) {
                            delete pendingStudyGenerations[key];
                            break;
                        }
                    }
                }
            }

            for (const quiz of quizzes) {
                if (!knownQuizIds.has(quiz.id)) {
                    knownQuizIds.add(quiz.id);
                    for (const [key, gen] of Object.entries(pendingStudyGenerations)) {
                        if (gen.type === 'quiz' && gen.sourceId === quiz.source_id) {
                            delete pendingStudyGenerations[key];
                            break;
                        }
                    }
                }
            }

            // Check for timed out pending generations (180s)
            const now = Date.now();
            const TIMEOUT_MS = 180000;
            let timedOutCount = 0;
            for (const [key, gen] of Object.entries(pendingStudyGenerations)) {
                if (now - (gen.timestamp || now) > TIMEOUT_MS) {
                    delete pendingStudyGenerations[key];
                    timedOutCount++;
                }
            }
            if (timedOutCount > 0) {
                showAppAlert('Study tool generation timed out after 3 minutes due to slow network or high server load. Please try again.', {
                    title: 'Generation Timed Out',
                    type: 'warning',
                    icon: 'hourglass_disabled'
                });
            }

            // If all finished or timed out, stop polling
            if (Object.keys(pendingStudyGenerations).length === 0 && studyToolsPollInterval) {
                clearInterval(studyToolsPollInterval);
                studyToolsPollInterval = null;
            }
        }

        cachedStudyToolsData = {
            notes: notes,
            flashcard_sets: flashcardSets,
            quizzes: quizzes,
            artifacts: data.artifacts || []
        };
        renderStudyTools(cachedStudyToolsData);

    } catch (e) {
        console.warn("Could not load study tools:", e);
    }
}

/**
 * Manually refreshes the studio tools list with a spin animation on the refresh button icon.
 *
 * @async
 * @returns {Promise<void>}
 */
async function refreshStudyTools() {
    const refreshIcon = document.getElementById('refresh-study-tools-icon');
    if (refreshIcon) refreshIcon.classList.add('animate-spin');
    try {
        await loadNotebookStudyTools(false);
    } catch (err) {
        console.error("Error refreshing study tools:", err);
    } finally {
        if (refreshIcon) {
            setTimeout(() => refreshIcon.classList.remove('animate-spin'), 350);
        }
    }
}
window.refreshStudyTools = refreshStudyTools;

/** @type {string} Active artifact sorting mode ('modified_desc' | 'created_desc' | 'title_asc'). */
let currentArtifactSort = 'modified_desc';

/**
 * Updates the artifact sort preference and re-renders the studio tools container.
 *
 * @param {string} newSort - Selected sort key.
 */
function changeArtifactSort(newSort) {
    currentArtifactSort = newSort;
    if (cachedStudyToolsData) {
        renderStudyTools(cachedStudyToolsData);
    }
}

/**
 * Renders the unified list of artifacts (notes, flashcard decks, quizzes, and pending tasks) into the DOM.
 *
 * @param {Object} data - Studio tools data payload.
 */
function renderStudyTools(data) {
    const container = document.getElementById('study-tools-container');
    if (!container) return;

    data = data || {};
    const notes = data.notes || [];
    const flashcardSets = data.flashcard_sets || [];
    const quizzes = data.quizzes || [];
    const hasPending = Object.keys(pendingStudyGenerations).length > 0;

    // Build unified artifacts array
    let artifacts = [];
    notes.forEach(n => {
        artifacts.push({
            type: 'note',
            id: n.id,
            title: n.title || 'Untitled Note',
            created_at: n.created_at,
            updated_at: n.updated_at,
            raw: n
        });
    });
    flashcardSets.forEach(deck => {
        artifacts.push({
            type: 'flashcards',
            id: deck.id,
            title: deck.title || 'Flashcards',
            cards_count: deck.cards_count || 0,
            created_at: deck.created_at,
            updated_at: deck.updated_at,
            raw: deck
        });
    });
    quizzes.forEach(quiz => {
        artifacts.push({
            type: 'quiz',
            id: quiz.id,
            title: quiz.title || 'Practice Quiz',
            questions_count: quiz.questions_count || 0,
            created_at: quiz.created_at,
            updated_at: quiz.updated_at,
            raw: quiz
        });
    });

    if (artifacts.length === 0 && !hasPending) {
        container.innerHTML = `
            <div class="text-center py-6 text-xs text-on-surface-variant dark:text-dark-text-muted flex flex-col items-center gap-2">
                <span class="material-symbols-outlined text-[28px] text-on-surface-variant/40">school</span>
                <p class="font-medium">No study tools created yet.</p>
                <p class="text-[11px] text-on-surface-variant/60">Click Flashcards, Quiz, or Notes above to create one.</p>
            </div>`;
        return;
    }

    // Sort artifacts according to currentArtifactSort
    artifacts.sort((a, b) => {
        if (currentArtifactSort === 'created_desc') {
            const timeA = new Date(a.created_at || a.updated_at || 0).getTime();
            const timeB = new Date(b.created_at || b.updated_at || 0).getTime();
            return timeB - timeA;
        } else if (currentArtifactSort === 'title_asc') {
            return (a.title || '').localeCompare(b.title || '');
        } else {
            // Default: 'modified_desc' (most recently modified/created first)
            const timeA = new Date(a.updated_at || a.created_at || 0).getTime();
            const timeB = new Date(b.updated_at || b.created_at || 0).getTime();
            return timeB - timeA;
        }
    });

    let html = '';

    // 1. Render Active Pending Background Spinner Tiles
    for (const [genKey, info] of Object.entries(pendingStudyGenerations)) {
        let pendingTitle = 'Generating Practice Quiz...';
        let pendingSubtitle = `Analyzing ${escapeHtml(info.docName || 'Document')}`;
        if (info.type === 'note') {
            pendingTitle = 'Saving Note...';
            pendingSubtitle = escapeHtml(info.docName || 'Chat Note');
        } else if (info.type === 'flashcards') {
            pendingTitle = 'Generating Flashcards...';
            pendingSubtitle = `Analyzing ${escapeHtml(info.docName || 'Document')}`;
        }
        html += `
            <div id="pending-tile-${genKey}" onclick="handleStudyToolTileClick('${info.type}', null, event)" class="study-tool-tile p-3 bg-surface-bright dark:bg-dark-bg border border-secondary/50 dark:border-dark-accent/50 rounded-xl flex items-center justify-between animate-pulse mb-2 shadow-sm cursor-pointer">
                <div class="flex items-center gap-2.5 min-w-0 pr-2 flex-1">
                    <div class="w-8 h-8 rounded-lg bg-secondary/10 dark:bg-dark-accent/10 flex items-center justify-center text-secondary dark:text-dark-accent flex-shrink-0">
                        <span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>
                    </div>
                    <div class="study-tool-content min-w-0 flex-1">
                        <div class="text-xs font-semibold text-on-surface dark:text-dark-text truncate">${pendingTitle}</div>
                        <div class="text-[10px] text-secondary dark:text-dark-accent truncate font-medium">${pendingSubtitle}</div>
                    </div>
                </div>
            </div>`;
    }

    // 2. Render Unified Sorted Artifacts
    artifacts.forEach(art => {
        if (art.type === 'note') {
            html += `
                <div id="note-item-${art.id}" onclick="handleStudyToolTileClick('note', '${art.id}', event)" class="study-tool-tile p-3 bg-surface-bright dark:bg-dark-bg border border-paper dark:border-dark-border rounded-xl flex items-center justify-between hover:border-secondary dark:hover:border-dark-accent transition-colors group mb-2 cursor-pointer">
                    <div class="flex items-center gap-2.5 min-w-0 pr-2 flex-1">
                        <div id="note-item-icon-${art.id}" class="w-8 h-8 rounded-lg bg-secondary/10 dark:bg-dark-accent/10 flex items-center justify-center text-secondary dark:text-dark-accent flex-shrink-0">
                            <span class="material-symbols-outlined text-[18px]">sticky_note_2</span>
                        </div>
                        <div class="study-tool-content min-w-0 flex-1">
                            <div class="text-xs font-semibold text-on-surface dark:text-dark-text truncate group-hover:text-secondary dark:group-hover:text-dark-accent transition-colors">${escapeHtml(art.title)}</div>
                            <div class="text-[10px] text-on-surface-variant dark:text-dark-text-muted">
                                <span>Note</span>
                            </div>
                        </div>
                    </div>
                    <div class="study-tool-actions flex items-center gap-1 flex-shrink-0">
                        <button type="button" onclick="handleStudyToolTileClick('note', '${art.id}', event)" title="Open Note" class="w-7 h-7 flex items-center justify-center rounded-full text-secondary dark:text-dark-accent hover:bg-secondary/15 dark:hover:bg-dark-accent/15 transition-colors flex-shrink-0 aspect-square">
                            <span class="material-symbols-outlined text-[18px]">edit_note</span>
                        </button>
                        <button type="button" onclick="promptDeleteStudyTool('note', '${art.id}', '${escapeHtml(art.title)}', event)" title="Delete Note" class="opacity-0 group-hover:opacity-100 w-7 h-7 flex items-center justify-center rounded-full text-error dark:text-red-400 hover:bg-error/15 dark:hover:bg-red-400/15 transition-all flex-shrink-0 aspect-square">
                            <span class="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                    </div>
                </div>`;
        } else if (art.type === 'flashcards') {
            html += `
                <div id="card-deck-${art.id}" onclick="handleStudyToolTileClick('flashcards', '${art.id}', event)" class="study-tool-tile p-3 bg-surface-bright dark:bg-dark-bg border border-paper dark:border-dark-border rounded-xl flex items-center justify-between hover:border-secondary dark:hover:border-dark-accent transition-colors group mb-2 cursor-pointer">
                    <div class="flex items-center gap-2.5 min-w-0 pr-2 flex-1">
                        <div id="card-deck-icon-${art.id}" class="w-8 h-8 rounded-lg bg-secondary/10 dark:bg-dark-accent/10 flex items-center justify-center text-secondary dark:text-dark-accent flex-shrink-0">
                            <span class="material-symbols-outlined text-[18px]">style</span>
                        </div>
                        <div class="study-tool-content min-w-0 flex-1">
                            <div class="text-xs font-semibold text-on-surface dark:text-dark-text truncate group-hover:text-secondary dark:group-hover:text-dark-accent transition-colors">${escapeHtml(art.title)}</div>
                            <div class="text-[10px] text-on-surface-variant dark:text-dark-text-muted">
                                <span>${art.cards_count || 0} cards</span>
                            </div>
                        </div>
                    </div>
                    <div class="study-tool-actions flex items-center gap-1 flex-shrink-0">
                        <button type="button" onclick="handleStudyToolTileClick('flashcards', '${art.id}', event)" title="Practice Deck" class="w-7 h-7 flex items-center justify-center rounded-full text-secondary dark:text-dark-accent hover:bg-secondary/15 dark:hover:bg-dark-accent/15 transition-colors flex-shrink-0 aspect-square">
                            <span class="material-symbols-outlined text-[18px]">play_arrow</span>
                        </button>
                        <button type="button" onclick="promptDeleteStudyTool('flashcards', '${art.id}', '${escapeHtml(art.title)}', event)" title="Delete Deck" class="opacity-0 group-hover:opacity-100 w-7 h-7 flex items-center justify-center rounded-full text-error dark:text-red-400 hover:bg-error/15 dark:hover:bg-red-400/15 transition-all flex-shrink-0 aspect-square">
                            <span class="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                    </div>
                </div>`;
        } else if (art.type === 'quiz') {
            html += `
                <div id="quiz-item-${art.id}" onclick="handleStudyToolTileClick('quiz', '${art.id}', event)" class="study-tool-tile p-3 bg-surface-bright dark:bg-dark-bg border border-paper dark:border-dark-border rounded-xl flex items-center justify-between hover:border-secondary dark:hover:border-dark-accent transition-colors group mb-2 cursor-pointer">
                    <div class="flex items-center gap-2.5 min-w-0 pr-2 flex-1">
                        <div id="quiz-item-icon-${art.id}" class="w-8 h-8 rounded-lg bg-green-500/10 dark:bg-green-400/10 flex items-center justify-center text-green-600 dark:text-green-400 flex-shrink-0">
                            <span class="material-symbols-outlined text-[18px]">school</span>
                        </div>
                        <div class="study-tool-content min-w-0 flex-1">
                            <div class="text-xs font-semibold text-on-surface dark:text-dark-text truncate group-hover:text-green-600 dark:group-hover:text-green-400 transition-colors">${escapeHtml(art.title)}</div>
                            <div class="text-[10px] text-on-surface-variant dark:text-dark-text-muted">
                                <span>${art.questions_count || 0} questions</span>
                            </div>
                        </div>
                    </div>
                    <div class="study-tool-actions flex items-center gap-1 flex-shrink-0">
                        <button type="button" onclick="handleStudyToolTileClick('quiz', '${art.id}', event)" title="Take Quiz" class="w-7 h-7 flex items-center justify-center rounded-full text-green-600 dark:text-green-400 hover:bg-green-500/15 transition-colors flex-shrink-0 aspect-square">
                            <span class="material-symbols-outlined text-[18px]">play_arrow</span>
                        </button>
                        <button type="button" onclick="promptDeleteStudyTool('quiz', '${art.id}', '${escapeHtml(art.title)}', event)" title="Delete Quiz" class="opacity-0 group-hover:opacity-100 w-7 h-7 flex items-center justify-center rounded-full text-error dark:text-red-400 hover:bg-error/15 dark:hover:bg-red-400/15 transition-all flex-shrink-0 aspect-square">
                            <span class="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                    </div>
                </div>`;
        }
    });

    container.innerHTML = html;
}

/* =========================================================================
   STUDIO PANEL EXPANSION & VIEW CONTROLLERS
   ========================================================================= */

/** @type {string|null} ID of note currently opened in studio viewer. */
let activeNoteId = null;

/** @type {string} Active note editing mode ('edit' | 'preview'). */
let activeNoteMode = 'edit';

/** @type {Object<string, Object>} In-memory cache of fully loaded note objects by ID. */
let loadedNotesCache = {};

/** @type {Object<string, Object>} In-memory cache of fully loaded flashcard deck objects by ID. */
let loadedDecksCache = {};

/** @type {Object<string, Object>} In-memory cache of fully loaded quiz objects by ID. */
let loadedQuizzesCache = {};

/**
 * Handles clicks on header feature launcher buttons (Notes, Flashcards, Quiz).
 *
 * @param {string} type - Feature identifier ('notes' | 'flashcards' | 'quiz').
 */
function handleFeatureItemClick(type) {
    const studio = document.getElementById('panel-studio');
    if (studio && studio.classList.contains('collapsed')) {
        openPanel('right');
        return;
    }
    if (type === 'notes') {
        openNewNoteInStudio();
    } else {
        openStudyModal(type);
    }
}

/**
 * Handles tile clicks on individual study items in the studio panel list.
 *
 * @param {string} type - 'note', 'flashcards', or 'quiz'.
 * @param {string|null} id - Artifact primary key (null for pending tiles).
 * @param {Event} [event] - Originating DOM click event.
 */
function handleStudyToolTileClick(type, id, event) {
    if (event) event.stopPropagation();
    const studio = document.getElementById('panel-studio');
    if (studio && studio.classList.contains('collapsed')) {
        openPanel('right');
        return;
    }
    if (!id) return; // pending tile
    if (type === 'note') {
        openNoteInStudio(id);
    } else if (type === 'flashcards') {
        openFlashcardInStudio(id);
    } else if (type === 'quiz') {
        openQuizInStudio(id);
    }
}

/**
 * Opens the active studio viewer panel with custom title and icon, expanding the panel width.
 *
 * @param {string} type - Viewer content type ('note' | 'flashcards' | 'quiz').
 * @param {string} title - Header title text to display in the viewer banner.
 */
function openStudioViewer(type, title) {
    openPanel('right');
    // Slide chat by slightly expanding studio panel (from 320px to 440px, ~8-10% slide)
    document.documentElement.style.setProperty('--right-panel-width', '440px');

    document.getElementById('studio-main-view').classList.add('hidden');
    const activeViewer = document.getElementById('studio-active-viewer');
    activeViewer.classList.remove('hidden');
    activeViewer.classList.add('flex');

    let iconName = 'style';
    if (type === 'note') iconName = 'edit_note';
    else if (type === 'quiz') iconName = 'school';

    document.getElementById('studio-viewer-icon').innerText = iconName;
    document.getElementById('studio-viewer-title').innerText = title;
}

/**
 * Closes the active studio viewer panel and restores the standard studio panel width.
 */
function closeStudioViewer() {
    // Restore standard studio panel width
    document.documentElement.style.setProperty('--right-panel-width', '320px');
    isStudioWide = false;
    const expandIcon = document.getElementById('studio-expand-icon');
    if (expandIcon) expandIcon.innerText = 'open_in_full';

    const activeViewer = document.getElementById('studio-active-viewer');
    activeViewer.classList.add('hidden');
    activeViewer.classList.remove('flex');
    document.getElementById('studio-main-view').classList.remove('hidden');

    document.getElementById('studio-fc-container').classList.add('hidden');
    document.getElementById('studio-quiz-container').classList.add('hidden');
    document.getElementById('studio-notes-container').classList.add('hidden');

    currentDeck = null;
    currentQuiz = null;
    activeNoteId = null;
}

/* =========================================================================
   CUSTOM DELETE CONFIRMATION & OPTIMISTIC UI
   ========================================================================= */

/**
 * Opens the confirmation modal for deleting a study artifact.
 *
 * @param {string} type - Artifact type ('note' | 'flashcards' | 'quiz').
 * @param {string} id - Artifact primary key.
 * @param {string} title - Display title for modal confirmation message.
 * @param {Event} [event] - Originating DOM click event.
 */
function promptDeleteStudyTool(type, id, title, event) {
    if (event) event.stopPropagation();
    itemPendingDelete = { type, id };
    
    let modalTitle = 'Delete Artifact';
    if (type === 'note') modalTitle = 'Delete Note';
    else if (type === 'flashcards') modalTitle = 'Delete Flashcards';
    else if (type === 'quiz') modalTitle = 'Delete Quiz';

    document.getElementById('delete-study-modal-title').innerText = modalTitle;
    document.getElementById('delete-study-modal-desc').innerText = `Are you sure you want to delete "${title}"? This cannot be undone.`;
    document.getElementById('delete-study-tool-modal').classList.remove('hidden');
}

/**
 * Cancels and closes the artifact deletion modal.
 */
function closeDeleteStudyModal() {
    itemPendingDelete = null;
    document.getElementById('delete-study-tool-modal').classList.add('hidden');
}

/**
 * Executes artifact deletion with instant optimistic UI update followed by backend deletion API call.
 *
 * @async
 * @returns {Promise<void>}
 */
async function executeDeleteStudyTool() {
    if (!itemPendingDelete) return;
    const { type, id } = itemPendingDelete;
    
    closeDeleteStudyModal();

    // If currently open note is deleted, close viewer
    if (type === 'note' && activeNoteId === id) {
        closeStudioViewer();
    }

    // 1. Instant Optimistic Removal from UI
    if (type === 'note') {
        if (cachedStudyToolsData.notes) {
            cachedStudyToolsData.notes = cachedStudyToolsData.notes.filter(n => n.id !== id);
        }
        knownNoteIds.delete(id);
        delete loadedNotesCache[id];
    } else if (type === 'flashcards') {
        cachedStudyToolsData.flashcard_sets = cachedStudyToolsData.flashcard_sets.filter(s => s.id !== id);
        knownFlashcardIds.delete(id);
        delete loadedDecksCache[id];
    } else {
        cachedStudyToolsData.quizzes = cachedStudyToolsData.quizzes.filter(q => q.id !== id);
        knownQuizIds.delete(id);
        delete loadedQuizzesCache[id];
    }
    renderStudyTools(cachedStudyToolsData);

    // 2. Perform backend delete
    let endpoint = `/api/study/flashcards/${id}`;
    if (type === 'note') endpoint = `/api/notes/${id}`;
    else if (type === 'quiz') endpoint = `/api/study/quizzes/${id}`;

    try {
        const res = await fetch(endpoint, { method: 'DELETE' });
        if (!res.ok) {
            console.error("Delete failed on server, re-syncing items.");
            loadNotebookStudyTools(false);
        }
    } catch (err) {
        console.error("Delete network error:", err);
        loadNotebookStudyTools(false);
    }
}

/** @type {number|null} Debounce timer handle for note auto-saving. */
let noteAutoSaveTimeout = null;

/** @type {boolean} State tracking whether studio viewer panel is expanded to wide mode (680px). */
let isStudioWide = false;

/**
 * Toggles the studio viewer between default width (440px) and wide full-screen width (680px).
 */
function toggleStudioViewerWidth() {
    isStudioWide = !isStudioWide;
    const expandIcon = document.getElementById('studio-expand-icon');
    if (isStudioWide) {
        document.documentElement.style.setProperty('--right-panel-width', '680px');
        if (expandIcon) expandIcon.innerText = 'close_fullscreen';
    } else {
        document.documentElement.style.setProperty('--right-panel-width', '440px');
        if (expandIcon) expandIcon.innerText = 'open_in_full';
    }
}

/* =========================================================================
   CHAT MESSAGE: SAVE TO NOTE & COPY ACTIONS
   ========================================================================= */

/**
 * Extracts AI response message text from the chat bubble and saves it as a notebook note.
 * Optimistically adds a pending generation tile in the studio panel while saving.
 *
 * @async
 * @param {HTMLElement} btn - Button element clicked within the chat bubble action bar.
 * @returns {Promise<void>}
 */
async function saveMessageToNote(btn) {
    const msgDiv = btn.closest('[data-message-id]');
    const sourceMessageId = msgDiv ? msgDiv.getAttribute('data-message-id') : null;

    const msgBubble = btn.closest('.flex-1');
    if (!msgBubble) return;
    const textContainer = msgBubble.querySelector('.ai-text-content');
    if (!textContainer) return;
    
    const content = textContainer.innerText.trim();
    if (!content) return;

    const notebookId = getNotebookIdFromUrl();
    if (!notebookId) return;

    // Clean note title from first line / heading
    const firstLine = content.split('\n')[0].replace(/^#+\s*/, '').trim();
    const title = (firstLine.length > 40 ? firstLine.slice(0, 40) + '...' : firstLine) || 'Chat Note';

    // 1. Immediately register pending generation tile in Studio with loading spinner
    const genKey = `note_${Date.now()}`;
    pendingStudyGenerations[genKey] = { type: 'note', docName: title, timestamp: Date.now() };

    // Expand studio panel if collapsed and re-render tiles so loading spinner tile appears immediately!
    const studio = document.getElementById('panel-studio');
    if (studio && studio.classList.contains('collapsed')) {
        openPanel('right');
    }
    renderStudyTools(cachedStudyToolsData);

    try {
        const res = await fetch(`/notebooks/${notebookId}/notes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                content: content,
                source_message_id: sourceMessageId || null
            })
        });

        if (!res.ok) throw new Error('Failed to save note.');
        const savedNote = await res.json();

        // Clear pending generation tile
        delete pendingStudyGenerations[genKey];

        // Add to cache & update UI
        loadedNotesCache[savedNote.id] = savedNote;
        if (!cachedStudyToolsData.notes) cachedStudyToolsData.notes = [];
        cachedStudyToolsData.notes.unshift(savedNote);
        knownNoteIds.add(savedNote.id);
        renderStudyTools(cachedStudyToolsData);

        // Open note in studio immediately (renders as read-only chat note)
        openNoteInStudio(savedNote.id);
    } catch (err) {
        console.error("Save note error:", err);
        delete pendingStudyGenerations[genKey];
        renderStudyTools(cachedStudyToolsData);
        showAppAlert("Could not save note to database.", { title: 'Save Failed', type: 'error' });
    }
}

/**
 * Initializes the study workspace by triggering the initial load of all notebook study tools.
 */
function initStudyWorkspace() {
    loadNotebookStudyTools();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStudyWorkspace);
} else {
    initStudyWorkspace();
}
