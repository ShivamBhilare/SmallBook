/**
 * SmallBook - Chat & LLM Inference Controller
 * Handles chat prompt dispatch, SSE token streaming, Markdown formatting,
 * grounded citation tooltips, prompt branching, and model selection.
 */
    /* -------------------------------------------------------------------------
       CHAT SETTINGS & LLM DROPDOWNS
    ------------------------------------------------------------------------- */
    let currentPromptMode = 'hybrid';
    let currentResponseLength = 'default';
    let currentLlmModel = 'gemini/gemini-2.5-flash';
    let tempPromptMode = 'hybrid';
    let tempResponseLength = 'default';

    function openConfigureChatModal() {
        tempPromptMode = currentPromptMode;
        tempResponseLength = currentResponseLength;
        selectConfigMode(tempPromptMode);
        selectConfigLength(tempResponseLength);
        document.getElementById('configure-chat-modal').classList.remove('hidden');
    }
    function closeConfigureChatModal() { document.getElementById('configure-chat-modal').classList.add('hidden'); }
    function saveChatConfiguration() {
        currentPromptMode = tempPromptMode;
        currentResponseLength = tempResponseLength;
        closeConfigureChatModal();
    }
    function selectConfigMode(mode) {
        tempPromptMode = mode;
        ['strict', 'hybrid', 'concise'].forEach(m => {
            const pill = document.getElementById(`pill-mode-${m}`);
            if (!pill) return;
            const checkIcon = pill.querySelector('.pill-check');
            const descSpan = pill.querySelector('span:last-child');
            if (m === mode) {
                pill.className = 'config-pill p-3 rounded-xl text-left border transition-all flex flex-col gap-1 bg-secondary dark:bg-dark-accent text-on-primary dark:text-dark-bg border-secondary dark:border-dark-accent shadow-sm';
                if (checkIcon) checkIcon.classList.remove('hidden');
                if (descSpan) descSpan.className = 'text-[11px] opacity-90 leading-tight';
            } else {
                pill.className = 'config-pill p-3 rounded-xl text-left border transition-all flex flex-col gap-1 bg-surface-bright dark:bg-dark-bg border-paper dark:border-dark-border text-on-surface dark:text-dark-text hover:border-secondary dark:hover:border-dark-accent';
                if (checkIcon) checkIcon.classList.add('hidden');
                if (descSpan) descSpan.className = 'text-[11px] text-on-surface-variant dark:text-dark-text-muted leading-tight';
            }
        });
    }
    function selectConfigLength(length) {
        tempResponseLength = length;
        ['default', 'longer', 'shorter'].forEach(l => {
            const pill = document.getElementById(`pill-length-${l}`);
            if (!pill) return;
            const checkIcon = pill.querySelector('.length-check');
            if (l === length) {
                pill.className = 'config-length-pill py-2.5 px-3 rounded-xl text-xs sm:text-sm font-medium transition-all flex items-center justify-center gap-1.5 border bg-secondary dark:bg-dark-accent text-on-primary dark:text-dark-bg border-secondary dark:border-dark-accent shadow-sm';
                if (checkIcon) checkIcon.classList.remove('hidden');
            } else {
                pill.className = 'config-length-pill py-2.5 px-3 rounded-xl text-xs sm:text-sm font-medium transition-all flex items-center justify-center gap-1.5 border bg-surface-bright dark:bg-dark-bg border-paper dark:border-dark-border text-on-surface dark:text-dark-text hover:border-secondary dark:hover:border-dark-accent';
                if (checkIcon) checkIcon.classList.add('hidden');
            }
        });
    }

    function toggleModelDropdown(event) {
        if (event) event.stopPropagation();
        const menu = document.getElementById('model-dropdown-menu');
        if (menu) menu.classList.toggle('hidden');
    }

    function selectLlmModel(modelId, displayName) {
        currentLlmModel = modelId;
        const label = document.getElementById('selected-model-name');
        if (label) label.innerText = displayName;
        
        const allChecks = document.querySelectorAll('#model-dropdown-items .material-symbols-outlined');
        allChecks.forEach(c => c.classList.add('hidden'));
        
        const checkId = 'check-model-' + modelId.replace(/[^a-zA-Z0-9]/g, '-');
        const activeCheck = document.getElementById(checkId);
        if (activeCheck) activeCheck.classList.remove('hidden');

        const menu = document.getElementById('model-dropdown-menu');
        if (menu) menu.classList.add('hidden');
    }

    function renderChatModelDropdown(preferredModels, activeModel) {
        const container = document.getElementById('model-dropdown-items');
        if (!container) return;
        if (!preferredModels || preferredModels.length === 0) return;

        container.innerHTML = preferredModels.map(m => {
            const safeCheckId = 'check-model-' + m.id.replace(/[^a-zA-Z0-9]/g, '-');
            const isSelected = (m.id === activeModel);
            const badgeLabel = m.is_free ? 'Free' : (m.badge || 'BYOK');
            return `
                <button type="button" onclick="selectLlmModel('${escapeHtml(m.id)}', '${escapeHtml(m.name)}')" class="w-full text-left px-3.5 py-2 hover:bg-surface-variant dark:hover:bg-dark-panel-hover transition-colors dark:text-dark-text flex items-center justify-between group">
                    <div class="min-w-0 flex-1 pr-2">
                        <p class="font-medium truncate text-xs">${escapeHtml(m.name)}</p>
                        <p class="text-[10px] text-on-surface-variant dark:text-dark-text-muted truncate">${badgeLabel}</p>
                    </div>
                    <span id="${safeCheckId}" class="material-symbols-outlined text-[14px] text-secondary dark:text-dark-accent ${isSelected ? '' : 'hidden'}">check</span>
                </button>
            `;
        }).join('');

        const selected = preferredModels.find(m => m.id === activeModel) || preferredModels[0];
        if (selected) {
            currentLlmModel = selected.id;
            const label = document.getElementById('selected-model-name');
            if (label) label.innerText = selected.name;
        }
    }

    async function initChatModelPreferences() {
        try {
            const res = await fetch('/api/llm/preferences');
            if (res.ok) {
                const data = await res.json();
                if (data.preferences) {
                    renderChatModelDropdown(
                        data.preferences.preferred_models || [],
                        data.preferences.active_model || 'groq/openai/gpt-oss-120b'
                    );
                }
            }
        } catch (err) {
            console.error('Error fetching chat model preferences:', err);
        }
    }

    // Listen for preference updates from the BYOK settings modal
    window.addEventListener('llm-preferences-updated', (e) => {
        if (e.detail && e.detail.preferredModels) {
            renderChatModelDropdown(e.detail.preferredModels, e.detail.activeModel);
        }
    });

    // Source count chips & active source ids logic are provided globally by workspace-ui.js


    /* -------------------------------------------------------------------------
       STREAMING RAG CHAT & PERSISTENCE LOGIC
    ------------------------------------------------------------------------- */
    let activeLastMessageId = null;  // Tracks the leaf/latest assistant message in active chain
    let branchParentId = null;       // Set when user edits a prior prompt to create a timeline split

    function renderUserMessage(text, messageId, parentId, createdAt) {
        const container = document.getElementById('chat-messages-container');
        if (!container) return null;

        const msgDiv = document.createElement('div');
        msgDiv.className = 'flex gap-3 max-w-3xl ml-auto flex-row-reverse animate-fade-in group';
        if (messageId) msgDiv.setAttribute('data-message-id', messageId);
        if (parentId) msgDiv.setAttribute('data-parent-id', parentId);

        msgDiv.innerHTML = `
            <div class="h-8 w-8 rounded-full bg-primary/10 dark:bg-dark-text/10 border border-primary/20 flex items-center justify-center flex-shrink-0 text-primary dark:text-dark-text">
                <span class="material-symbols-outlined text-[18px]">person</span>
            </div>
            <div class="relative flex-1 bg-secondary/10 dark:bg-dark-accent/15 border border-secondary/20 dark:border-dark-accent/25 p-4 rounded-2xl rounded-tr-none">
                <p class="font-body-md text-on-surface dark:text-dark-text leading-relaxed whitespace-pre-wrap">${escapeHtml(text)}</p>
                <div class="mt-1 flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button type="button" onclick="editUserPrompt(${JSON.stringify(text)}, '${messageId || ''}', '${parentId || ''}')" class="text-[11px] text-on-surface-variant dark:text-dark-text-muted hover:text-secondary dark:hover:text-dark-accent flex items-center gap-1 transition-colors" title="Edit prompt & split branch">
                        <span class="material-symbols-outlined text-[14px]">edit</span>
                        <span>Edit</span>
                    </button>
                </div>
            </div>
        `;

        const spacer = document.getElementById('chat-bottom-spacer');
        if (spacer) container.insertBefore(msgDiv, spacer);
        else container.appendChild(msgDiv);
        return msgDiv;
    }

    function getAssistantActionBarHtml() {
        return `
            <div class="mt-2.5 pt-2 flex items-center gap-2 border-t border-paper/40 dark:border-dark-border/40 animate-fade-in">
                <button type="button" onclick="saveMessageToNote(this)" class="save-to-note-btn inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-surface-bright dark:bg-dark-bg border border-paper dark:border-dark-border text-on-surface dark:text-dark-text hover:border-secondary dark:hover:border-dark-accent hover:text-secondary dark:hover:text-dark-accent transition-all shadow-sm group" title="Save this response to notebook notes">
                    <span class="material-symbols-outlined text-[15px] text-secondary dark:text-dark-accent group-hover:scale-110 transition-transform">push_pin</span>
                    <span class="btn-text">Save to note</span>
                </button>
                <button type="button" onclick="copyMessageText(this)" class="copy-msg-btn w-7 h-7 flex items-center justify-center rounded-full text-on-surface-variant dark:text-dark-text-muted hover:text-on-surface dark:hover:text-dark-text hover:bg-surface-variant/80 dark:hover:bg-dark-panel-hover transition-all aspect-square" title="Copy response text">
                    <span class="material-symbols-outlined text-[16px]">content_copy</span>
                </button>
            </div>
        `;
    }

    function buildCitationsHtml(citations) {
        if (!citations || citations.length === 0) return '';
        return `
            <div class="mt-3 pt-2.5 border-t border-paper/60 dark:border-dark-border/40 flex flex-wrap items-center gap-1.5 animate-fade-in">
                <span class="text-[11px] font-semibold text-on-surface-variant dark:text-dark-text-muted uppercase tracking-wider mr-1">Sources:</span>
                ${citations.map(s => {
                    const title = escapeHtml(s.source_title || s.document_title || 'Document');
                    const pageNum = s.page_number || ((s.order || 0) + 1);
                    const snippet = escapeHtml(s.chunk_snapshot || s.text_snippet || '');
                    return `
                        <div class="group/cit relative inline-block">
                            <span class="inline-flex items-center gap-1 bg-surface-bright dark:bg-dark-bg text-on-surface-variant dark:text-dark-text-muted border border-paper dark:border-dark-border px-2 py-0.5 rounded-full text-xs cursor-pointer hover:border-secondary dark:hover:border-dark-accent transition-colors">
                                <span class="material-symbols-outlined text-[13px] text-secondary dark:text-dark-accent">description</span>
                                <span class="font-medium truncate max-w-[140px]">${title} (p.${pageNum})</span>
                            </span>
                            ${snippet ? `
                            <div class="hidden group-hover/cit:block absolute bottom-full left-0 mb-2 w-64 p-2.5 bg-surface-container-lowest dark:bg-dark-panel border border-paper dark:border-dark-border rounded-xl shadow-xl z-50 text-[11px] dark:text-dark-text leading-relaxed pointer-events-none">
                                <p class="font-semibold text-secondary dark:text-dark-accent mb-1">${title}</p>
                                <p class="text-on-surface-variant dark:text-dark-text-muted italic line-clamp-4">"${snippet}"</p>
                            </div>` : ''}
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    function buildTimingsHtml(timingsMs, usedTokens) {
        if (!timingsMs) return '';
        return `
            <div class="flex items-center gap-2 text-[10px] text-on-surface-variant/70 dark:text-dark-text-muted/60 mt-2 animate-fade-in">
                <span>⏱️ Total: ${timingsMs.total_ms || 0}ms (Retrieval: ${timingsMs.retrieval_ms || 0}ms, LLM: ${timingsMs.llm_ms || 0}ms)</span>
                ${usedTokens ? `<span>• 🔤 ${usedTokens} tokens</span>` : ''}
            </div>
        `;
    }

    function renderAssistantMessage(text, messageId, citations, llmModel, createdAt, timingsMs, usedTokens) {
        const container = document.getElementById('chat-messages-container');
        if (!container) return null;

        const msgDiv = document.createElement('div');
        msgDiv.className = 'flex gap-3 max-w-3xl animate-fade-in';
        if (messageId) msgDiv.setAttribute('data-message-id', messageId);

        const citationsHtml = buildCitationsHtml(citations);
        const timingsHtml = buildTimingsHtml(timingsMs, usedTokens);

        msgDiv.innerHTML = `
            <div class="h-8 w-8 rounded-full bg-secondary/10 dark:bg-dark-accent/15 border border-secondary/20 dark:border-dark-accent/30 flex items-center justify-center flex-shrink-0 text-secondary dark:text-dark-accent">
                <span class="material-symbols-outlined text-[18px]">auto_awesome</span>
            </div>
            <div class="flex-1 bg-surface-variant/40 dark:bg-dark-panel-hover p-4 rounded-2xl rounded-tl-none border border-paper/60 dark:border-dark-border/60">
                <div class="font-body-md dark:text-dark-text leading-relaxed prose dark:prose-invert max-w-none ai-text-content">
                    ${formatMarkdownText(text)}
                </div>
                <div class="ai-metadata-content">${citationsHtml}${timingsHtml}</div>
                ${getAssistantActionBarHtml()}
            </div>
        `;

        const spacer = document.getElementById('chat-bottom-spacer');
        if (spacer) container.insertBefore(msgDiv, spacer);
        else container.appendChild(msgDiv);
        const textContent = msgDiv.querySelector('.ai-text-content');
        if (textContent) renderMathSafely(textContent);
        return msgDiv;
    }

    function editUserPrompt(text, messageId, parentId) {
        const input = document.getElementById('chat-input');
        if (!input) return;

        input.value = text;
        branchParentId = (parentId && parentId !== 'null' && parentId !== 'None') ? parentId : null;

        input.style.height = '';
        const targetHeight = Math.min(input.scrollHeight, 120);
        input.style.height = targetHeight + 'px';
        input.style.overflowY = input.scrollHeight > 120 ? 'auto' : 'hidden';

        const sendBtn = document.getElementById('send-btn');
        const sourcesChip = document.getElementById('sources-chip');
        if (sendBtn) sendBtn.classList.remove('hidden');
        if (sourcesChip) sourcesChip.classList.add('hidden');

        input.focus();
    }

    async function loadChatHistory() {
        const notebookId = getNotebookIdFromUrl();
        if (!notebookId) return;

        const container = document.getElementById('chat-messages-container');
        if (!container) return;

        try {
            const res = await fetch(`/notebooks/${notebookId}/chat/history`);
            if (!res.ok) return;

            const data = await res.json();
            const messages = data.messages || [];

            if (messages.length === 0) {
                activeLastMessageId = null;
                return;
            }

            // Clear placeholder welcome message
            container.innerHTML = '';

            messages.forEach(msg => {
                if (msg.role === 'user') {
                    renderUserMessage(msg.content, msg.id, msg.parent_id, msg.created_at);
                } else if (msg.role === 'assistant') {
                    renderAssistantMessage(
                        msg.content,
                        msg.id,
                        msg.citations || [],
                        msg.llm_model,
                        msg.created_at,
                        msg.timings_ms,
                        msg.used_tokens
                    );
                    activeLastMessageId = msg.id;
                }
            });

            // Re-append spacer at bottom
            const spacer = document.createElement('div');
            spacer.id = 'chat-bottom-spacer';
            spacer.className = 'h-28 sm:h-36 w-full flex-shrink-0 pointer-events-none';
            container.appendChild(spacer);

            container.scrollTop = container.scrollHeight;
        } catch (err) {
            console.error('Error loading chat history:', err);
        }
    }

    function appendLoadingIndicator() {
        const container = document.getElementById('chat-messages-container');
        if (!container) return null;
        const loadingId = 'ai-loading-' + Date.now();
        const msgDiv = document.createElement('div');
        msgDiv.id = loadingId;
        msgDiv.className = 'flex gap-3 max-w-3xl animate-fade-in';
        msgDiv.innerHTML = `
            <div class="h-8 w-8 rounded-full bg-secondary/10 dark:bg-dark-accent/15 border border-secondary/20 dark:border-dark-accent/30 flex items-center justify-center flex-shrink-0 text-secondary dark:text-dark-accent">
                <span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span>
            </div>
            <div class="flex-1 bg-surface-variant/40 dark:bg-dark-panel-hover p-4 rounded-2xl rounded-tl-none border border-paper/60 dark:border-dark-border/60 flex items-center gap-2.5">
                <div class="flex items-center gap-1.5 py-0.5">
                    <span class="w-2 h-2 rounded-full bg-secondary dark:bg-dark-accent animate-bounce" style="animation-delay: 0ms"></span>
                    <span class="w-2 h-2 rounded-full bg-secondary dark:bg-dark-accent animate-bounce" style="animation-delay: 150ms"></span>
                    <span class="w-2 h-2 rounded-full bg-secondary dark:bg-dark-accent animate-bounce" style="animation-delay: 300ms"></span>
                </div>
                <span class="text-xs font-medium text-on-surface-variant dark:text-dark-text-muted">Searching sources & preparing response...</span>
            </div>
        `;
        const spacer = document.getElementById('chat-bottom-spacer');
        if (spacer) container.insertBefore(msgDiv, spacer);
        else container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
        return loadingId;
    }

    function initializeStreamingAiMessage(loadingId) {
        const container = document.getElementById('chat-messages-container');
        const loadingEl = loadingId ? document.getElementById(loadingId) : null;
        const msgDiv = document.createElement('div');
        msgDiv.id = loadingId;
        msgDiv.className = 'flex gap-3 max-w-3xl animate-fade-in';
        
        msgDiv.innerHTML = `
            <div class="h-8 w-8 rounded-full bg-secondary/10 dark:bg-dark-accent/15 border border-secondary/20 dark:border-dark-accent/30 flex items-center justify-center flex-shrink-0 text-secondary dark:text-dark-accent">
                <span class="material-symbols-outlined text-[18px]">auto_awesome</span>
            </div>
            <div class="flex-1 bg-surface-variant/40 dark:bg-dark-panel-hover p-4 rounded-2xl rounded-tl-none border border-paper/60 dark:border-dark-border/60">
                <div class="font-body-md dark:text-dark-text leading-relaxed prose dark:prose-invert max-w-none ai-text-content">
                    <div class="flex items-center gap-2 text-on-surface-variant dark:text-dark-text-muted text-xs py-1">
                        <span class="inline-block w-2 h-2 rounded-full bg-secondary dark:bg-dark-accent animate-ping"></span>
                        <span>Generating answer...</span>
                    </div>
                </div>
                <div class="ai-metadata-content"></div>
            </div>
        `;

        if (loadingEl) {
            loadingEl.replaceWith(msgDiv);
        } else {
            const spacer = document.getElementById('chat-bottom-spacer');
            if (spacer) container.insertBefore(msgDiv, spacer);
            else container.appendChild(msgDiv);
        }
        
        if (container) container.scrollTop = container.scrollHeight;

        return {
            element: msgDiv,
            textContainer: msgDiv.querySelector('.ai-text-content'),
            metadataContainer: msgDiv.querySelector('.ai-metadata-content')
        };
    }

    function renderMetadata(container, data) {
        const citationsHtml = buildCitationsHtml(data.sources);
        const timingsHtml = buildTimingsHtml(data.timings_ms, data.used_tokens);
        container.innerHTML = citationsHtml + timingsHtml + getAssistantActionBarHtml();
    }

    function appendErrorMessage(loadingId, errorText) {
        const container = document.getElementById('chat-messages-container');
        const loadingEl = loadingId ? document.getElementById(loadingId) : null;
        const msgDiv = document.createElement('div');
        msgDiv.className = 'flex gap-3 max-w-3xl animate-fade-in';
        
        const isKeyIssue = /api key|missing.*key|authentication|unauthorized|provider key/i.test(errorText);

        msgDiv.innerHTML = `
            <div class="h-8 w-8 rounded-full ${isKeyIssue ? 'bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400' : 'bg-error/10 border-error/20 text-error'} border flex items-center justify-center flex-shrink-0">
                <span class="material-symbols-outlined text-[18px]">${isKeyIssue ? 'key' : 'error'}</span>
            </div>
            <div class="flex-1 ${isKeyIssue ? 'bg-amber-500/5 border-amber-500/25 text-on-surface dark:text-dark-text' : 'bg-error/5 border-error/20 text-error'} border p-4 rounded-2xl rounded-tl-none text-sm shadow-xs">
                <p class="font-semibold text-xs ${isKeyIssue ? 'text-amber-700 dark:text-amber-400' : 'text-error'}">${isKeyIssue ? 'API Key Required' : 'Error generating response'}</p>
                <p class="text-xs mt-1 leading-relaxed text-on-surface-variant dark:text-dark-text-muted">${escapeHtml(errorText)}</p>
                ${isKeyIssue ? `
                    <div class="mt-3 flex items-center gap-2">
                        <button type="button" onclick="window.dispatchEvent(new CustomEvent('open-byok-modal', { detail: { tab: 'providers' } }))" class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-secondary dark:bg-dark-accent text-on-primary dark:text-dark-bg text-xs font-semibold hover:opacity-90 transition-opacity shadow-sm">
                            <span class="material-symbols-outlined text-[15px]">key</span>
                            <span>Open Key Settings</span>
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
        if (loadingEl) {
            loadingEl.replaceWith(msgDiv);
        } else {
            const spacer = document.getElementById('chat-bottom-spacer');
            if (spacer) container.insertBefore(msgDiv, spacer);
            else container.appendChild(msgDiv);
        }
        if (container) container.scrollTop = container.scrollHeight;
    }

    async function submitChatMessage() {
        const input = document.getElementById('chat-input');
        if (!input) return;
        const text = input.value.trim();
        if (!text) return;

        const notebookId = getNotebookIdFromUrl();
        if (!notebookId) return;

        const sendBtn = document.getElementById('send-btn');
        const sourcesChip = document.getElementById('sources-chip');
        if (sendBtn) sendBtn.disabled = true;

        input.value = '';
        input.style.height = '';
        input.style.overflowY = 'hidden';
        if (sendBtn) sendBtn.classList.add('hidden');
        if (sourcesChip) sourcesChip.classList.remove('hidden');

        // Determine parent_id for branching
        const targetParentId = (branchParentId !== null) ? branchParentId : activeLastMessageId;

        // Render user message bubble immediately
        const userMsgEl = renderUserMessage(text, null, targetParentId);
        const loadingId = appendLoadingIndicator();
        const activeSourceIds = getSelectedSourceIds();
        const chatContainer = document.getElementById('chat-messages-container');

        let bubbleData = null;

        try {
            // 1. Initiate Streaming Fetch Request
            const response = await fetch(`/notebooks/${notebookId}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: text,
                    source_ids: activeSourceIds,
                    mode: currentPromptMode,
                    model: currentLlmModel,
                    response_length: currentResponseLength,
                    parent_id: targetParentId
                })
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to get answer from AI');
            }

            // 2. Setup the AI Bubble for Streaming
            bubbleData = initializeStreamingAiMessage(loadingId);
            
            // 3. Native ReadableStream parsing with throttled RAF rendering
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let accumulatedText = "";
            let buffer = "";

            let renderPending = false;
            let lastRenderTime = 0;
            const RENDER_INTERVAL_MS = 40;
            let renderTimer = null;

            function renderStreamingChunk() {
                if (!bubbleData || !bubbleData.textContainer) return;
                bubbleData.textContainer.innerHTML = formatMarkdownText(accumulatedText) + '<span class="inline-block w-1.5 h-4 ml-1 bg-secondary dark:bg-dark-accent rounded-sm animate-pulse align-middle" style="vertical-align: -2px;"></span>';
                
                // Keep scrolled to bottom if user is near the bottom
                const isNearBottom = (chatContainer.scrollHeight - chatContainer.scrollTop) <= (chatContainer.clientHeight + 250);
                if (isNearBottom) {
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
            }

            function requestStreamingRender() {
                if (renderPending) return;
                const now = Date.now();
                const elapsed = now - lastRenderTime;

                if (elapsed >= RENDER_INTERVAL_MS) {
                    renderPending = true;
                    requestAnimationFrame(() => {
                        renderStreamingChunk();
                        lastRenderTime = Date.now();
                        renderPending = false;
                    });
                } else {
                    renderPending = true;
                    if (renderTimer) clearTimeout(renderTimer);
                    renderTimer = setTimeout(() => {
                        requestAnimationFrame(() => {
                            renderStreamingChunk();
                            lastRenderTime = Date.now();
                            renderPending = false;
                            renderTimer = null;
                        });
                    }, RENDER_INTERVAL_MS - elapsed);
                }
            }

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n\n');
                buffer = lines.pop(); // Keep incomplete JSON in buffer
                
                for (const line of lines) {
                    const trimmedLine = line.trim();
                    if (!trimmedLine) continue;

                    if (trimmedLine.startsWith('data: ')) {
                        const dataStr = trimmedLine.slice(6).trim();
                        if (dataStr === '[DONE]') continue; 
                        
                        try {
                            const data = JSON.parse(dataStr);
                            
                            // A) Process user save event
                            if (data.type === 'user_saved' && data.user_message_id && userMsgEl) {
                                userMsgEl.setAttribute('data-message-id', data.user_message_id);
                                if (data.parent_id) userMsgEl.setAttribute('data-parent-id', data.parent_id);
                                const editBtn = userMsgEl.querySelector('button[onclick^="editUserPrompt"]');
                                if (editBtn) {
                                    editBtn.setAttribute('onclick', `editUserPrompt(${JSON.stringify(text)}, '${data.user_message_id}', '${data.parent_id || ''}')`);
                                }
                            }
                            // B) Process text chunk
                            else if (data.type === 'chunk' && data.content) {
                                accumulatedText += data.content;
                                requestStreamingRender();
                            }
                            // B.2) Process fallback notice event
                            else if (data.type === 'fallback_notice') {
                                const noticeDiv = document.createElement('div');
                                noticeDiv.className = 'mb-2.5 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-xs flex items-center gap-1.5 animate-fade-in';
                                noticeDiv.innerHTML = `
                                    <span class="material-symbols-outlined text-[15px]">swap_horiz</span>
                                    <span><strong>Switched to ${escapeHtml(data.fallback_label || data.fallback_model)}</strong>: ${escapeHtml(data.reason || 'Fallback active')}</span>
                                `;
                                if (bubbleData && bubbleData.textContainer && bubbleData.textContainer.parentElement) {
                                    bubbleData.textContainer.parentElement.insertBefore(noticeDiv, bubbleData.textContainer);
                                }
                            } 
                            // C) Process final metadata payload
                            else if (data.type === 'metadata') {
                                if (renderTimer) {
                                    clearTimeout(renderTimer);
                                    renderTimer = null;
                                }
                                renderPending = false;

                                if (accumulatedText) {
                                    bubbleData.textContainer.innerHTML = formatMarkdownText(accumulatedText);
                                    renderMathSafely(bubbleData.textContainer);
                                } else if (!bubbleData.textContainer.querySelector('.text-error')) {
                                    bubbleData.textContainer.innerHTML = '<span class="text-xs text-on-surface-variant dark:text-dark-text-muted italic">No response generated.</span>';
                                }
                                if (data.message_id) {
                                    bubbleData.element.setAttribute('data-message-id', data.message_id);
                                    activeLastMessageId = data.message_id;
                                }
                                // Reset branching parent after successful completion
                                branchParentId = null;

                                renderMetadata(bubbleData.metadataContainer, data);
                                chatContainer.scrollTop = chatContainer.scrollHeight;
                            }
                            // D) Process error payload from server stream
                            else if (data.type === 'error') {
                                const errMsg = data.error || 'Stream error';
                                if (bubbleData && bubbleData.textContainer) {
                                    bubbleData.textContainer.innerHTML = `<div class="p-3 rounded-xl bg-error/10 border border-error/20 text-error text-xs leading-relaxed"><strong>Generation Failed:</strong> ${escapeHtml(errMsg)}</div>`;
                                }
                                throw new Error(errMsg);
                            }
                        } catch (e) {
                            if (e.message && e.message.startsWith('All LLM candidate') || (typeof data !== 'undefined' && data && data.type === 'error')) {
                                throw e;
                            }
                            console.error("Error parsing stream event:", e);
                        }
                    }
                }
            }

            // Final cleanup: remove trailing cursor
            if (accumulatedText && bubbleData) {
                bubbleData.textContainer.innerHTML = formatMarkdownText(accumulatedText);
                renderMathSafely(bubbleData.textContainer);
            }
        } catch (err) {
            console.error('Chat error:', err);
            appendErrorMessage(loadingId, err.message || 'Network error');
        } finally {
            if (sendBtn) sendBtn.disabled = false;
            input.focus();
        }
    }

    function openClearChatModal() {
        const modal = document.getElementById('clear-chat-modal');
        if (modal) modal.classList.remove('hidden');
    }

    function closeClearChatModal() {
        const modal = document.getElementById('clear-chat-modal');
        if (modal) modal.classList.add('hidden');
    }

    async function confirmClearChatHistory() {
        const notebookId = getNotebookIdFromUrl();
        if (!notebookId) return;

        const btn = document.getElementById('btn-confirm-clear-chat');
        const btnText = document.getElementById('clear-chat-btn-text');
        if (btn) btn.disabled = true;
        if (btnText) btnText.innerText = "Clearing...";

        try {
            const res = await fetch(`/notebooks/${notebookId}/chat/history`, {
                method: 'DELETE'
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to clear chat history.');
            }

            activeLastMessageId = null;
            branchParentId = null;

            const container = document.getElementById('chat-messages-container');
            if (container) {
                container.innerHTML = `
                    <div class="flex gap-3 max-w-3xl animate-fade-in">
                        <div class="h-8 w-8 rounded-full bg-secondary/10 dark:bg-dark-accent/15 border border-secondary/20 dark:border-dark-accent/30 flex items-center justify-center flex-shrink-0 text-secondary dark:text-dark-accent">
                            <span class="material-symbols-outlined text-[18px]">auto_awesome</span>
                        </div>
                        <div class="flex-1 bg-surface-variant/40 dark:bg-dark-panel-hover p-4 rounded-2xl rounded-tl-none border border-paper/60 dark:border-dark-border/60">
                            <p class="font-body-md dark:text-dark-text leading-relaxed">
                                Hello! I'm ready to answer questions grounded in your selected documents. What would you like to explore?
                            </p>
                        </div>
                    </div>
                    <div id="chat-bottom-spacer" class="h-28 sm:h-36 w-full flex-shrink-0 pointer-events-none"></div>
                `;
            }
            closeClearChatModal();
        } catch (err) {
            console.error('Error clearing chat history:', err);
            showAppAlert(err.message || 'Error clearing chat history.', { title: 'Action Failed', type: 'error' });
        } finally {
            if (btn) btn.disabled = false;
            if (btnText) btnText.innerText = "Clear History";
        }
    }

    function initModalDismissListeners() {
        const clearModalEl = document.getElementById('clear-chat-modal');
        if (clearModalEl && !clearModalEl.dataset.dismissBound) {
            clearModalEl.dataset.dismissBound = 'true';
            clearModalEl.addEventListener('click', function(e) {
                if (e.target === this) closeClearChatModal();
            });
        }
        const configModalEl = document.getElementById('configure-chat-modal');
        if (configModalEl && !configModalEl.dataset.dismissBound) {
            configModalEl.dataset.dismissBound = 'true';
            configModalEl.addEventListener('click', function(e) {
                if (e.target === this) closeConfigureChatModal();
            });
        }
    }

    function initChatInputListeners() {
        const chatInput = document.getElementById('chat-input');
        if (chatInput && !chatInput.dataset.listenersBound) {
            chatInput.dataset.listenersBound = 'true';
            chatInput.addEventListener('input', function() {
                const sendBtn = document.getElementById('send-btn');
                const sourcesChip = document.getElementById('sources-chip');
                if (this.value.trim().length > 0) {
                    if (sendBtn) sendBtn.classList.remove('hidden');
                    if (sourcesChip) sourcesChip.classList.add('hidden');
                } else {
                    if (sendBtn) sendBtn.classList.add('hidden');
                    if (sourcesChip) sourcesChip.classList.remove('hidden');
                }
                this.style.height = '';
                if (this.value.length > 0) {
                    const targetHeight = Math.min(this.scrollHeight, 120);
                    this.style.height = targetHeight + 'px';
                    this.style.overflowY = this.scrollHeight > 120 ? 'auto' : 'hidden';
                } else {
                    this.style.overflowY = 'hidden';
                }
            });
            chatInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    submitChatMessage();
                }
            });
        }
    }

    function copyMessageText(btn) {
        const msgBubble = btn.closest('.flex-1');
        if (!msgBubble) return;
        const textContainer = msgBubble.querySelector('.ai-text-content');
        if (!textContainer) return;
        
        const content = textContainer.innerText.trim();
        if (!content) return;

        navigator.clipboard.writeText(content).then(() => {
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px] text-emerald-500">check</span>';
            setTimeout(() => {
                btn.innerHTML = originalHtml;
            }, 2000);
        }).catch(err => {
            console.error('Clipboard copy failed:', err);
        });
    }

    // Initialize chat history, model preferences & DOM listeners (single execution guard)
    function initChatWorkspace() {
        initChatInputListeners();
        initModalDismissListeners();
        loadChatHistory();
        initChatModelPreferences();
        updateSourcesCount();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initChatWorkspace);
    } else {
        initChatWorkspace();
    }

    // Export all chat and modal actions to window for robust inline onclick accessibility
    window.openConfigureChatModal = openConfigureChatModal;
    window.closeConfigureChatModal = closeConfigureChatModal;
    window.saveChatConfiguration = saveChatConfiguration;
    window.selectConfigMode = selectConfigMode;
    window.selectConfigLength = selectConfigLength;
    window.toggleModelDropdown = toggleModelDropdown;
    window.selectLlmModel = selectLlmModel;
    window.openClearChatModal = openClearChatModal;
    window.closeClearChatModal = closeClearChatModal;
    window.confirmClearChatHistory = confirmClearChatHistory;
    window.submitChatMessage = submitChatMessage;
    window.editUserPrompt = editUserPrompt;
    window.copyMessageText = copyMessageText;



