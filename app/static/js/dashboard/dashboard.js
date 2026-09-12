/**
 * @fileoverview Notebooks Dashboard Alpine.js Component.
 * Manages user notebook collections, real-time client search filtering, multi-metric sorting,
 * grid/list view mode switching with localStorage persistence, new notebook creation,
 * and workspace deletion dialogs.
 */

/* ==========================================================================
   DASHBOARD COMPONENT REGISTRATION
   ========================================================================== */

document.addEventListener('alpine:init', () => {
    Alpine.data('notebookDashboard', () => ({
        // State
        notebooks: [],
        isLoading: true,
        searchQuery: '',
        viewMode: localStorage.getItem('viewMode') || 'grid', // 'grid' or 'list' loaded from storage
        sortBy: 'recent', // 'recent', 'oldest', 'title'
        activeMenu: null, // Tracks currently open dropdown menu

        // Modal Form State
        isCreateModalOpen: false,
        newNotebookTitle: '',
        newNotebookProvider: '',
        isCreating: false,

        isDeleteModalOpen: false,
        notebookToDelete: null,
        isDeleting: false,

        // Error States
        errorMessage: '',
        modalError: '',

        /**
         * Initializes dashboard, fetches notebook records, binds viewMode watcher,
         * and parses query parameters for auto-opening the create modal.
         */
        init() {
            this.fetchNotebooks();
            this.$watch('viewMode', value => localStorage.setItem('viewMode', value));
            if (new URLSearchParams(window.location.search).get('create') === '1') {
                this.isCreateModalOpen = true;
                // Clean up URL query parameter without refresh
                const url = new URL(window.location.href);
                url.searchParams.delete('create');
                window.history.replaceState({}, '', url.toString());
            }
        },

        /**
         * Loads all notebook records owned by the authenticated user from the backend API.
         * @returns {Promise<void>}
         */
        async fetchNotebooks() {
            this.isLoading = true;
            this.errorMessage = '';
            try {
                const response = await fetch('/notebooks/api/list');
                if (!response.ok) throw new Error('Failed to fetch notebooks');
                const data = await response.json();
                this.notebooks = data.notebooks || [];
            } catch (error) {
                this.errorMessage = error.message || 'An error occurred while loading notebooks.';
            } finally {
                this.isLoading = false;
            }
        },

        /**
         * Computed getter filtering notebooks by search query and sorting by selected metric.
         * @returns {Array<Object>} Sorted and filtered notebook items.
         */
        get filteredNotebooks() {
            let filtered = this.notebooks.filter(nb =>
                nb.title.toLowerCase().includes(this.searchQuery.toLowerCase())
            );

            return filtered.sort((a, b) => {
                if (this.sortBy === 'recent') {
                    return new Date(b.created_at) - new Date(a.created_at);
                } else if (this.sortBy === 'oldest') {
                    return new Date(a.created_at) - new Date(b.created_at);
                } else if (this.sortBy === 'title') {
                    return a.title.localeCompare(b.title);
                }
            });
        },

        /**
         * Formats an ISO date string into an uppercase date string (e.g., "JUL 3, 2026").
         * @param {string} dateString - ISO date string.
         * @returns {string} Formatted uppercase date.
         */
        formatDateUpper(dateString) {
            if (!dateString) return '';
            const date = new Date(dateString);
            return date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            }).toUpperCase();
        },

        /**
         * Closes create modal and resets input fields.
         */
        closeModal() {
            this.isCreateModalOpen = false;
            this.newNotebookTitle = '';
            this.newNotebookProvider = '';
            this.modalError = '';
        },

        /**
         * Submits creation payload for a new notebook and redirects to its workspace.
         * @returns {Promise<void>}
         */
        async submitCreateNotebook() {
            this.isCreating = true;
            this.modalError = '';
            try {
                const response = await fetch('/notebooks/api/create', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        title: this.newNotebookTitle || "Untitled SmallBook",
                        preferred_llm_provider: this.newNotebookProvider || null
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to create notebook');
                }

                const data = await response.json();

                // REDIRECT TO WORKSPACE ON SUCCESS
                window.location.href = `/notebooks/workspace/${data.notebook.id}`;

            } catch (error) {
                this.modalError = error.message;
                this.isCreating = false;
            }
        },

        /**
         * Opens confirmation dialog before notebook deletion.
         * @param {string} id - UUID of the notebook to delete.
         */
        confirmDelete(id) {
            this.notebookToDelete = id;
            this.activeMenu = null;
            this.isDeleteModalOpen = true;
        },

        /**
         * Closes deletion modal and resets target notebook ID.
         */
        cancelDelete() {
            this.isDeleteModalOpen = false;
            this.notebookToDelete = null;
            this.isDeleting = false;
        },

        /**
         * Dispatches DELETE request to backend and removes notebook from local state.
         * @returns {Promise<void>}
         */
        async executeDelete() {
            if (!this.notebookToDelete) return;

            this.isDeleting = true;
            try {
                const response = await fetch(`/notebooks/api/${this.notebookToDelete}`, {
                    method: 'DELETE'
                });

                if (!response.ok) throw new Error('Failed to delete notebook');

                // Remove from local state to update UI immediately
                this.notebooks = this.notebooks.filter(nb => nb.id !== this.notebookToDelete);
                this.cancelDelete();
            } catch (error) {
                this.errorMessage = error.message;
                this.cancelDelete();
            }
        }
    }));
});
