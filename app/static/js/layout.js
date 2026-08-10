/**
 * IMS Performance Manager – Enterprise Application Shell
 * PR #2 | layout.js
 * Manages: sidebar drawer, mobile toggle, theme switching, notifications
 * Does NOT change any backend behavior or business logic.
 */

(function () {
    'use strict';

    /* ─── ELEMENTS ─────────────────────────────────────────── */
    const sidebar        = document.getElementById('appSidebar');
    const overlay        = document.getElementById('sidebarOverlay');
    const toggleBtn      = document.getElementById('sidebarToggleBtn');
    const closeBtn       = document.getElementById('sidebarCloseBtn');
    const themeBtn       = document.getElementById('themeToggleBtn');
    const themeIcon      = document.getElementById('themeIcon');
    const userMenuButton = document.getElementById('userDropdown');
    const userMenu       = userMenuButton ? userMenuButton.nextElementSibling : null;

    /* ─── HELPERS ──────────────────────────────────────────── */
    function isMobile() {
        return window.innerWidth < 992;
    }

    /* ─── SIDEBAR DRAWER (mobile) ──────────────────────────── */
    function openDrawer() {
        if (!sidebar || !overlay) return;
        sidebar.classList.add('drawer-open');
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'true');
    }

    function closeDrawer() {
        if (!sidebar || !overlay) return;
        sidebar.classList.remove('drawer-open');
        overlay.classList.remove('active');
        document.body.style.overflow = '';
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'false');
    }

    /* ─── SIDEBAR COLLAPSE (desktop) ──────────────────────── */
    function toggleDesktopSidebar() {
        document.body.classList.toggle('sidebar-collapsed');
        const collapsed = document.body.classList.contains('sidebar-collapsed');
        localStorage.setItem('sidebar-collapsed', collapsed ? '1' : '0');
        if (toggleBtn) toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }

    function restoreDesktopState() {
        if (localStorage.getItem('sidebar-collapsed') === '1') {
            document.body.classList.add('sidebar-collapsed');
        }
    }

    /* ─── UNIFIED TOGGLE ───────────────────────────────────── */
    function handleToggle() {
        if (isMobile()) {
            if (sidebar && sidebar.classList.contains('drawer-open')) {
                closeDrawer();
            } else {
                openDrawer();
            }
        } else {
            toggleDesktopSidebar();
        }
    }

    /* ─── THEME SWITCHING ──────────────────────────────────── */
    const THEME_KEY = 'ims-theme';

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        document.body.setAttribute('data-theme', theme);
        if (themeIcon) {
            themeIcon.className = theme === 'dark'
                ? 'bi bi-sun-fill'
                : 'bi bi-moon-stars-fill';
        }
        if (themeBtn) {
            themeBtn.title = theme === 'dark' ? 'Açık Temaya Geç' : 'Koyu Temaya Geç';
        }
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next    = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        localStorage.setItem(THEME_KEY, next);
    }

    function restoreTheme() {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved) {
            applyTheme(saved);
        }
    }

    /* ─── NOTIFICATIONS ─────────────────────────────────────── */
    function updateNotificationBadge() {
        const badge = document.querySelector('.notification-badge');
        if (!badge) return;
        const count = parseInt(badge.textContent, 10) || 0;
        if (count === 0) {
            badge.classList.add('hidden');
        } else {
            badge.classList.remove('hidden');
        }
    }

    /* ─── ACTIVE NAV LINK HIGHLIGHT ────────────────────────── */
    function highlightActiveNav() {
        const currentPath = window.location.pathname;
        const links = document.querySelectorAll('.sidebar-nav-link');
        links.forEach(function (link) {
            const href = link.getAttribute('href');
            if (!href || href === '#') return;
            // Exact match or starts-with for nested routes
            if (currentPath === href || (href !== '/' && currentPath.startsWith(href))) {
                link.classList.add('active');
            }
        });
    }

    /* ─── DROPDOWN ACCESSIBLE CLOSE ────────────────────────── */
    function setupDropdownKeyClose() {
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeDrawer();
                // Bootstrap dropdowns handle their own Escape
            }
        });
    }

    function setupUserMenu() {
        if (!userMenuButton || !userMenu) return;
        userMenuButton.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            const isOpen = userMenu.classList.toggle('show');
            userMenuButton.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
        document.addEventListener('click', function (event) {
            if (!event.target.closest('#userDropdown') && !event.target.closest('.user-dropdown')) {
                userMenu.classList.remove('show');
                userMenuButton.setAttribute('aria-expanded', 'false');
            }
        });
    }

    /* ─── RESIZE HANDLER ────────────────────────────────────── */
    let resizeTimer;
    function onResize() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            if (!isMobile()) {
                // Close drawer when viewport widens past mobile breakpoint
                closeDrawer();
            }
        }, 100);
    }

    /* ─── SMOOTH FOCUS FLASH ON PAGE LOAD ─────────────────── */
    function markPageReady() {
        document.body.classList.add('page-ready');
    }

    /* ─── INIT ──────────────────────────────────────────────── */
    function init() {
        // Restore state before first paint
        restoreTheme();
        if (!isMobile()) {
            restoreDesktopState();
        }

        // Event listeners
        if (toggleBtn) {
            toggleBtn.addEventListener('click', handleToggle);
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', closeDrawer);
        }
        if (overlay) {
            overlay.addEventListener('click', closeDrawer);
        }
        if (themeBtn) {
            themeBtn.addEventListener('click', toggleTheme);
        }

        window.addEventListener('resize', onResize);

        // Runtime setup
        updateNotificationBadge();
        highlightActiveNav();
        setupDropdownKeyClose();
        setupUserMenu();

        // Slight delay so CSS transitions play smoothly on load
        requestAnimationFrame(markPageReady);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

}());
