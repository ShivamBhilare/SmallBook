/**
 * SmallBook - Theme Management & Session Sign-Out
 */

// Initial Theme Check to prevent FOUC
(function applyInitialTheme() {
    const stored = localStorage.getItem('theme');
    if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
})();

function syncThemeUI() {
    const isDark = document.documentElement.classList.contains('dark');
    document.querySelectorAll('.theme-icon').forEach(icon => {
        icon.innerText = isDark ? 'light_mode' : 'dark_mode';
    });
}

function toggleTheme() {
    document.documentElement.classList.toggle('dark');
    const isDark = document.documentElement.classList.contains('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    syncThemeUI();
}

// Sync icons on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncThemeUI);
} else {
    syncThemeUI();
}

// Fast theme restoration and BFCache handling on Back/Forward navigation
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

// Global user session sign-out
async function signOut() {
    try {
        await fetch('/auth/api/sign-out', { method: 'POST' });
    } catch (e) {
        console.error('Sign out error:', e);
    } finally {
        window.location.href = '/auth/sign-in';
    }
}
