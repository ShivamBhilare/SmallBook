/**
 * @fileoverview Theme Management & Session Sign-Out Module.
 * Controls dark/light mode toggles, persists user theme preferences in localStorage,
 * synchronizes Material Symbol icons across DOM elements, handles BFCache page restoration,
 * and coordinates global session logout flows.
 */

/* ==========================================================================
   INITIAL THEME INITIALIZATION (Prevents Flash of Unstyled Content - FOUC)
   ========================================================================== */

(function applyInitialTheme() {
    const stored = localStorage.getItem('theme');
    if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
})();

/* ==========================================================================
   THEME SYNCHRONIZATION & TOGGLE FUNCTIONS
   ========================================================================== */

/**
 * Synchronizes theme icons in the DOM based on current document class state.
 */
function syncThemeUI() {
    const isDark = document.documentElement.classList.contains('dark');
    document.querySelectorAll('.theme-icon').forEach(icon => {
        icon.innerText = isDark ? 'light_mode' : 'dark_mode';
    });
}

/**
 * Toggles the document root between light and dark modes, persists setting,
 * and updates UI indicator icons.
 */
function toggleTheme() {
    document.documentElement.classList.toggle('dark');
    const isDark = document.documentElement.classList.contains('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    syncThemeUI();
}

// Sync icons on initial page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncThemeUI);
} else {
    syncThemeUI();
}

/* ==========================================================================
   BFCACHE & BACK/FORWARD NAVIGATION RESTORATION
   ========================================================================== */

/**
 * Fast theme restoration and BFCache handling on Back/Forward navigation.
 */
window.addEventListener('pageshow', (event) => {
    const storedTheme = localStorage.getItem('theme');
    if (storedTheme === 'dark') {
        document.documentElement.classList.add('dark');
    } else if (storedTheme === 'light') {
        document.documentElement.classList.remove('dark');
    }
    syncThemeUI();

    if (event.persisted) {
        window.location.reload();
    }
});

/* ==========================================================================
   GLOBAL USER LOGOUT
   ========================================================================== */

/**
 * Initiates user session sign-out via the backend API and redirects to sign-in.
 *
 * @returns {Promise<void>}
 */
async function signOut() {
    try {
        await fetch('/auth/api/sign-out', { method: 'POST' });
    } catch (e) {
        console.error('Sign out error:', e);
    } finally {
        window.location.href = '/auth/sign-in';
    }
}
