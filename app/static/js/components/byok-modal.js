/**
 * SmallBook - BYOK (Bring Your Own Key) & Model Preferences Alpine Component
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('byokModal', () => ({
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

        init() {
            this.fetchInitialData();
        },

        handleGlobalKeydown(e) {
            if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
                e.preventDefault();
                this.openModal();
            }
        },

        openModal(tab = 'providers') {
            this.isOpen = true;
            this.activeTab = tab;
            this.statusMessage = '';
            this.fetchInitialData();
        },

        closeModal() {
            this.isOpen = false;
            this.statusMessage = '';
        },

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

        isProviderSaved(providerId) {
            return this.credentials.some(c => c.provider === providerId && c.is_active);
        },

        getSavedKeyLast4(providerId) {
            const cred = this.credentials.find(c => c.provider === providerId);
            return cred ? cred.key_last4 : '';
        },

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

        isModelSelected(modelId) {
            return this.preferredModels.some(m => (m.id || m) === modelId);
        },

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

        setDefaultModel(modelId) {
            this.activeModel = modelId;
        },

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

        showStatus(msg, type = 'success') {
            this.statusMessage = msg;
            this.statusType = type;
            setTimeout(() => {
                if (this.statusMessage === msg) this.statusMessage = '';
            }, 5000);
        },

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
