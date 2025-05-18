// content/content.js
console.log("Megara Recorder: Content script injected.");

let isRecorderActive = false;
let highlightedElement = null;
let currentOverlayData = null; // Store data related to the active overlay

// --- Highlighting Functions (Keep as before) ---
function addHighlight(event) {
    if (!isRecorderActive || !event.target || event.target.id === '_megara-recorder-overlay' || event.target.closest('#_megara-recorder-overlay')) return; // Ignore overlay itself
    removeHighlight();
    event.target.classList.add('_megara-recorder-highlight');
    highlightedElement = event.target;
}
function removeHighlight() {
    if (highlightedElement) {
        highlightedElement.classList.remove('_megara-recorder-highlight');
        highlightedElement = null;
    }
}

// --- Overlay Management Functions ---

function getOverlayElement() {
    return document.getElementById('_megara-recorder-overlay');
}

function createOverlay() {
    if (getOverlayElement()) return getOverlayElement(); // Don't create if exists

    const overlay = document.createElement('div');
    overlay.id = '_megara-recorder-overlay';
    overlay.innerHTML = `
        <h4>Record Step</h4>
        <div class="_mr-element-info">
            Element: <code id="_mr-element-tag">N/A</code><br>
            Selector: <code id="_mr-element-selector">N/A</code>
        </div>
        <div>
            <label for="_mr-action-type">Action Type:</label>
            <select id="_mr-action-type">
                <!-- Options will be populated dynamically -->
            </select>
        </div>
        <div class="_mr-value-section" id="_mr-value-section">
             <label for="_mr-value-input" id="_mr-value-label">Value:</label>
             <textarea id="_mr-value-input" rows="2"></textarea>
        </div>
        <div class="_mr-button-group">
            <button class="_mr-cancel-button" id="_mr-cancel-button">Cancel</button>
            <button class="_mr-save-button" id="_mr-save-button">Save Step</button>
        </div>
    `;
    document.body.appendChild(overlay);

    // Populate Action Types
    const actionSelect = overlay.querySelector('#_mr-action-type');
    // Get ActionTypeEnum values (assuming they are accessible or hardcoded)
    // TODO: Get these dynamically or keep a hardcoded list matching the Enum
    const actionTypes = [
        'CLICK', 'TYPE', 'SELECT', 'EXTRACT_TABLE', 'EXTRACT_ELEMENT',
        'NAVIGATE', 'WAIT_FOR_SELECTOR', 'WAIT_FOR_TIMEOUT'
    ];
    actionTypes.forEach(action => {
        const option = document.createElement('option');
        option.value = action;
        option.textContent = action;
        actionSelect.appendChild(option);
    });

    // Add event listeners for the overlay's internal elements
    actionSelect.addEventListener('change', handleActionTypeChange);
    overlay.querySelector('#_mr-save-button').addEventListener('click', handleOverlaySave);
    overlay.querySelector('#_mr-cancel-button').addEventListener('click', hideOverlay);

    return overlay;
}

function handleActionTypeChange(event) {
    const selectedAction = event.target.value;
    const valueSection = document.getElementById('_mr-value-section');
    const valueLabel = document.getElementById('_mr-value-label');
    const valueInput = document.getElementById('_mr-value-input');

    // Show/hide value input based on action type and set appropriate label
    if (['TYPE', 'SELECT', 'NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(selectedAction)) {
        valueLabel.textContent = 'Value / URL / Option Value / Timeout (ms):';
        valueInput.placeholder = '';
        valueSection.style.display = 'block';
    } else if (['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction)) {
        valueLabel.textContent = 'Label for Extracted Data (Optional):';
        valueInput.placeholder = 'e.g., login_message, user_table';
        valueSection.style.display = 'block';
    } else if (selectedAction === 'WAIT_FOR_SELECTOR') {
         valueLabel.textContent = 'State[:Timeout] (e.g., visible:10000):';
         valueInput.placeholder = 'visible';
         valueSection.style.display = 'block';
    } else { // CLICK or others that don't need value
        valueLabel.textContent = 'Value:'; // Reset label
        valueSection.style.display = 'none';
    }
}


function showOverlay(targetElement, selector) {
    const overlay = createOverlay(); // Ensure overlay exists
    currentOverlayData = { targetElement, selector }; // Store context

    // Populate overlay with info
    overlay.querySelector('#_mr-element-tag').textContent = `<${targetElement.tagName.toLowerCase()}>`;
    overlay.querySelector('#_mr-element-selector').textContent = selector;
    overlay.querySelector('#_mr-action-type').value = 'CLICK'; // Default to CLICK
    overlay.querySelector('#_mr-value-input').value = ''; // Clear value field
    handleActionTypeChange({ target: overlay.querySelector('#_mr-action-type') }); // Update value visibility

    // Position overlay near the element (simple positioning for now)
    const rect = targetElement.getBoundingClientRect();
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

    overlay.style.left = `${Math.max(5, scrollLeft + rect.left)}px`; // Position near left edge, ensure on screen
    overlay.style.top = `${scrollTop + rect.bottom + 5}px`; // Position below element
    overlay.style.display = 'block';
}

function hideOverlay() {
    const overlay = getOverlayElement();
    if (overlay) {
        overlay.style.display = 'none';
    }
    currentOverlayData = null; // Clear context
}

function handleOverlaySave() {
    if (!currentOverlayData) return; // Should not happen

    const overlay = getOverlayElement();
    const actionType = overlay.querySelector('#_mr-action-type').value;
    const valueInput = overlay.querySelector('#_mr-value-input').value.trim();
    const selector = currentOverlayData.selector; // Get stored selector

    // Basic validation
    if (!actionType) {
        alert("Please select an Action Type.");
        return;
    }
     if (!selector && !['NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(actionType) ) {
         alert("Selector is missing (internal error). Cannot save.");
         return;
     }

    // Prepare step data (ensure value is null if empty string)
    const stepData = {
        action_type: actionType,
        selector: selector,
        value: valueInput || null // Send null if value is empty
    };

    // Send step data to background script
    console.log("Content Script: Sending step data to background:", stepData);
    chrome.runtime.sendMessage({ action: "saveStep", data: stepData }, (response) => {
        if (chrome.runtime.lastError) {
            console.error("Content Script: Error sending step:", chrome.runtime.lastError);
            alert("Error saving step: " + chrome.runtime.lastError.message);
        } else {
            console.log("Content Script: Background response:", response);
            if (!response?.success) {
                 alert("Error saving step: " + (response?.message || 'Unknown error'));
            } else {
                 // Optional: Show brief success confirmation on page?
                 console.log("Step saved successfully!");
            }
        }
         // Hide overlay regardless of save success/failure for now
         hideOverlay();
    });
}


// --- NEW: Robust Selector Generation Logic ---

/**
 * Checks if a generated CSS selector uniquely identifies one element on the page.
 * @param {string} selector The CSS selector string.
 * @returns {boolean} True if the selector identifies exactly one element, false otherwise.
 */
function isSelectorUnique(selector) {
    if (!selector) return false;
    try {
        return document.querySelectorAll(selector).length === 1;
    } catch (e) {
        console.warn(`[Selector Check] Invalid selector generated: ${selector}`, e);
        return false;
    }
}

/**
 * Filters class list to remove potentially unstable classes.
 * Add more patterns here based on observed frameworks/dynamic classes.
 * @param {DOMTokenList} classList The classList object from an element.
 * @returns {string[]} An array of potentially stable class names.
 */
function getStableClasses(classList) {
    const unstablePatterns = [
        /^(fa-|fas-|far-|fal-|fab-)/, // Font Awesome icons
        /^(?:col|row|container|grid)(?:-|$)/, // Common layout frameworks (Bootstrap, etc.)
        /^(?:d|m|p|mx|my|px|py|pt|pb|pl|pr|ms|me|mt|mb)-(?:[0-5]|auto|xs|sm|md|lg|xl|xxl)/, // Bootstrap spacing/display
        /^(active|focus|hover|disabled|selected|open|closed)/, // State classes
        /\d/, // Classes containing digits (often dynamic)
        /^[a-z]{1,2}$/ // Very short classes (often utility)
        // Add more framework-specific or observed dynamic patterns here
    ];
    const stableClasses = [];
    for (const className of classList) {
        if (className && !unstablePatterns.some(pattern => pattern.test(className))) {
            stableClasses.push(className);
        }
    }
    return stableClasses;
}


/**
 * Tries to generate a robust CSS selector for a given element.
 * @param {Element} element The target DOM element.
 * @param {number} [maxDepth=3] Maximum levels to traverse up for parent selectors.
 * @returns {string|null} A CSS selector string or null if no suitable selector found.
 */
function generateRobustSelector(element, maxDepth = 3) {
    if (!element || !(element instanceof Element) || maxDepth <= 0) {
        return null;
    }

    let selector = null;
    const tagName = element.tagName.toLowerCase();

    // 1. Try ID (Highest priority)
    if (element.id) {
        const idSelector = `#${CSS.escape(element.id)}`; // Use CSS.escape for special characters
        if (isSelectorUnique(idSelector)) {
            console.debug("[Selector Gen] Using unique ID:", idSelector);
            return idSelector;
        }
         // If ID is not unique (shouldn't happen often), prefix with tag
         selector = `${tagName}${idSelector}`;
         if (isSelectorUnique(selector)) {
             console.debug("[Selector Gen] Using non-unique ID with tag:", selector);
             return selector;
         }
    }

    // 2. Try common data-* test attributes
    const testAttrs = ['data-testid', 'data-cy', 'data-qa', 'data-test-id', 'data-test'];
    for (const attr of testAttrs) {
        if (element.hasAttribute(attr)) {
            const val = CSS.escape(element.getAttribute(attr));
            selector = `${tagName}[${attr}="${val}"]`; // Include tagName for specificity
            if (isSelectorUnique(selector)) {
                console.debug(`[Selector Gen] Using unique test attribute ${attr}:`, selector);
                return selector;
            }
        }
    }

    // 3. Try 'name' attribute (useful for forms)
    if (element.name) {
        selector = `${tagName}[name="${CSS.escape(element.name)}"]`;
        if (isSelectorUnique(selector)) {
            console.debug("[Selector Gen] Using unique name attribute:", selector);
            return selector;
        }
    }

    // 4. Try stable class names
    const stableClasses = getStableClasses(element.classList);
    if (stableClasses.length > 0) {
        selector = `${tagName}.${stableClasses.map(c => CSS.escape(c)).join('.')}`;
        if (isSelectorUnique(selector)) {
            console.debug("[Selector Gen] Using stable classes:", selector);
            return selector;
        }
    }

    // 5. Try Parent + Child combination (Recursive)
    const parent = element.parentElement;
    if (parent && parent.tagName.toLowerCase() !== 'body' && parent.tagName.toLowerCase() !== 'html') {
        const parentSelector = generateRobustSelector(parent, maxDepth - 1); // Recurse with decreased depth

        if (parentSelector) {
            // Try simple child descriptor: tag name
            selector = `${parentSelector} > ${tagName}`;
            if (isSelectorUnique(selector)) {
                 console.debug("[Selector Gen] Using parent + child tag:", selector);
                 return selector;
            }

            // Try child descriptor: tag name + stable classes (if any)
            if (stableClasses.length > 0) {
                 const classPart = `.${stableClasses.map(c => CSS.escape(c)).join('.')}`;
                 selector = `${parentSelector} > ${tagName}${classPart}`;
                 if (isSelectorUnique(selector)) {
                     console.debug("[Selector Gen] Using parent + child tag/class:", selector);
                     return selector;
                 }
            }

             // Fallback (more brittle): Use positional :nth-of-type
             let index = 1;
             let sibling = element.previousElementSibling;
             while (sibling) {
                 if (sibling.tagName === element.tagName) {
                     index++;
                 }
                 sibling = sibling.previousElementSibling;
             }
             const positionalSelector = `${tagName}:nth-of-type(${index})`;
             selector = `${parentSelector} > ${positionalSelector}`;
              if (isSelectorUnique(selector)) {
                 console.debug("[Selector Gen] Using parent + child position:", selector);
                 return selector;
             }
        }
    }

    // 6. Last Resort: Just the tag name (unlikely to be unique)
    console.warn(`[Selector Gen] Could not find unique selector for element. Falling back to tagName: ${tagName}`);
    return tagName; // Or return null if tagname isn't acceptable
}

// --- END Robust Selector Generation Logic ---


// --- UPDATED Click Handling ---
function handleClick(event) {
    // Ignore clicks if not recording or if click is on overlay itself
    if (!isRecorderActive || !event.target || event.target.id === '_megara-recorder-overlay' || event.target.closest('#_megara-recorder-overlay')) {
         return;
    }

    event.preventDefault();
    event.stopPropagation();

    const targetElement = event.target;
    removeHighlight(); // Remove highlight after click

    console.log("Recorder Clicked:", targetElement.tagName);

    // --- Use the new selector generator ---
    const selector = generateRobustSelector(targetElement);
    console.log("  Generated Selector (robust):", selector);
    // --- End selector generation ---

    if (!selector) {
        alert("Could not generate a reliable selector for the clicked element.");
        return; // Don't show overlay if no selector found
    }

    // Show the overlay, passing the generated selector
    showOverlay(targetElement, selector);
}


// --- Event Listeners Setup (Keep as before) ---
function addListeners() {
    console.log("Megara Recorder: Adding event listeners.");
    document.addEventListener('mouseover', addHighlight, true);
    document.addEventListener('mouseout', removeHighlight, true);
    document.addEventListener('click', handleClick, true); // Use capture phase
}

function removeListeners() {
    console.log("Megara Recorder: Removing event listeners.");
    removeHighlight();
    document.removeEventListener('mouseover', addHighlight, true);
    document.removeEventListener('mouseout', removeHighlight, true);
    document.removeEventListener('click', handleClick, true);
}

// --- Message Listener & Ready Signal (Keep as before) ---
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log("Content Script: Received message:", message);
    if (message.action === "activateRecording") {
        isRecorderActive = true;
        addListeners();
        console.log("Megara Recorder: Recording ACTIVATED");
        sendResponse({ status: "Recording activated" });
    } else if (message.action === "deactivateRecording") {
        isRecorderActive = false;
        removeListeners();
        hideOverlay(); // Hide overlay if recording stops
        console.log("Megara Recorder: Recording DEACTIVATED");
        sendResponse({ status: "Recording deactivated" });
    }
    return true;
});

console.log("Content Script: Sending ready message to background.");
chrome.runtime.sendMessage({ action: "contentScriptReady" }, (response) => {
     if (chrome.runtime.lastError) {
        console.warn("Content Script: Error sending ready message:", chrome.runtime.lastError.message);
    } else {
        console.log("Content Script: Background acknowledged ready message.");
    }
});