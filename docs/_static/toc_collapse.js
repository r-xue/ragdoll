/**
 * toc_collapse.js
 *
 * Adds a collapse/expand toggle button to the right-side Table of Contents (TOC)
 * drawer in the Furo Sphinx theme. The collapsed state is persisted in localStorage
 * across page navigations.
 *
 * Only activates on desktop viewports (min-width: 82em) where Furo displays
 * the TOC inline. On smaller screens, Furo's mobile overlay handles the TOC.
 */
(function () {
    'use strict';

    function init() {
        var tocDrawer = document.querySelector('.toc-drawer');
        if (!tocDrawer || tocDrawer.classList.contains('no-toc')) return;

        // Only active on desktop screens where Furo displays the inline TOC drawer
        if (!window.matchMedia('(min-width: 82em)').matches) return;

        var isCollapsed = localStorage.getItem('ragdoll-toc-collapsed') === 'true';

        var btn = document.createElement('button');
        btn.className = 'toc-toggle-btn';
        btn.setAttribute('aria-label', 'Toggle table of contents');
        btn.setAttribute('title', 'Toggle table of contents');

        // Set initial button position and icon with zero transition
        if (isCollapsed) {
            btn.style.right = '0px';
            btn.textContent = '\u276E'; // ❮
            tocDrawer.classList.add('toc-collapsed');
            if (tocDrawer.parentElement) tocDrawer.parentElement.classList.add('toc-collapsed');
        } else {
            btn.textContent = '\u276F'; // ❯
            var rect = tocDrawer.getBoundingClientRect();
            var offset = document.documentElement.clientWidth - rect.left;
            btn.style.right = Math.max(0, offset) + 'px';
        }

        document.body.appendChild(btn);

        function updateBtnPos() {
            var collapsed = document.documentElement.classList.contains('toc-collapsed') || tocDrawer.classList.contains('toc-collapsed');
            if (collapsed) {
                btn.style.right = '0px';
                btn.textContent = '\u276E';
            } else {
                var rect = tocDrawer.getBoundingClientRect();
                var offset = document.documentElement.clientWidth - rect.left;
                btn.style.right = Math.max(0, offset) + 'px';
                btn.textContent = '\u276F';
            }
        }

        window.addEventListener('resize', updateBtnPos);

        btn.addEventListener('click', function () {
            // Enable smooth animation only during this user click interaction
            document.body.classList.add('toc-animating');

            var currentlyCollapsed = document.documentElement.classList.contains('toc-collapsed') || tocDrawer.classList.contains('toc-collapsed');
            var nextCollapsed = !currentlyCollapsed;

            document.documentElement.classList.toggle('toc-collapsed', nextCollapsed);
            tocDrawer.classList.toggle('toc-collapsed', nextCollapsed);
            if (tocDrawer.parentElement) {
                tocDrawer.parentElement.classList.toggle('toc-collapsed', nextCollapsed);
            }
            localStorage.setItem('ragdoll-toc-collapsed', nextCollapsed ? 'true' : 'false');
            updateBtnPos();

            // Remove animation class after transition completes
            setTimeout(function () {
                document.body.classList.remove('toc-animating');
            }, 300);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
