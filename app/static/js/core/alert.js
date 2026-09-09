/**
 * SmallBook - Global Native UI Alert & Confirmation Modal System
 * Provides window.showAppAlert(), window.showAppConfirm(), window.closeAppAlert()
 * and transparently overrides window.alert() with styled in-app dialogs.
 */

(function initGlobalAlertModal() {
    let activeResolver = null;

    const TYPE_CONFIG = {
        warning: {
            box: 'bg-amber-500/10 dark:bg-amber-400/10 border-amber-500/25 dark:border-amber-400/25 text-amber-600 dark:text-amber-400',
            icon: 'hourglass_top',
            defaultTitle: 'Notice',
            btnText: 'Understood'
        },
        error: {
            box: 'bg-error/10 dark:bg-red-500/10 border-error/25 dark:border-red-500/25 text-error dark:text-red-400',
            icon: 'error',
            defaultTitle: 'Something Went Wrong',
            btnText: 'Dismiss'
        },
        success: {
            box: 'bg-emerald-500/10 dark:bg-emerald-400/10 border-emerald-500/25 dark:border-emerald-400/25 text-emerald-600 dark:text-emerald-400',
            icon: 'check_circle',
            defaultTitle: 'Success',
            btnText: 'Done'
        },
        info: {
            box: 'bg-blue-500/10 dark:bg-blue-400/10 border-blue-500/25 dark:border-blue-400/25 text-blue-600 dark:text-blue-400',
            icon: 'info',
            defaultTitle: 'Information',
            btnText: 'Got it'
        }
    };

    function resolveProps(message, options = {}) {
        const text = String(message ?? '');
        const lower = text.toLowerCase();

        let type = options.type;
        if (!type) {
            if (lower.includes('cooldown') || lower.includes('wait ') || lower.includes('minute(s)')) {
                type = 'warning';
            } else if (lower.includes('error') || lower.includes('failed') || lower.includes('cannot') || lower.includes('could not') || lower.includes('denied') || lower.includes('invalid')) {
                type = 'error';
            } else if (lower.includes('success') || lower.includes('saved') || lower.includes('completed')) {
                type = 'success';
            } else {
                type = 'info';
            }
        }

        const config = TYPE_CONFIG[type] || TYPE_CONFIG.info;

        let title = options.title;
        if (!title) {
            if (lower.includes('cooldown')) {
                title = 'Cooldown Active';
            } else {
                title = config.defaultTitle;
            }
        }

        let icon = options.icon;
        if (!icon) {
            if (lower.includes('cooldown')) {
                icon = 'hourglass_top';
            } else {
                icon = config.icon;
            }
        }

        let btnText = options.buttonText || (options.confirm ? 'Confirm' : config.btnText);

        return {
            text,
            type,
            title,
            icon,
            btnText,
            subtitle: options.subtitle || null,
            confirm: !!options.confirm,
            cancelText: options.cancelText || 'Cancel'
        };
    }

    function displayModal(props, resolve) {
        activeResolver = resolve;
        const modal = document.getElementById('app-alert-modal');
        const card = document.getElementById('app-alert-card');
        if (!modal || !card) {
            resolve(true);
            return;
        }

        const titleEl = document.getElementById('app-alert-title');
        const subtitleEl = document.getElementById('app-alert-subtitle');
        const msgEl = document.getElementById('app-alert-message');
        const iconEl = document.getElementById('app-alert-icon');
        const iconBox = document.getElementById('app-alert-icon-container');
        const confirmBtn = document.getElementById('app-alert-confirm-btn');
        const confirmText = document.getElementById('app-alert-confirm-text');
        const cancelBtn = document.getElementById('app-alert-cancel-btn');

        if (titleEl) titleEl.textContent = props.title;
        if (subtitleEl) {
            if (props.subtitle) {
                subtitleEl.textContent = props.subtitle;
                subtitleEl.classList.remove('hidden');
            } else {
                subtitleEl.classList.add('hidden');
            }
        }
        if (msgEl) msgEl.textContent = props.text;
        if (iconEl) iconEl.textContent = props.icon;

        if (iconBox) {
            const cfg = TYPE_CONFIG[props.type] || TYPE_CONFIG.info;
            iconBox.className = 'h-11 w-11 rounded-2xl flex items-center justify-center flex-shrink-0 transition-colors border ' + cfg.box;
        }

        if (confirmText) confirmText.textContent = props.btnText;

        if (cancelBtn) {
            if (props.confirm) {
                cancelBtn.classList.remove('hidden');
                cancelBtn.textContent = props.cancelText;
            } else {
                cancelBtn.classList.add('hidden');
            }
        }

        // Show modal & trigger scale-in
        modal.classList.remove('hidden');
        requestAnimationFrame(() => {
            card.classList.remove('scale-95', 'opacity-0');
            card.classList.add('scale-100', 'opacity-100');
        });

        if (confirmBtn) {
            setTimeout(() => confirmBtn.focus(), 60);
        }
    }

    function closeAppAlert(result = true) {
        const modal = document.getElementById('app-alert-modal');
        const card = document.getElementById('app-alert-card');
        if (!modal) return;
        if (card) {
            card.classList.remove('scale-100', 'opacity-100');
            card.classList.add('scale-95', 'opacity-0');
        }
        setTimeout(() => {
            modal.classList.add('hidden');
            if (activeResolver) {
                const cb = activeResolver;
                activeResolver = null;
                cb(result);
            }
        }, 160);
    }

    window.showAppAlert = function(message, options = {}) {
        return new Promise((resolve) => {
            const props = resolveProps(message, options);
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => displayModal(props, resolve), { once: true });
            } else {
                displayModal(props, resolve);
            }
        });
    };

    window.showAppConfirm = function(message, options = {}) {
        return window.showAppAlert(message, { ...options, confirm: true });
    };

    window.closeAppAlert = closeAppAlert;

    // Global override of standard browser alert
    window.alert = function(message) {
        window.showAppAlert(message);
    };

    function initAlertEvents() {
        const confirmBtn = document.getElementById('app-alert-confirm-btn');
        const cancelBtn = document.getElementById('app-alert-cancel-btn');
        const closeBtn = document.getElementById('app-alert-close-btn');
        const modal = document.getElementById('app-alert-modal');

        if (confirmBtn) confirmBtn.addEventListener('click', () => closeAppAlert(true));
        if (cancelBtn) cancelBtn.addEventListener('click', () => closeAppAlert(false));
        if (closeBtn) closeBtn.addEventListener('click', () => closeAppAlert(false));
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeAppAlert(false);
            });
        }

        document.addEventListener('keydown', (e) => {
            if (!modal || modal.classList.contains('hidden')) return;
            if (e.key === 'Escape') {
                e.preventDefault();
                closeAppAlert(false);
            } else if (e.key === 'Enter' && !e.shiftKey) {
                if (document.activeElement !== cancelBtn) {
                    e.preventDefault();
                    closeAppAlert(true);
                }
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAlertEvents);
    } else {
        initAlertEvents();
    }
})();
