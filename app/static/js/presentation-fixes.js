"use strict";

/*
 * Presentation-only realization formatting.
 *
 * Business values stay untouched. The UI displays realization percentages as
 * whole numbers using the accepted rule:
 *   xx.51 and above -> next integer
 *   xx.50 and below -> current integer
 *
 * The full supplied fraction is preserved: any value strictly above .50000
 * rounds upward, while an exact .50000 tie stays at the lower integer.
 */
(function () {
    const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA"]);
    const NUMBER_PATTERN = "-?\\d+(?:[.,]\\d+)?(?:[eE][+-]?\\d+)?";
    const PREFIX_PERCENT_RE = new RegExp(`%\\s*(${NUMBER_PATTERN})`, "g");
    const SUFFIX_PERCENT_RE = new RegExp(`(${NUMBER_PATTERN})\\s*%`, "g");

    function roundRealizationForDisplay(value) {
        const numeric = Number(String(value ?? 0).replace(",", "."));
        if (!Number.isFinite(numeric)) {
            return 0;
        }

        const sign = numeric < 0 ? -1 : 1;
        const absolute = Math.abs(numeric);
        const whole = Math.floor(absolute);
        const fraction = absolute - whole;
        const displayed = whole + (fraction > 0.5 ? 1 : 0);
        return sign * displayed;
    }

    function formatRealizationPercent(value) {
        return `${roundRealizationForDisplay(value)}%`;
    }

    function normalizePercentageText(text) {
        if (!text || text.indexOf("%") === -1) {
            return text;
        }

        let next = text.replace(PREFIX_PERCENT_RE, function (_match, value) {
            return `%${roundRealizationForDisplay(value)}`;
        });
        next = next.replace(SUFFIX_PERCENT_RE, function (_match, value) {
            return `${roundRealizationForDisplay(value)}%`;
        });
        return next;
    }

    function shouldSkipTextNode(node) {
        const parent = node && node.parentElement;
        if (!parent || SKIP_TAGS.has(parent.tagName)) {
            return true;
        }
        return Boolean(parent.closest("[contenteditable='true']"));
    }

    function normalizeTextNode(node) {
        if (!node || node.nodeType !== Node.TEXT_NODE || shouldSkipTextNode(node)) {
            return;
        }
        const normalized = normalizePercentageText(node.nodeValue);
        if (normalized !== node.nodeValue) {
            node.nodeValue = normalized;
        }
    }

    function normalizeTree(root) {
        if (!root) {
            return;
        }
        if (root.nodeType === Node.TEXT_NODE) {
            normalizeTextNode(root);
            return;
        }
        if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) {
            return;
        }

        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node) {
            normalizeTextNode(node);
            node = walker.nextNode();
        }
    }

    function installDynamicFormatter() {
        if (!document.body || typeof MutationObserver === "undefined") {
            return;
        }

        const observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === "characterData") {
                    normalizeTextNode(mutation.target);
                    return;
                }
                mutation.addedNodes.forEach(normalizeTree);
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    function initializePresentationFixes() {
        normalizeTree(document.body);
        installDynamicFormatter();

        /* Keep existing callers compatible without changing their calculations. */
        window.formatPercent = formatRealizationPercent;
        window.formatRealizationPercent = formatRealizationPercent;
        window.roundRealizationForDisplay = roundRealizationForDisplay;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializePresentationFixes, { once: true });
    } else {
        initializePresentationFixes();
    }
})();
