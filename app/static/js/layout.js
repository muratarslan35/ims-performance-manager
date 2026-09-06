/**
 * IMS Performance Manager – Enterprise Application Shell
 * Manages: sidebar drawer, mobile toggle, theme switching, notifications,
 * persistent IMS background-import progress, and global page navigation progress.
 */

(function () {
    'use strict';

    const sidebar        = document.getElementById('appSidebar');
    const overlay        = document.getElementById('sidebarOverlay');
    const toggleBtn      = document.getElementById('sidebarToggleBtn');
    const closeBtn       = document.getElementById('sidebarCloseBtn');
    const themeBtn       = document.getElementById('themeToggleBtn');
    const themeIcon      = document.getElementById('themeIcon');
    const userMenuButton = document.getElementById('userDropdown');
    const userMenu       = userMenuButton ? userMenuButton.nextElementSibling : null;

    function setupGlobalPageLoader() {
        if (document.getElementById('globalPageLoader')) return;

        const style = document.createElement('style');
        style.id = 'globalPageLoaderStyles';
        style.textContent = [
            '#globalPageLoader{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;background:rgba(244,247,251,.96);backdrop-filter:blur(8px);opacity:0;visibility:hidden;pointer-events:none;transition:opacity .18s ease,visibility .18s ease}',
            '#globalPageLoader.is-visible{opacity:1;visibility:visible;pointer-events:all}',
            '#globalPageLoader.is-complete{opacity:0;visibility:hidden;pointer-events:none}',
            '.global-page-loader-card{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:190px;padding:28px 32px;border:1px solid rgba(11,78,162,.12);border-radius:24px;background:rgba(255,255,255,.92);box-shadow:0 24px 70px rgba(15,23,42,.14)}',
            '.global-page-loader-ring{--page-load-progress:0deg;position:relative;width:108px;height:108px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#0b4ea2 var(--page-load-progress),rgba(11,78,162,.12) 0);box-shadow:0 12px 28px rgba(11,78,162,.16)}',
            '.global-page-loader-ring::before{content:"";position:absolute;inset:9px;border-radius:50%;background:#fff;box-shadow:inset 0 0 0 1px rgba(11,78,162,.06)}',
            '.global-page-loader-value{position:relative;z-index:1;font-size:25px;font-weight:900;letter-spacing:-.03em;color:#0b4ea2;font-variant-numeric:tabular-nums}',
            '.global-page-loader-label{margin-top:14px;font-size:13px;font-weight:800;letter-spacing:.04em;color:#42556f}',
            '.global-page-loader-sub{margin-top:3px;font-size:11px;color:#7b8ba0}',
            '[data-theme="dark"] #globalPageLoader{background:rgba(8,17,31,.96)}',
            '[data-theme="dark"] .global-page-loader-card{background:rgba(21,34,56,.94);border-color:#2d3e59;box-shadow:0 24px 70px rgba(0,0,0,.36)}',
            '[data-theme="dark"] .global-page-loader-ring{background:conic-gradient(#75b8ff var(--page-load-progress),rgba(117,184,255,.13) 0)}',
            '[data-theme="dark"] .global-page-loader-ring::before{background:#152238;box-shadow:inset 0 0 0 1px #2d3e59}',
            '[data-theme="dark"] .global-page-loader-value{color:#91c7ff}',
            '[data-theme="dark"] .global-page-loader-label{color:#dce7f5}',
            '[data-theme="dark"] .global-page-loader-sub{color:#91a4bd}',
            '@media(max-width:575.98px){.global-page-loader-card{min-width:170px;padding:24px 28px;border-radius:20px}.global-page-loader-ring{width:96px;height:96px}.global-page-loader-value{font-size:23px}}',
            '@media(prefers-reduced-motion:reduce){#globalPageLoader{transition:none}}'
        ].join('');
        document.head.appendChild(style);

        const loader = document.createElement('div');
        loader.id = 'globalPageLoader';
        loader.setAttribute('role', 'status');
        loader.setAttribute('aria-live', 'polite');
        loader.setAttribute('aria-hidden', 'true');
        loader.innerHTML = '<div class="global-page-loader-card">' +
            '<div class="global-page-loader-ring" id="globalPageLoaderRing">' +
            '<span class="global-page-loader-value" id="globalPageLoaderValue">0%</span></div>' +
            '<div class="global-page-loader-label">Yükleniyor</div>' +
            '<div class="global-page-loader-sub">Sayfa hazırlanıyor</div></div>';
        document.body.appendChild(loader);

        const ring = document.getElementById('globalPageLoaderRing');
        const value = document.getElementById('globalPageLoaderValue');
        let current = 0;
        let timer = null;
        let finishing = false;

        function render(next) {
            current = Math.max(current, Math.min(Math.round(next), 100));
            value.textContent = current + '%';
            ring.style.setProperty('--page-load-progress', (current * 3.6) + 'deg');
        }

        function show(startAt) {
            finishing = false;
            current = 0;
            render(startAt || 4);
            loader.classList.remove('is-complete');
            loader.classList.add('is-visible');
            loader.setAttribute('aria-hidden', 'false');
            if (timer) window.clearInterval(timer);
            timer = window.setInterval(function () {
                if (finishing) return;
                const remaining = 92 - current;
                if (remaining <= 0) return;
                render(current + Math.max(1, Math.ceil(remaining * 0.09)));
            }, 180);
        }

        function finish() {
            if (!loader.classList.contains('is-visible')) return;
            finishing = true;
            if (timer) {
                window.clearInterval(timer);
                timer = null;
            }
            const finishTimer = window.setInterval(function () {
                if (current >= 100) {
                    window.clearInterval(finishTimer);
                    window.setTimeout(function () {
                        loader.classList.add('is-complete');
                        loader.classList.remove('is-visible');
                        loader.setAttribute('aria-hidden', 'true');
                    }, 140);
                    return;
                }
                render(Math.min(100, current + Math.max(1, Math.ceil((100 - current) * 0.32))));
            }, 28);
        }

        function isSameOriginNavigation(anchor, event) {
            if (!anchor || event.defaultPrevented || event.button !== 0) return false;
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
            if (anchor.target && anchor.target !== '_self') return false;
            if (anchor.hasAttribute('download')) return false;
            const href = anchor.getAttribute('href');
            if (!href || href.startsWith('#') || href.startsWith('javascript:')) return false;
            try {
                const url = new URL(anchor.href, window.location.href);
                if (url.origin !== window.location.origin) return false;
                if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return false;
                return true;
            } catch (_error) {
                return false;
            }
        }

        document.addEventListener('click', function (event) {
            const anchor = event.target.closest('a[href]');
            if (isSameOriginNavigation(anchor, event)) show(5);
        }, true);

        document.addEventListener('submit', function (event) {
            if (event.defaultPrevented) return;
            const form = event.target;
            if (!(form instanceof HTMLFormElement)) return;
            const target = (form.getAttribute('target') || '').toLowerCase();
            if (target && target !== '_self') return;
            show(5);
        }, true);

        window.addEventListener('pageshow', function (event) {
            if (event.persisted) finish();
        });
        window.addEventListener('load', finish, { once: true });

        window.IMSPageLoader = { show: show, finish: finish, setProgress: render };
    }

    function isMobile() {
        return window.innerWidth < 992;
    }

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

    function handleToggle() {
        if (isMobile()) {
            if (sidebar && sidebar.classList.contains('drawer-open')) closeDrawer();
            else openDrawer();
        } else {
            toggleDesktopSidebar();
        }
    }

    const THEME_KEY = 'ims-theme';

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        document.body.setAttribute('data-theme', theme);
        if (themeIcon) {
            themeIcon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
        }
        if (themeBtn) {
            themeBtn.title = theme === 'dark' ? 'Açık Temaya Geç' : 'Koyu Temaya Geç';
        }
        window.dispatchEvent(new CustomEvent('ims:theme-change', { detail: { theme: theme } }));
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        localStorage.setItem(THEME_KEY, next);
    }

    function restoreTheme() {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved) applyTheme(saved);
    }

    function updateNotificationBadge() {
        const badge = document.querySelector('.notification-badge');
        if (!badge) return;
        const count = parseInt(badge.textContent, 10) || 0;
        if (count === 0) badge.classList.add('hidden');
        else badge.classList.remove('hidden');
    }

    function renderImportNotifications(jobs) {
        const container = document.getElementById('imsImportNotifications');
        const empty = document.getElementById('notificationsEmpty');
        const countLabel = document.getElementById('notificationCount');
        const badge = document.querySelector('.notification-badge');
        if (!container || !empty || !countLabel || !badge) return;
        const active = (jobs || []).filter(function (job) {
            return ['QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED'].includes(job.status);
        });
        const unread = active.filter(function (job) {
            return ['QUEUED', 'PROCESSING', 'FAILED'].includes(job.status);
        }).length;
        badge.textContent = String(unread);
        badge.setAttribute('aria-label', unread + ' okunmamış bildirim');
        countLabel.textContent = unread + ' Yeni';
        empty.classList.toggle('d-none', active.length > 0);
        container.innerHTML = active.map(function (job) {
            const period = job.month + '/' + job.year;
            let icon = 'bi-hourglass-split';
            let text = period + ' IMS sırada bekliyor';
            let tone = 'text-primary';
            if (job.status === 'PROCESSING') text = period + ' IMS işleniyor';
            if (job.status === 'COMPLETED') {
                icon = 'bi-check-circle-fill';
                tone = 'text-success';
                text = period + ' IMS başarıyla tamamlandı — raporu aç';
            }
            if (job.status === 'FAILED') {
                icon = 'bi-exclamation-triangle-fill';
                tone = 'text-danger';
                text = 'IMS yüklenemedi — hata raporunu aç';
            }
            return '<a class="list-group-item list-group-item-action" href="/ims">' +
                '<i class="bi ' + icon + ' ' + tone + ' me-2"></i>' +
                '<span>' + text + '</span><small class="d-block text-muted">' +
                job.file_name.replace(/[&<>"']/g, '') + '</small></a>';
        }).join('');
        updateNotificationBadge();
    }

    function refreshImportNotifications() {
        if (!document.getElementById('imsImportNotifications')) return;
        fetch('/ims/import-jobs', {headers: {'Accept': 'application/json'}})
            .then(function (response) { return response.ok ? response.json() : Promise.reject(); })
            .then(function (payload) { renderImportNotifications(payload.jobs); })
            .catch(function () {});
    }

    function setupImsProgressBar() {
        if (!window.location.pathname.startsWith('/ims')) return;
        const hero = document.querySelector('.ims-hero');
        if (!hero || document.getElementById('imsRealProgress')) return;

        const style = document.createElement('style');
        style.textContent = [
            '#imsRealProgress{display:none;margin:0 0 16px;border:1px solid rgba(25,135,84,.28);border-radius:14px;background:rgba(25,135,84,.08);overflow:hidden;color:var(--bs-body-color,#1c3558)}',
            '#imsRealProgress.visible{display:block}',
            '#imsRealProgress.failed{border-color:rgba(220,53,69,.32);background:rgba(220,53,69,.08)}',
            '.ims-real-progress-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px 8px}',
            '.ims-real-progress-copy{min-width:0;display:flex;align-items:center;gap:10px}',
            '.ims-real-progress-icon{font-size:20px;color:#198754;flex:0 0 auto}',
            '#imsRealProgress.failed .ims-real-progress-icon{color:#dc3545}',
            '.ims-real-progress-message{font-size:14px;font-weight:800;line-height:1.25}',
            '.ims-real-progress-detail{font-size:11px;opacity:.72;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
            '.ims-real-progress-percent{font-size:20px;font-weight:900;color:#198754;flex:0 0 auto}',
            '#imsRealProgress.failed .ims-real-progress-percent{color:#dc3545}',
            '.ims-real-progress-track{height:8px;background:rgba(25,135,84,.13)}',
            '.ims-real-progress-fill{height:100%;width:0;background:#198754;transition:width .35s ease}',
            '#imsRealProgress.failed .ims-real-progress-track{background:rgba(220,53,69,.13)}',
            '#imsRealProgress.failed .ims-real-progress-fill{background:#dc3545}',
            '@media(max-width:575.98px){.ims-real-progress-head{align-items:flex-start}.ims-real-progress-percent{font-size:18px}.ims-real-progress-detail{white-space:normal}}'
        ].join('');
        document.head.appendChild(style);

        const bar = document.createElement('div');
        bar.id = 'imsRealProgress';
        bar.setAttribute('role', 'status');
        bar.setAttribute('aria-live', 'polite');
        bar.innerHTML = '<div class="ims-real-progress-head">' +
            '<div class="ims-real-progress-copy"><i class="bi bi-arrow-repeat ims-real-progress-icon"></i>' +
            '<div><div class="ims-real-progress-message" id="imsRealProgressMessage">IMS yükleme durumu kontrol ediliyor</div>' +
            '<div class="ims-real-progress-detail" id="imsRealProgressDetail"></div></div></div>' +
            '<div class="ims-real-progress-percent" id="imsRealProgressPercent">0%</div></div>' +
            '<div class="ims-real-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">' +
            '<div class="ims-real-progress-fill" id="imsRealProgressFill"></div></div>';
        hero.parentNode.insertBefore(bar, hero);

        const message = document.getElementById('imsRealProgressMessage');
        const detail = document.getElementById('imsRealProgressDetail');
        const percent = document.getElementById('imsRealProgressPercent');
        const fill = document.getElementById('imsRealProgressFill');
        const track = bar.querySelector('[role="progressbar"]');
        const icon = bar.querySelector('.ims-real-progress-icon');
        let timer = null;

        function render(payload) {
            if (!payload || !payload.progress) {
                bar.classList.remove('visible');
                return false;
            }
            const item = payload.progress;
            const value = Math.max(0, Math.min(parseInt(item.percent, 10) || 0, 100));
            const failed = item.status === 'FAILED';
            const completed = item.status === 'COMPLETED';
            bar.classList.add('visible');
            bar.classList.toggle('failed', failed);
            message.textContent = item.message || 'IMS yüklemesi işleniyor';
            detail.textContent = [item.detail, item.file_name].filter(Boolean).join(' · ');
            percent.textContent = value + '%';
            fill.style.width = value + '%';
            track.setAttribute('aria-valuenow', String(value));
            icon.className = 'bi ' + (failed ? 'bi-exclamation-triangle-fill' : completed ? 'bi-check-circle-fill' : 'bi-arrow-repeat') + ' ims-real-progress-icon';
            return Boolean(payload.active);
        }

        function refresh() {
            fetch('/ims/progress', {headers: {'Accept': 'application/json'}, cache: 'no-store'})
                .then(function (response) { return response.ok ? response.json() : Promise.reject(); })
                .then(function (payload) {
                    const active = render(payload);
                    if (timer) window.clearTimeout(timer);
                    timer = window.setTimeout(refresh, active ? 2500 : 10000);
                })
                .catch(function () {
                    if (timer) window.clearTimeout(timer);
                    timer = window.setTimeout(refresh, 10000);
                });
        }

        refresh();
    }

    function highlightActiveNav() {
        const currentPath = window.location.pathname;
        const links = document.querySelectorAll('.sidebar-nav-link');
        links.forEach(function (link) {
            const href = link.getAttribute('href');
            if (!href || href === '#') return;
            if (currentPath === href || (href !== '/' && currentPath.startsWith(href))) {
                link.classList.add('active');
            }
        });
    }

    function setupDropdownKeyClose() {
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeDrawer();
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

    let resizeTimer;
    function onResize() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            if (!isMobile()) closeDrawer();
        }, 100);
    }

    function markPageReady() {
        document.body.classList.add('page-ready');
    }

    function init() {
        setupGlobalPageLoader();
        restoreTheme();
        if (!isMobile()) restoreDesktopState();

        if (toggleBtn) toggleBtn.addEventListener('click', handleToggle);
        if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
        if (overlay) overlay.addEventListener('click', closeDrawer);
        if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

        window.addEventListener('resize', onResize);
        updateNotificationBadge();
        refreshImportNotifications();
        window.setInterval(refreshImportNotifications, 15000);
        setupImsProgressBar();
        highlightActiveNav();
        setupDropdownKeyClose();
        setupUserMenu();
        requestAnimationFrame(markPageReady);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

}());
