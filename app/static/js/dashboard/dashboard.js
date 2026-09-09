/**
 * SmallBook - Notebooks Dashboard Alpine.js Component
 * Handles notebook listing, client-side searching, sorting, grid/list view toggles,
 * creation modals, and deletion workflows.
 */
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

        // Initialize Component
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

        // Fetch Notebooks on load
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

        // Computed property for sorting and searching
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

        // Format date to string like "JUL 3, 2026"
        formatDateUpper(dateString) {
            if (!dateString) return '';
            const date = new Date(dateString);
            return date.toLocaleDateString('en-US', { 
                month: 'short', 
                day: 'numeric', 
                year: 'numeric' 
            }).toUpperCase();
        },

        // Close Modal & Reset Form
        closeModal() {
            this.isCreateModalOpen = false;
            this.newNotebookTitle = '';
            this.newNotebookProvider = '';
            this.modalError = '';
        },

        // Submit New Notebook and Redirect
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

        // Open Delete Modal
        confirmDelete(id) {
            this.notebookToDelete = id;
            this.activeMenu = null;
            this.isDeleteModalOpen = true;
        },

        // Close Delete Modal
        cancelDelete() {
            this.isDeleteModalOpen = false;
            this.notebookToDelete = null;
            this.isDeleting = false;
        },

        // Execute Delete Request
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
