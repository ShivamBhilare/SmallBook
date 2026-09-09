/**
 * SmallBook - Sources Library Modal Alpine Component
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('sourcesLibraryModal', () => ({
        isOpen: false,
        isLoading: false,
        sources: [],
        searchQuery: '',
        sortBy: 'recent', // 'recent', 'oldest', 'name'
        
        isDeleteConfirmOpen: false,
        sourceToDelete: null,
        isDeleting: false,

        openModal() {
            this.isOpen = true;
            this.fetchSources();
        },

        closeModal() {
            this.isOpen = false;
        },

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

        formatBytes(bytes) {
            if (!bytes || bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        },

        formatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        },

        confirmDeleteSource(source) {
            this.sourceToDelete = source;
            this.isDeleteConfirmOpen = true;
        },

        cancelDelete() {
            this.isDeleteConfirmOpen = false;
            this.sourceToDelete = null;
            this.isDeleting = false;
        },

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
