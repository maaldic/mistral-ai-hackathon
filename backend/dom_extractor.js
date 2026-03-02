(() => {
    // Clean up any previously assigned agent IDs to prevent duplicate IDs on re-evaluation
    document.querySelectorAll('[data-agent-id]').forEach(el => el.removeAttribute('data-agent-id'));

    let agentId = 0;
    const interactiveElements = [];

    const INTERACTIVE_SELECTORS = 'a[href], button, input, select, textarea, video, audio, [role="button"], [role="link"], [role="textbox"], [role="searchbox"], [role="combobox"], [role="menuitem"], [role="tab"], [onclick], [tabindex]:not([tabindex="-1"])';
    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'META', 'LINK', 'BR', 'HR']);

    const vpW = window.innerWidth;
    const vpH = window.innerHeight;
    // Generous margin so elements just outside viewport are still captured
    const MARGIN = 100;

    function isInViewport(el) {
        const rect = el.getBoundingClientRect();
        // Element has no layout (zero-size)
        if (rect.width === 0 && rect.height === 0) return false;
        // Check overlap with viewport + margin
        return rect.bottom > -MARGIN && rect.top < vpH + MARGIN
            && rect.right > -MARGIN && rect.left < vpW + MARGIN;
    }

    function isFixedOrSticky(el) {
        const style = window.getComputedStyle(el);
        return style.position === 'fixed' || style.position === 'sticky';
    }

    function isVisible(el) {
        if (el.offsetParent === null && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
            if (!isFixedOrSticky(el)) return false;
        }
        const style = window.getComputedStyle(el);
        // Allow opacity:0 elements through if they have aria-label — these are
        // hover-reveal controls (e.g. YouTube player Play/Mute/Seek buttons)
        // that become visible on hover. Playwright's click naturally hovers
        // over the element first, revealing it just-in-time.
        const opacityOk = style.opacity !== '0' || el.hasAttribute('aria-label');
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && opacityOk
            && el.getAttribute('aria-hidden') !== 'true';
    }

    function getLabel(el) {
        let text = (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || el.getAttribute('alt')) || '';

        if (!text.trim()) {
            text = el.innerText || '';
        }

        // Try getting text from images or other labeled children inside the element
        if (!text.trim() && el.querySelector) {
            const childWithLabel = el.querySelector('img[alt], [aria-label], [title]');
            if (childWithLabel) {
                text = (childWithLabel.getAttribute('alt') || childWithLabel.getAttribute('aria-label') || childWithLabel.getAttribute('title')) || '';
            }
        }

        if (!text.trim()) {
            text = el.textContent || '';
        }

        if (!text.trim()) {
            text = (el.getAttribute('name') || el.getAttribute('value')) || '';
        }

        return text ? text.replace(/\s+/g, ' ').trim().slice(0, 80) : '';
    }

    function getType(el) {
        const tag = el.tagName.toLowerCase();
        if (tag === 'input') return `${el.type || 'text'} input`;
        if (tag === 'a') return 'link';
        if (tag === 'button' || el.getAttribute('role') === 'button') return 'button';
        if (tag === 'select') return 'dropdown';
        if (tag === 'textarea') return 'text area';
        if (tag === 'video') return 'video player';
        if (tag === 'audio') return 'audio player';
        return tag;
    }

    function getExtra(el) {
        const parts = [];
        const tag = el.tagName.toLowerCase();

        // Links: omitted href extraction to save prompt tokens
        // if (tag === 'a' && el.href) { ... }

        // Inputs: show current value
        if (tag === 'input' || tag === 'textarea') {
            if (el.value) {
                parts.push(`value="${el.value.slice(0, 60)}"`);
            }
            if (el.type === 'checkbox' || el.type === 'radio') {
                parts.push(el.checked ? 'checked' : 'unchecked');
            }
        }

        // Select: show selected option
        if (tag === 'select' && el.selectedIndex >= 0) {
            const opt = el.options[el.selectedIndex];
            if (opt) {
                parts.push(`selected="${opt.text.slice(0, 60)}"`);
            }
        }

        // Disabled state
        if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
            parts.push('disabled');
        }

        return parts.length ? ' ' + parts.join(' ') : '';
    }

    // Tags that are always "leaf" interactive elements — never walk inside them
    const LEAF_INTERACTIVE = new Set([
        'INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A', 'VIDEO', 'AUDIO',
    ]);

    // Selectors for "real" form controls that should be discovered individually
    const DEEP_INTERACTIVE = 'input, select, textarea, button, a[href], [role="textbox"], [role="searchbox"], [role="combobox"], [role="option"], [role="listbox"]';

    function walk(node) {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        if (SKIP_TAGS.has(node.tagName)) return;
        if (!isVisible(node)) return;

        // Mark interactive elements
        if (node.matches && node.matches(INTERACTIVE_SELECTORS)) {
            // Container check: if this is NOT a leaf interactive tag AND it
            // contains deeper interactive children, treat it as a transparent
            // container — skip marking it and walk into children instead.
            if (!LEAF_INTERACTIVE.has(node.tagName) && node.querySelector(DEEP_INTERACTIVE)) {
                // Don't mark this container, keep walking children
                for (const child of node.childNodes) walk(child);
                if (node.shadowRoot) {
                    for (const child of node.shadowRoot.childNodes) walk(child);
                }
                return;
            }

            agentId++;
            node.setAttribute('data-agent-id', String(agentId));

            // Only report elements in/near the viewport (or fixed/sticky)
            if (isInViewport(node) || isFixedOrSticky(node)) {
                const label = getLabel(node);
                const type = getType(node);
                const extra = getExtra(node);
                if (label) {
                    interactiveElements.push(`[${agentId}] "${label}" (${type})${extra}`);
                } else {
                    interactiveElements.push(`[${agentId}] (${type})${extra}`);
                }
            }
            // Check shadow root inside interactive elements for sub-components
            if (node.shadowRoot) {
                for (const child of node.shadowRoot.childNodes) walk(child);
            }
            return;
        }

        for (const child of node.childNodes) walk(child);
        // Traverse into open shadow DOM
        if (node.shadowRoot) {
            for (const child of node.shadowRoot.childNodes) walk(child);
        }
    }

    walk(document.body);

    // --- Iframe Detection ---
    let iframeId = 0;
    const iframeLines = [];
    const iframeSelectors = {};
    document.querySelectorAll('iframe').forEach(iframe => {
        // Skip tiny/hidden iframes (tracking pixels, ads, etc.)
        const rect = iframe.getBoundingClientRect();
        if (rect.width < 50 || rect.height < 50) return;
        if (!isVisible(iframe)) return;

        iframeId++;
        iframe.setAttribute('data-agent-iframe-id', String(iframeId));
        const src = iframe.src || '';
        const title = iframe.title || iframe.name || '';
        const srcDisplay = src.length > 80 ? src.slice(0, 77) + '...' : src;
        iframeLines.push(`[iframe-${iframeId}] "${title || 'Untitled'}" src=${srcDisplay} (${Math.round(rect.width)}x${Math.round(rect.height)})`);
        iframeSelectors[String(iframeId)] = `iframe[data-agent-iframe-id="${iframeId}"]`;
    });

    // Build a map of agentId -> full element description for action history
    const elementLabels = {};
    for (const line of interactiveElements) {
        const match = line.match(/^\[(\d+)\]/);
        if (match) {
            elementLabels[match[1]] = line;
        }
    }

    return {
        url: window.location.href,
        title: document.title,
        interactive: interactiveElements.join('\n'),
        iframes: iframeLines.join('\n'),
        elementLabels: elementLabels,
        iframeSelectors: iframeSelectors,
    };
})()
