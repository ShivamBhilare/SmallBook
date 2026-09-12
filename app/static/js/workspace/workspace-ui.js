/**
 * @fileoverview Workspace UI & Shell Controllers.
 * Configures Marked markdown parsing with KaTeX mathematics extensions, DOM sanitization,
 * mobile bottom navigation tab switching, bidirectional resizable panel dividers,
 * and collapsible panel sidebar toggles.
 */

/* ==========================================================================
   MARKDOWN & KATEX INITIALIZATION
   ========================================================================== */

// Initialize Marked with KaTeX Extension safely
if (window.marked && window.markedKatex) {
    marked.use(markedKatex({
        throwOnError: false,
        output: 'htmlAndMathml',
        nonStandard: true
    }));
}

/**
 * Safely renders LaTeX mathematical notation on DOM elements via KaTeX auto-render.
 *
 * @param {HTMLElement} element - Target DOM element containing raw math delimiters.
 */
function renderMathSafely(element) {
    if (window.renderMathInElement && element) {
        try {
            renderMathInElement(element, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false },
                    { left: '\\(', right: '\\)', display: false },
                    { left: '\\[', right: '\\]', display: true }
                ],
                throwOnError: false
            });
        } catch (e) {
            console.error("KaTeX auto-render error:", e);
        }
    }
}

/* ==========================================================================
   DOM & WORKSPACE URL UTILITIES
   ========================================================================== */

/**
 * Extracts the active notebook UUID from the current window location path (/workspace/{notebook_id}).
 *
 * @returns {string} Extracted notebook UUID, or empty string if not found.
 */
function getNotebookIdFromUrl() {
    const pathSegments = window.location.pathname.split('/');
    const wsIndex = pathSegments.indexOf('workspace');
    if (wsIndex !== -1 && pathSegments[wsIndex + 1]) {
        return pathSegments[wsIndex + 1];
    }
    return '';
}
window.getNotebookIdFromUrl = getNotebookIdFromUrl;

/**
 * Sanitizes and escapes raw strings for safe HTML DOM insertion.
 *
 * @param {string|unknown} str - Raw text string.
 * @returns {string} Escaped HTML string safe from XSS.
 */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
window.escapeHtml = escapeHtml;
window.renderMathSafely = renderMathSafely;

/* ==========================================================================
   SOURCE SELECTION & BADGE COUNTERS
   ========================================================================== */

/**
 * Collects UUIDs of all currently checked source documents in the panel.
 *
 * @returns {Array<string>} List of selected source UUID strings.
 */
function getSelectedSourceIds() {
    const checked = document.querySelectorAll('.source-checkbox:checked');
    return Array.from(checked).map(cb => cb.value).filter(Boolean);
}
window.getSelectedSourceIds = getSelectedSourceIds;

/**
 * Updates the badge counter reflecting selected source documents.
 */
function updateSourcesCount() {
    const checked = document.querySelectorAll('.source-checkbox:checked');
    const countSpan = document.getElementById('sources-count');
    if (countSpan) countSpan.innerText = checked.length;
}
window.updateSourcesCount = updateSourcesCount;

document.addEventListener('change', (e) => {
    if (e.target && e.target.classList.contains('source-checkbox')) {
        updateSourcesCount();
    }
});

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updateSourcesCount);
} else {
    updateSourcesCount();
}

/* ==========================================================================
   LATEX MATH DELIMITER NORMALIZATION
   ========================================================================== */

/**
 * Normalizes various mathematical delimiter formats into standard KaTeX/Marked delimiters ($$ and $).
 * Prevents Marked from escaping LaTeX backslashes (e.g. \[ or \() into plain brackets.
 *
 * @param {string} text - Raw input text containing LaTeX math.
 * @returns {string} Processed text with standardized math delimiters.
 */
function normalizeMathDelimiters(text) {
    if (!text) return '';
    let processed = text;

    // 1. Explicit LaTeX display math: \[ ... \] -> \n\n$$\n...\n$$\n\n
    processed = processed.replace(/\\\[([\s\S]*?)\\\]/g, (match, formula) => {
        return '\n\n$$\n' + formula.trim() + '\n$$\n\n';
    });

    // 2. Explicit LaTeX inline math: \( ... \) -> $...$
    processed = processed.replace(/\\\(([\s\S]*?)\\\)/g, (match, formula) => {
        return '$' + formula.trim() + '$';
    });

    // 3. Standalone bracketed display math on separate lines:
    // Matches [ ... \macro ... ] or lines with LaTeX commands
    processed = processed.replace(/(?:^|\n)\s*\[\s*([\s\S]*?\\(?:frac|sum|prod|int|sqrt|boxed|mid|cap|cup|displaystyle|mathbf|math|alpha|beta|gamma|theta|sigma|mu|times|cdot|approx|equiv|le|ge|neq|quad|qquad|text|dots)[\s\S]*?)\s*\]\s*(?=\n|$)/g, (match, formula) => {
        return '\n\n$$\n' + formula.trim() + '\n$$\n\n';
    });

    // 4. Standalone bracketed lines containing equality relations:
    // E.g. [ P(A\mid B)P(B) = P(B\mid A)P(A). ]
    processed = processed.replace(/(?:^|\n)\s*\[\s*([^\[\]\n]*?=[^\[\]\n]*?)\s*\]\s*(?=\n|$)/g, (match, formula) => {
        return '\n\n$$\n' + formula.trim() + '\n$$\n\n';
    });

    return processed;
}

/**
 * Formats Markdown and LaTeX math formulas into sanitized, rendered HTML.
 *
 * @param {string} text - Raw Markdown or math text.
 * @returns {string} Sanitized, rendered HTML string.
 */
function formatMarkdownText(text) {
    if (!text) return '';

    // 1. Normalize math delimiters so Marked & KaTeX detect them properly
    const normalizedText = normalizeMathDelimiters(text);

    // 2. Parse markdown (including math via KaTeX extension)
    let rawHtml = '';
    try {
        rawHtml = marked.parse(normalizedText);
    } catch (e) {
        console.error("Markdown parsing error:", e);
        rawHtml = escapeHtml(text); // Fallback
    }

    // 3. Sanitize HTML
    const cleanHtml = DOMPurify.sanitize(rawHtml, {
        ADD_TAGS: [
            'math', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'msup', 'msub',
            'munderover', 'munder', 'mover', 'mfrac', 'msqrt', 'mroot', 'mfenced',
            'mphantom', 'mtext', 'mspace', 'maction', 'maligngroup', 'malignmark',
            'menclose', 'merror', 'mglyph', 'mlabeledtr', 'mlongdiv', 'mmultiscripts',
            'mscarries', 'mscarry', 'msgroup', 'msline', 'msrow', 'mstack', 'mstyle',
            'mtable', 'mtd', 'mtr', 'annotation', 'annotation-xml'
        ],
        ADD_ATTR: [
            'class', 'style', 'aria-hidden', 'mathvariant', 'encoding', 'display', 'xmlns'
        ]
    });

    return cleanHtml;
}

/* ==========================================================================
   DROPDOWN OUTSIDE-CLICK LISTENERS
   ========================================================================== */

// Dismiss action menus when clicking outside
document.addEventListener('click', function(e) {
    if (!e.target.closest('.source-menu') && !e.target.closest('button[onclick^="toggleSourceMenu"]')) {
        document.querySelectorAll('.source-menu').forEach(m => m.classList.add('hidden'));
    }
    if (!e.target.closest('#sort-menu') && !e.target.closest('button[onclick^="toggleSortMenu"]')) {
        const sortMenu = document.getElementById('sort-menu');
        if (sortMenu) sortMenu.classList.add('hidden');
    }
    const modelMenu = document.getElementById('model-dropdown-menu');
    if (modelMenu && !modelMenu.classList.contains('hidden') && !e.target.closest('#model-dropdown-container')) {
        modelMenu.classList.add('hidden');
    }
});

/* ==========================================================================
   MOBILE TAB SWITCHING (< 1024px)
   ========================================================================== */

/**
 * Switches the active panel tab in mobile viewport layouts.
 *
 * @param {string} tabName - Target tab identifier ('sources', 'chat', or 'studio').
 */
function switchTab(tabName) {
    document.querySelectorAll('[role="tab"]').forEach(tab => {
        tab.setAttribute('aria-selected', tab.id === `tab-${tabName}` ? 'true' : 'false');
    });
    ['sources', 'chat', 'studio'].forEach(id => {
        const panel = document.getElementById(`panel-${id}`);
        if (id === tabName) panel.classList.add('active-tab');
        else panel.classList.remove('active-tab');
    });
}

/* ==========================================================================
   PANEL RESIZING CONTROLLERS
   ========================================================================== */

let isResizingLeft = false, isResizingRight = false, startX = 0, startWidth = 0;
const resizerLeft = document.getElementById('resizer-left');
const resizerRight = document.getElementById('resizer-right');

if (resizerLeft && resizerRight) {
    resizerLeft.addEventListener('mousedown', (e) => {
        isResizingLeft = true; startX = e.clientX;
        startWidth = document.getElementById('panel-sources').getBoundingClientRect().width;
        document.body.style.cursor = 'col-resize';
        document.body.classList.add('select-none', 'is-resizing');
        e.preventDefault();
    });
    resizerRight.addEventListener('mousedown', (e) => {
        isResizingRight = true; startX = e.clientX;
        startWidth = document.getElementById('panel-studio').getBoundingClientRect().width;
        document.body.style.cursor = 'col-resize';
        document.body.classList.add('select-none', 'is-resizing');
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
        if (isResizingLeft) {
            let newWidth = startWidth + (e.clientX - startX);
            if (newWidth < 200) newWidth = 200;
            if (newWidth > 600) newWidth = 600;
            document.documentElement.style.setProperty('--left-panel-width', `${newWidth}px`);
        }
        if (isResizingRight) {
            let newWidth = startWidth + (startX - e.clientX);
            if (newWidth < 200) newWidth = 200;
            if (newWidth > 600) newWidth = 600;
            document.documentElement.style.setProperty('--right-panel-width', `${newWidth}px`);
        }
    });
    document.addEventListener('mouseup', () => {
        isResizingLeft = false; isResizingRight = false;
        document.body.style.cursor = 'default';
        document.body.classList.remove('select-none', 'is-resizing');
    });
}

/* ==========================================================================
   PANEL COLLAPSE & EXPAND TOGGLES
   ========================================================================== */

/**
 * Toggles a side panel between collapsed icon-only bar and expanded width.
 *
 * @param {string} side - Side identifier ('left' for sources, 'right' for studio).
 */
function togglePanel(side) {
    const panel = side === 'left' ? document.getElementById('panel-sources') : document.getElementById('panel-studio');
    const resizer = side === 'left' ? document.getElementById('resizer-left') : document.getElementById('resizer-right');
    const icon = side === 'left' ? document.getElementById('collapse-icon-left') : document.getElementById('collapse-icon-right');

    panel.classList.toggle('collapsed');
    if (panel.classList.contains('collapsed')) {
        resizer.style.display = 'none';
        icon.innerText = side === 'left' ? 'keyboard_double_arrow_right' : 'keyboard_double_arrow_left';
    } else {
        resizer.style.display = '';
        icon.innerText = side === 'left' ? 'keyboard_double_arrow_left' : 'keyboard_double_arrow_right';
    }
}

/**
 * Expands a panel if it is currently collapsed.
 *
 * @param {string} side - Side identifier ('left' or 'right').
 */
function openPanel(side) {
    const panel = side === 'left' ? document.getElementById('panel-sources') : document.getElementById('panel-studio');
    if (panel.classList.contains('collapsed')) togglePanel(side);
}

window.togglePanel = togglePanel;
window.openPanel = openPanel;
window.switchTab = switchTab;
window.formatMarkdownText = formatMarkdownText;
