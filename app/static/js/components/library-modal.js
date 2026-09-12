/**
 * @fileoverview Sources Library Modal Alpine Component.
 * Manages the global cross-notebook document library modal, client-side searching,
 * sorting, byte size formatting, and permanent global document deletion.
 */

/* ==========================================================================
   SOURCES LIBRARY MODAL COMPONENT REGISTRATION
   ========================================================================== */

document.addEventListener('alpine:init', () => {
    Alpine.data('sourcesLibraryModal', () => ({
        // State
        isOpen: false,
        isLoading: false,
        sources: [],
        searchQuery: '',
        sortBy: 'recent', // 'recent', 'oldest', 'name'

        // Deletion confirmation state
        isDeleteConfirmOpen: false,
        sourceToDelete: null,
        isDeleting: false,

        /**
         * Opens library modal and initiates source fetching.
         */
        openModal() {
            this.isOpen = true;
            this.fetchSources();
        },

        /**
         * Closes library modal.
         */
        closeModal() {
            this.isOpen = false;
        },

        /**
         * Fetches all user documents across all notebooks from backend.
         * @returns {Promise<void>}
         */
        async fetchSources() {
            this.isLoading = true;
            try {
                const res = await fetch('/api/sources/all');
                if (!res.ok) throw new Error('Failed to fetch sources');
                const data = await res.json();
                this.sources = data.sources || [];
            } catch (err) {
                console.error('Error loading sources library:', err);
            } finally {
                this.isLoading = false;
            }
        },

        /**
         * Computed getter filtering sources by query and sorting by selected metric.
         * @returns {Array<Object>} Sorted and filtered source items.
         */
        get sortedAndFilteredSources() {
            let list = this.sources.filter(s => {
                const q = this.searchQuery.toLowerCase();
                const nameMatch = (s.original_filename || '').toLowerCase().includes(q);
                const nbMatch = (s.notebooks || []).some(nb => (nb.title || '').toLowerCase().includes(q));
                return nameMatch || nbMatch;
            });

            return list.sort((a, b) => {
                if (this.sortBy === 'recent') {
                    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
                } else if (this.sortBy === 'oldest') {
                    return new Date(a.created_at || 0) - new Date(b.created_at || 0);
                } else if (this.sortBy === 'name') {
                    return (a.original_filename || '').localeCompare(b.original_filename || '');
                }
            });
        },

        /**
         * Formats byte count into human-readable unit string (KB, MB, GB).
         * @param {number} bytes - Byte count.
         * @returns {string} Formatted size string.
         */
        formatBytes(bytes) {
            if (!bytes || bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        },

        /**
         * Formats ISO date string into localized short date.
         * @param {string} dateStr - ISO date string.
         * @returns {string} Formatted date (e.g. "Jul 3, 2026").
         */
        formatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        },

        /**
         * Opens confirmation modal before permanent document deletion.
         * @param {Object} source - Target source document object.
         */
        confirmDeleteSource(source) {
            this.sourceToDelete = source;
            this.isDeleteConfirmOpen = true;
        },

        /**
         * Cancels active deletion and resets modal state.
         */
        cancelDelete() {
            this.isDeleteConfirmOpen = false;
            this.sourceToDelete = null;
            this.isDeleting = false;
        },

        /**
         * Sends permanent deletion request to backend and removes source from state.
         * @returns {Promise<void>}
         */
        async executeDeleteSource() {
            if (!this.sourceToDelete) return;
            this.isDeleting = true;
            try {
                const res = await fetch(`/api/sources/${this.sourceToDelete.id}`, {
                    method: 'DELETE'
                });
                if (!res.ok) throw new Error('Failed to delete source');

                this.sources = this.sources.filter(s => s.id !== this.sourceToDelete.id);
                this.cancelDelete();
            } catch (err) {
                console.error('Error deleting source:', err);
                if (typeof window.showAppAlert === 'function') {
                    window.showAppAlert(err.message || 'Error deleting source', { title: 'Delete Failed', type: 'error' });
                }
                this.cancelDelete();
            }
        }
    }));
});
