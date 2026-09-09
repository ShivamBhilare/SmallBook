/**
 * SmallBook - Workspace UI & Shell Controllers
 * Handles Markdown & KaTeX rendering, Mobile tab switching,
 * Resizable side panel dividers, and panel collapse toggling.
 */
    // Initialize Marked with KaTeX Extension safely
    if (window.marked && window.markedKatex) {
        marked.use(markedKatex({
            throwOnError: false,
            output: 'htmlAndMathml',
            nonStandard: true
        }));
    }

    // Function to safely run KaTeX auto-render on DOM elements as fallback
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

    // Escape HTML Helper Function (CRITICAL FOR UI SECURITY)
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /**
     * Normalizes various mathematical delimiter formats into standard KaTeX/Marked delimiters ($$ and $).
     * Prevents Marked from escaping LaTeX backslashes (e.g. \[ or \() into plain brackets.
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
     * Professional Markdown and Math Parser
     * Replaces the old regex-based formatMarkdownText function.
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

    // Mobile tabs switching
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

    // Panel Resizing Logic
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
    function openPanel(side) {
        const panel = side === 'left' ? document.getElementById('panel-sources') : document.getElementById('panel-studio');
        if (panel.classList.contains('collapsed')) togglePanel(side);
    }

