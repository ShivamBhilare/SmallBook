/**
 * @fileoverview Bring Your Own Key (BYOK) & Model Preferences Alpine Component.
 * Manages encrypted API key inputs, live dry-run provider tests, custom model selection,
 * preferred models catalog (top 3-5 limit), free-tier quota telemetry, and header status dots.
 */

/* ==========================================================================
   BYOK MODAL COMPONENT REGISTRATION
   ========================================================================== */

document.addEventListener('alpine:init', () => {
    Alpine.data('byokModal', () => ({
        // State
        isOpen: false,
        activeTab: 'providers',
        isLoading: false,
        isSaving: false,
        catalog: [],
        credentials: [],
        keyInputs: {},
        preferredModels: [],
        activeModel: 'groq/openai/gpt-oss-120b',
        fallbackEnabled: true,
        confirmDeleteProviderId: null,
        quota: {
            used_today: 0,
            daily_limit: 25,
            remaining_today: 25,
            is_allowed: true
        },
        statusMessage: '',
        statusType: 'success',

        /**
         * Initializes component state on mount.
         */
        init() {
            this.fetchInitialData();
        },

        /**
         * Global keyboard shortcut listener (Cmd+K / Ctrl+K) to toggle modal.
         * @param {KeyboardEvent} e - Keyboard event.
         */
        handleGlobalKeydown(e) {
            if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
                e.preventDefault();
                this.openModal();
            }
        },

        /**
         * Opens the modal dialog and switches to specified tab.
         * @param {string} [tab='providers'] - Tab to activate ('providers' or 'preferences').
         */
        openModal(tab = 'providers') {
            this.isOpen = true;
            this.activeTab = tab;
            this.statusMessage = '';
            this.fetchInitialData();
        },

        /**
         * Closes the modal dialog and resets transient messages.
         */
        closeModal() {
            this.isOpen = false;
            this.statusMessage = '';
        },

        /**
         * Fetches provider catalog, saved credentials, model preferences, and free-tier quotas.
         * @returns {Promise<void>}
         */
        async fetchInitialData() {
            this.isLoading = true;
            try {
                const [catRes, keyRes, prefRes] = await Promise.all([
                    fetch('/api/llm/catalog'),
                    fetch('/api/llm/keys'),
                    fetch('/api/llm/preferences')
                ]);

                if (catRes.ok) {
                    const catData = await catRes.json();
                    this.catalog = catData.catalog || [];
                    this.catalog.forEach(p => {
                        if (!this.keyInputs[p.id]) {
                            this.keyInputs[p.id] = {
                                rawKey: '',
                                apiBase: p.id === 'custom' ? 'http://localhost:11434/v1' : '',
                                customModel: p.id === 'custom' ? 'ollama/llama3.2' : '',
                                showKey: false,
                                testing: false,
                                testResult: null
                            };
                        }
                    });
                }

                if (keyRes.ok) {
                    const keyData = await keyRes.json();
                    this.credentials = keyData.credentials || [];
                    this.updateHeaderStatusDot();
                }

                if (prefRes.ok) {
                    const prefData = await prefRes.json();
                    if (prefData.preferences) {
                        this.activeModel = prefData.preferences.active_model || 'groq/openai/gpt-oss-120b';
                        this.preferredModels = prefData.preferences.preferred_models || [];
                        this.fallbackEnabled = prefData.preferences.fallback_enabled ?? true;
                    }
                    if (prefData.quota) {
                        this.quota = prefData.quota;
                    }
                }
            } catch (err) {
                console.error('Error loading LLM settings:', err);
            } finally {
                this.isLoading = false;
            }
        },

        /**
         * Checks if an active credential exists for the given provider.
         * @param {string} providerId - Provider identifier.
         * @returns {boolean} True if active credential exists.
         */
        isProviderSaved(providerId) {
            return this.credentials.some(c => c.provider === providerId && c.is_active);
        },

        /**
         * Returns the masked last 4 characters of a saved provider key.
         * @param {string} providerId - Provider identifier.
         * @returns {string} Last 4 characters or empty string.
         */
        getSavedKeyLast4(providerId) {
            const cred = this.credentials.find(c => c.provider === providerId);
            return cred ? cred.key_last4 : '';
        },

        /**
         * Sends a dry-run 1-token verification request for the given provider key.
         * @param {string} providerId - Provider identifier.
         * @returns {Promise<void>}
         */
        async testProviderKey(providerId) {
            const input = this.keyInputs[providerId];
            if (!input) return;
            if (!input.rawKey && !this.isProviderSaved(providerId)) {
                input.testResult = { is_valid: false, message: 'Please enter an API key first.' };
                return;
            }

            input.testing = true;
            input.testResult = null;
            try {
                const res = await fetch('/api/llm/keys/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider: providerId,
                        raw_key: input.rawKey || '',
                        api_base: input.apiBase || null,
                        model: input.customModel || null
                    })
                });
                const data = await res.json();
                input.testResult = data;
            } catch (err) {
                input.testResult = { is_valid: false, message: 'Connection test failed: ' + err.message };
            } finally {
                input.testing = false;
            }
        },

        /**
         * Encrypts and persists a new API key for the specified provider.
         * @param {string} providerId - Provider identifier.
         * @returns {Promise<void>}
         */
        async saveProviderKey(providerId) {
            const input = this.keyInputs[providerId];
            if (!input || !input.rawKey) {
                if (typeof window.showAppAlert === 'function') {
                    window.showAppAlert('Please enter an API key before saving.', { title: 'API Key Required', type: 'warning' });
                }
                return;
            }

            input.testing = true;
            try {
                const res = await fetch('/api/llm/keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider: providerId,
                        raw_key: input.rawKey,
                        api_base: input.apiBase || null,
                        custom_model_name: input.customModel || null
                    })
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Failed to save key');
                }
                const data = await res.json();
                input.rawKey = '';
                input.testResult = data.validation;
                await this.fetchInitialData();
                this.showStatus('API Key saved and encrypted securely!', 'success');
            } catch (err) {
                this.showStatus(err.message, 'error');
            } finally {
                input.testing = false;
            }
        },

        /**
         * Removes a stored provider credential and updates state.
         * @param {string} providerId - Provider identifier to delete.
         * @returns {Promise<void>}
         */
        async executeRemoveProviderKey(providerId) {
            if (!providerId) return;
            this.confirmDeleteProviderId = null;
            try {
                const res = await fetch(`/api/llm/keys/${providerId}`, { method: 'DELETE' });
                if (!res.ok) throw new Error('Failed to delete key');
                await this.fetchInitialData();
                this.showStatus('API Key removed successfully.', 'success');
            } catch (err) {
                this.showStatus(err.message, 'error');
            }
        },

        /**
         * Checks if a model is present in the preferred models list.
         * @param {string} modelId - Model identifier string.
         * @returns {boolean} True if selected.
         */
        isModelSelected(modelId) {
            return this.preferredModels.some(m => (m.id || m) === modelId);
        },

        /**
         * Adds or removes a model from preferred selection (enforcing min 1 and max 5 bounds).
         * @param {Object} model - Model metadata object.
         */
        toggleModelSelection(model) {
            const exists = this.isModelSelected(model.id);
            if (exists) {
                if (this.preferredModels.length <= 1) {
                    this.showStatus('You must keep at least 1 chat model selected.', 'error');
                    return;
                }
                this.preferredModels = this.preferredModels.filter(m => (m.id || m) !== model.id);
                if (this.activeModel === model.id && this.preferredModels.length > 0) {
                    this.activeModel = this.preferredModels[0].id || this.preferredModels[0];
                }
            } else {
                if (this.preferredModels.length >= 5) {
                    this.showStatus('You can select a maximum of 5 chat models for your dropdown.', 'error');
                    return;
                }
                this.preferredModels.push({
                    id: model.id,
                    name: model.name,
                    provider: model.provider || 'custom',
                    badge: model.is_free ? 'Free' : 'BYOK',
                    is_free: model.is_free || false
                });
                if (!this.activeModel || this.preferredModels.length === 1) {
                    this.activeModel = model.id;
                }
            }
        },

        /**
         * Designates the default active model for new chat sessions.
         * @param {string} modelId - Model identifier.
         */
        setDefaultModel(modelId) {
            this.activeModel = modelId;
        },

        /**
         * Persists preferred models and fallback behaviors to backend API.
         * @returns {Promise<void>}
         */
        async saveModelPreferences() {
            this.isSaving = true;
            try {
                const res = await fetch('/api/llm/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        active_model: this.activeModel,
                        preferred_models: this.preferredModels,
                        fallback_enabled: this.fallbackEnabled
                    })
                });
                if (!res.ok) throw new Error('Failed to save preferences');
                this.showStatus('Model preferences updated successfully!', 'success');

                // Dispatch event to update dynamic chat dropdown in workspace
                window.dispatchEvent(new CustomEvent('llm-preferences-updated', {
                    detail: {
                        activeModel: this.activeModel,
                        preferredModels: this.preferredModels
                    }
                }));
            } catch (err) {
                this.showStatus(err.message, 'error');
            } finally {
                this.isSaving = false;
            }
        },

        /**
         * Displays a timed toast notification inside the modal.
         * @param {string} msg - Message to display.
         * @param {string} [type='success'] - Toast level ('success' or 'error').
         */
        showStatus(msg, type = 'success') {
            this.statusMessage = msg;
            this.statusType = type;
            setTimeout(() => {
                if (this.statusMessage === msg) this.statusMessage = '';
            }, 5000);
        },

        /**
         * Updates visual indicator dots in application header according to key status.
         */
        updateHeaderStatusDot() {
            const dots = [
                document.getElementById('byok-header-status-dot'),
                document.getElementById('byok-header-status-dot-mobile')
            ];
            const hasKeys = this.credentials.length > 0;
            dots.forEach(dot => {
                if (dot) {
                    if (hasKeys) {
                        dot.className = 'absolute top-1 right-1 w-2 h-2 rounded-full bg-emerald-500 ring-2 ring-surface dark:ring-dark-panel';
                        dot.title = 'Personal BYOK Keys Active';
                    } else {
                        dot.className = 'absolute top-1 right-1 w-2 h-2 rounded-full bg-amber-500 ring-2 ring-surface dark:ring-dark-panel';
                        dot.title = 'Free Tier Active (25/day)';
                    }
                }
            });
        }
    }));
});
