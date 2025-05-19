// content/content.js
console.log("CONTENT.JS: SCRIPT EXECUTION STARTED");

let isRecorderActive = false;
let highlightedElement = null;
let currentOverlayData = null; // Stores { targetElement, selector } for the active overlay
let currentTemplatePreviewData = []; // Stores template preview data [[row1_cell1, row1_cell2], [row2_cell1, ...]]

// --- Helper: Robust Selector Generation ---
/**
 * Checks if a generated CSS selector uniquely identifies one element on the page.
 * @param {string} selector The CSS selector string.
 * @returns {boolean} True if the selector identifies exactly one element, false otherwise.
 */
function isSelectorUnique(selector) {
    if (!selector) {
        console.debug("[isSelectorUnique] Received empty/null selector.");
        return false;
    }
    try {
        const elements = document.querySelectorAll(selector);
        const count = elements.length;
        console.debug(`[isSelectorUnique] Selector: '${selector}', Found elements: ${count}`);
        return count === 1;
    } catch (e) {
        // This can happen if the selector is invalid (e.g., malformed ID with special chars not escaped)
        console.warn(`[isSelectorUnique] Invalid or error during querySelectorAll for selector: '${selector}'`, e);
        return false;
    }
}

/**
 * Filters class list to remove potentially unstable classes.
 * @param {DOMTokenList} classList The classList object from an element.
 * @returns {string[]} An array of potentially stable class names.
 */
function getStableClasses(classList) {
    if (!classList || classList.length === 0) return [];

    const unstablePatterns = [
        /^(fa-|fas-|far-|fal-|fab-)/, // Font Awesome
        /^(?:col|row|container|grid|flex|d|m|p|mx|my|px|py|pt|pb|pl|pr|ms|me|mt|mb|g|gap)-(?:[0-9]+|auto|xs|sm|md|lg|xl|xxl|none|inline|block|flex|grid|table|contents|list-item|inline-block|inline-flex|inline-grid|inline-table)/, // Common layout/spacing (Bootstrap, Tailwind, etc.)
        /^(active|focus|hover|disabled|selected|open|closed|collapsed|expanded|current|loading|loaded|dragging|dragover|dropping|error|success|warning|info|modal|tooltip|popover|dropdown|nav|navbar|header|footer|sidebar|main|content|wrapper|container|page|section)/i, // Common state, role, or generic layout classes
        /\d/, // Classes containing digits (often dynamic, unless specific like 'w-50')
        /^[a-z]{1,2}$/, // Very short classes (often utility unless part of a known system like 'is', 'has')
        /^(is-|has-|js-|ui-)/, // Common JS hooks or UI framework prefixes
        // Add more framework-specific or observed dynamic patterns here based on Megara
        // For example, if Megara uses classes like 'generated-id-xzy', add /^generated-id-/
    ];
    const stableClasses = [];
    for (const className of classList) {
        if (className && !unstablePatterns.some(pattern => pattern.test(className))) {
            stableClasses.push(CSS.escape(className)); // Escape class names
        }
    }
    console.debug("[getStableClasses] Original:", Array.from(classList), "Filtered:", stableClasses);
    return stableClasses;
}


/**
 * Tries to generate a robust CSS selector for a given element.
 * @param {Element} element The target DOM element.
 * @param {number} [maxDepth=3] Maximum levels to traverse up for parent selectors.
 * @returns {string|null} A CSS selector string or null if no suitable selector found.
 */
function generateRobustSelector(element, maxDepth = 3) {
    if (!element || !(element instanceof Element) || element.tagName === 'HTML' || element.tagName === 'BODY' || maxDepth <= 0) {
        console.debug("[generateRobustSelector] Base case: Invalid element, body/html, or maxDepth reached.");
        return null;
    }

    let selector = null;
    const tagName = element.tagName.toLowerCase();
    console.debug(`[generateRobustSelector] Trying for: <${tagName}>, Depth: ${maxDepth}`, element);

    // 1. Try ID (Highest priority)
    if (element.id) {
        const idSelector = `#${CSS.escape(element.id)}`;
        console.debug("[generateRobustSelector] Trying ID:", idSelector);
        if (isSelectorUnique(idSelector)) {
            console.log("[generateRobustSelector] SUCCESS: Using unique ID:", idSelector);
            return idSelector;
        }
        // If ID isn't unique (bad practice), try with tag name for more specificity
        selector = `${tagName}${idSelector}`;
        console.debug("[generateRobustSelector] Trying Tagged ID:", selector);
        if (isSelectorUnique(selector)) {
            console.log("[generateRobustSelector] SUCCESS: Using non-unique ID with tag:", selector);
            return selector;
        }
    }

    // 2. Try common data-* test attributes
    const testAttrs = ['data-testid', 'data-cy', 'data-qa', 'data-test-id', 'data-test', 'data-component'];
    for (const attr of testAttrs) {
        if (element.hasAttribute(attr)) {
            const val = CSS.escape(element.getAttribute(attr));
            selector = `${tagName}[${attr}="${val}"]`;
            console.debug(`[generateRobustSelector] Trying Test Attribute ${attr}:`, selector);
            if (isSelectorUnique(selector)) {
                console.log(`[generateRobustSelector] SUCCESS: Using unique test attribute ${attr}:`, selector);
                return selector;
            }
        }
    }

    // 3. Try 'name' attribute (useful for forms)
    if (element.name) {
        selector = `${tagName}[name="${CSS.escape(element.name)}"]`;
        console.debug("[generateRobustSelector] Trying Name attribute:", selector);
        if (isSelectorUnique(selector)) {
            console.log("[generateRobustSelector] SUCCESS: Using unique name attribute:", selector);
            return selector;
        }
    }

    // 4. Try stable class names
    const stableClasses = getStableClasses(element.classList);
    if (stableClasses.length > 0) {
        selector = `${tagName}.${stableClasses.join('.')}`;
        console.debug("[generateRobustSelector] Trying stable classes:", selector);
        if (isSelectorUnique(selector)) {
            console.log("[generateRobustSelector] SUCCESS: Using stable classes:", selector);
            return selector;
        }
    }

    // 5. Try Parent + Child combination (Recursive)
    const parent = element.parentElement;
    if (parent) { // Ensure parent exists
        console.debug("[generateRobustSelector] Trying parent strategy for element:", element);
        const parentSelector = generateRobustSelector(parent, maxDepth - 1); // Recurse

        if (parentSelector) {
            console.debug("[generateRobustSelector] Parent selector found:", parentSelector);
            // Strategy 5a: Parent + direct child tagName
            selector = `${parentSelector} > ${tagName}`;
            console.debug("[generateRobustSelector] Trying Parent + child tag:", selector);
            if (isSelectorUnique(selector)) {
                console.log("[generateRobustSelector] SUCCESS: Using parent + child tag:", selector);
                return selector;
            }

            // Strategy 5b: Parent + direct child tagName + stable classes
            if (stableClasses.length > 0) {
                 const classPart = `.${stableClasses.join('.')}`;
                 selector = `${parentSelector} > ${tagName}${classPart}`;
                 console.debug("[generateRobustSelector] Trying Parent + child tag/class:", selector);
                 if (isSelectorUnique(selector)) {
                     console.log("[generateRobustSelector] SUCCESS: Using parent + child tag/class:", selector);
                     return selector;
                 }
            }

            // Strategy 5c: Parent + direct child :nth-of-type (more robust than nth-child)
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
             console.debug("[generateRobustSelector] Trying Parent + child position (:nth-of-type):", selector);
              if (isSelectorUnique(selector)) {
                 console.log("[generateRobustSelector] SUCCESS: Using parent + child position:", selector);
                 return selector;
             }
        } else {
             console.debug("[generateRobustSelector] No robust selector found for parent.");
        }
    }

    // 6. Last Resort: If all else fails, and if only tagName is too generic, maybe just return null.
    // For now, let's try returning just the tag name if it's SOMEWHAT unique (e.g. < 5 matches)
    // This is a very loose fallback.
    if (document.querySelectorAll(tagName).length < 5 && document.querySelectorAll(tagName).length > 0) {
        console.warn(`[generateRobustSelector] Could not find unique selector. Falling back to less reliable tagName: ${tagName}`);
        return tagName;
    }

    console.error("[generateRobustSelector] All strategies failed to produce a sufficiently unique selector. Returning null.", element);
    return null; // Explicitly return null if no reliable selector found
}
// --- END Robust Selector Generation Logic ---


// --- Overlay Management Functions ---
function getOverlayElement() {
    return document.getElementById('_megara-recorder-overlay');
}

function createOverlay() {
    let overlay = getOverlayElement();
    if (overlay) return overlay; // Don't create if exists

    overlay = document.createElement('div');
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
        <div class="_mr-value-section" id="_mr-value-section" style="display: none;">
             <label for="_mr-value-input" id="_mr-value-label">Value:</label>
             <textarea id="_mr-value-input" rows="2"></textarea>
        </div>
        <div class="_mr-mapping-section" id="_mr-mapping-section" style="display: none;">
            <label>Map Extracted Data to Template Cell (Click a cell below):</label>
            <div id="_mr-template-preview-grid-container">
                <table id="_mr-template-preview-grid">
                    
                </table>
                <span class="text-muted _mr-no-preview" style="display:none;">No template preview available or data is empty.</span>
            </div>
            <input type="hidden" id="_mr-selected-template-cell" />
        </div>
        <div class="_mr-error-message" id="_mr-error-message" style="display: none;"></div>
        <div class="_mr-button-group">
            <button class="_mr-cancel-button" id="_mr-cancel-button">Cancel</button>
            <button class="_mr-save-button" id="_mr-save-button">Save Step</button>
        </div>
    `;
    document.body.appendChild(overlay);

    // Populate Action Types
    const actionSelect = overlay.querySelector('#_mr-action-type');
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

// --- NEW: Function to render the template preview grid ---
function renderTemplatePreviewGrid(previewData) {
    const gridTable = document.getElementById('_mr-template-preview-grid');
    const noPreviewMessage = document.querySelector('#_mr-template-preview-grid-container ._mr-no-preview');
    const selectedCellInput = document.getElementById('_mr-selected-template-cell');

    gridTable.innerHTML = ''; // Clear previous grid
    if(selectedCellInput) selectedCellInput.value = ''; // Clear previous selection

    if (previewData && previewData.length > 0) {
        if (noPreviewMessage) noPreviewMessage.style.display = 'none';

        previewData.forEach((rowData, rowIndex) => {
            const tr = document.createElement('tr');
            rowData.forEach((cellData, colIndex) => {
                const cellElement = (rowIndex === 0) ? document.createElement('th') : document.createElement('td');
                cellElement.textContent = cellData || ""; // Ensure textContent is not null
                const colLetter = String.fromCharCode(65 + colIndex); // 65 is 'A'
                const cellRef = `${colLetter}${rowIndex + 1}`;
                cellElement.dataset.cellRef = cellRef;

                cellElement.addEventListener('click', function(e) {
                    const currentlySelected = gridTable.querySelector('._mr-cell-selected');
                    if (currentlySelected) {
                        currentlySelected.classList.remove('_mr-cell-selected');
                    }
                    this.classList.add('_mr-cell-selected');
                    if(selectedCellInput) selectedCellInput.value = this.dataset.cellRef;
                    console.log("Content.JS: Template cell selected:", this.dataset.cellRef);
                });
                tr.appendChild(cellElement);
            });
            gridTable.appendChild(tr);
        });
    } else {
        if (noPreviewMessage) noPreviewMessage.style.display = 'inline';
        console.log("Content.JS: No preview data to render or preview data is empty.");
    }
}


function handleActionTypeChange(event) {
    const selectedAction = event.target.value;
    const valueSection = document.getElementById('_mr-value-section');
    const valueLabel = document.getElementById('_mr-value-label');
    const valueInput = document.getElementById('_mr-value-input');
    const mappingSection = document.getElementById('_mr-mapping-section');

    // Reset value input
    valueInput.value = '';

    // Logic for Value Section
    if (['TYPE', 'SELECT', 'NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(selectedAction)) {
        valueLabel.textContent = 'Value / URL / Option Value / Timeout (ms):';
        valueInput.placeholder = selectedAction === 'TYPE' ? 'Enter text...' : (selectedAction === 'NAVIGATE' ? 'http://...' : (selectedAction === 'SELECT' ? 'Option Value' : '1000'));
        valueSection.style.display = 'block';
    } else if (['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction)) {
        valueLabel.textContent = 'Label for Extracted Data (Optional):';
        valueInput.placeholder = 'e.g., login_message, user_table';
        valueSection.style.display = 'block';
    } else if (selectedAction === 'WAIT_FOR_SELECTOR') {
         valueLabel.textContent = 'State[:Timeout] (e.g., visible:10000):';
         valueInput.placeholder = 'visible';
         valueSection.style.display = 'block';
    } else { // CLICK or others
        valueSection.style.display = 'none';
    }

    // Logic for Mapping Section
    if (['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction) && currentTemplatePreviewData.length > 0) {
        mappingSection.style.display = 'block';
    } else {
        mappingSection.style.display = 'none';
    }
}


function showOverlay(targetElement, selector) {
    const overlay = createOverlay(); // Ensure overlay is created and elements exist
    currentOverlayData = { targetElement, selector };
    const errorDiv = overlay.querySelector('#_mr-error-message');
    const actionSelect = overlay.querySelector('#_mr-action-type');
    const valueInput = overlay.querySelector('#_mr-value-input');
    const selectedCellInput = document.getElementById('_mr-selected-template-cell');

    // Clear previous state
    if (errorDiv) { errorDiv.textContent = ''; errorDiv.style.display = 'none'; }
    if (valueInput) valueInput.value = '';
    if (selectedCellInput) selectedCellInput.value = ''; // Clear cell selection


    // Populate element info
    overlay.querySelector('#_mr-element-tag').textContent = `<${targetElement.tagName.toLowerCase()}>`;
    overlay.querySelector('#_mr-element-selector').textContent = selector;

    // Auto-Suggest Action Type
    let suggestedAction = 'CLICK';
    const tagName = targetElement.tagName.toLowerCase();
    const inputType = targetElement.type?.toLowerCase();
    if (tagName === 'a') suggestedAction = 'NAVIGATE';
    else if (tagName === 'button' || ['submit', 'button', 'reset'].includes(inputType)) suggestedAction = 'CLICK';
    else if ((tagName === 'input' && ['text', 'password', 'email', 'search', 'tel', 'url', 'number'].includes(inputType)) || tagName === 'textarea') suggestedAction = 'TYPE';
    else if (tagName === 'select') suggestedAction = 'SELECT';
    else if (tagName === 'table') suggestedAction = 'EXTRACT_TABLE';

    actionSelect.value = suggestedAction;

    // Render template preview grid (using stored data)
    renderTemplatePreviewGrid(currentTemplatePreviewData);

    // Trigger change to update UI sections based on suggested action
    handleActionTypeChange({ target: actionSelect });

    // Position and display overlay
    const rect = targetElement.getBoundingClientRect();
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
    overlay.style.left = `${Math.max(5, scrollLeft + rect.left)}px`;
    overlay.style.top = `${scrollTop + rect.bottom + 5}px`;
    overlay.style.display = 'block';
}

function hideOverlay() {
    const overlay = getOverlayElement();
    if (overlay) {
        overlay.style.display = 'none';
    }
    currentOverlayData = null;
}

function handleOverlaySave() {
    if (!currentOverlayData) return;

    const overlay = getOverlayElement();
    const actionType = overlay.querySelector('#_mr-action-type').value;
    const valueInput = overlay.querySelector('#_mr-value-input').value.trim();
    const selector = currentOverlayData.selector;
    const errorDiv = overlay.querySelector('#_mr-error-message');
    const mappingTargetCell = document.getElementById('_mr-selected-template-cell').value || null;


    errorDiv.textContent = ''; errorDiv.style.display = 'none'; // Clear previous errors

    if (!actionType) { errorDiv.textContent = "Please select an Action Type."; errorDiv.style.display = 'block'; return; }
    if (!selector && !['NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(actionType) ) {
         errorDiv.textContent = "Selector is missing or invalid."; errorDiv.style.display = 'block'; return;
     }

    const stepData = {
        action_type: actionType,
        selector: selector,
        value: valueInput || null,
        mapping_target_cell: mappingTargetCell // Send cell reference
    };

    console.log("Content Script: Sending step data to background:", stepData);
    overlay.querySelector('#_mr-save-button').disabled = true;
    overlay.querySelector('#_mr-cancel-button').disabled = true;

    chrome.runtime.sendMessage({ action: "saveStep", data: stepData }, (response) => {
         overlay.querySelector('#_mr-save-button').disabled = false;
         overlay.querySelector('#_mr-cancel-button').disabled = false;

        if (chrome.runtime.lastError || !response) {
            console.error("CS: Error sending/receiving saveStep:", chrome.runtime.lastError?.message || "No response");
            errorDiv.textContent = `Error: ${chrome.runtime.lastError?.message || 'Communication error with background.'}`;
            errorDiv.style.display = 'block';
        } else {
            console.log("CS: Background response for saveStep:", response);
            if (!response.success) {
                 errorDiv.textContent = `Error saving: ${response.message || 'Unknown API error'}`;
                 errorDiv.style.display = 'block';
            } else {
                 console.log("Step saved successfully!");
                 hideOverlay();
            }
        }
    });
}

// --- Highlighting Functions ---
function addHighlight(event) {
    if (!isRecorderActive || !event.target || event.target.id === '_megara-recorder-overlay' || event.target.closest('#_megara-recorder-overlay')) return;
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

// --- Click Handling ---
function handleClick(event) {
    if (!isRecorderActive || !event.target || event.target.id === '_megara-recorder-overlay' || event.target.closest('#_megara-recorder-overlay')) {
         return;
    }
    event.preventDefault(); event.stopPropagation();
    const targetElement = event.target;
    removeHighlight(); // Remove highlight from element just clicked
    console.log("Recorder Clicked:", targetElement.tagName);
    const selector = generateRobustSelector(targetElement);
    console.log("  Generated Selector (robust):", selector);
    if (!selector) { alert("Could not generate a reliable selector."); return; }
    showOverlay(targetElement, selector);
}

// --- Event Listeners Setup ---
function addListeners() {
    console.log("CONTENT.JS: Adding event listeners (mouseover, mouseout, click).");
    document.addEventListener('mouseover', addHighlight, true);
    document.addEventListener('mouseout', removeHighlight, true);
    document.addEventListener('click', handleClick, true);
}

function removeListeners() {
    console.log("CONTENT.JS: Removing event listeners.");
    removeHighlight();
    document.removeEventListener('mouseover', addHighlight, true);
    document.removeEventListener('mouseout', removeHighlight, true);
    document.removeEventListener('click', handleClick, true);
}

// --- Message Listener & Ready Signal ---
if (chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        console.log("CONTENT.JS: MESSAGE LISTENER - Received message:", message);
        if (message.action === "activateRecording") {
            if (isRecorderActive) { sendResponse({ status: "Already active" }); return true; }
            isRecorderActive = true; addListeners();
            console.log("CONTENT.JS: Recording ACTIVATED.");
            sendResponse({ status: "Recording activated in content script" });
        } else if (message.action === "deactivateRecording") {
            if (!isRecorderActive) { sendResponse({ status: "Already inactive" }); return true; }
            isRecorderActive = false; removeListeners(); hideOverlay();
            console.log("CONTENT.JS: Recording DEACTIVATED.");
            sendResponse({ status: "Recording deactivated in content script" });
        } else if (message.action === "setTemplatePreview") { // Handle new message
            console.log("CONTENT.JS: Received template PREVIEW data:", message.previewData);
            currentTemplatePreviewData = message.previewData || [];
            // If overlay is already visible, re-render its grid
            const overlay = getOverlayElement();
            if (overlay && overlay.style.display === 'block') {
                renderTemplatePreviewGrid(currentTemplatePreviewData);
                 const actionSelect = overlay.querySelector('#_mr-action-type');
                 if (actionSelect) handleActionTypeChange({target: actionSelect}); // Update visibility based on new headers
            }
            sendResponse({status: "Template preview received by content script"});
        } else {
            console.log("CONTENT.JS: Received unhandled message action:", message.action);
        }
        return true; // Keep channel open for async sendResponse
    });
    console.log("CONTENT.JS: chrome.runtime.onMessage.addListener has been SET UP.");
} else {
    console.error("CONTENT.JS: chrome.runtime.onMessage is NOT available.");
}

if (chrome.runtime && chrome.runtime.sendMessage) {
    console.log("CONTENT.JS: Sending 'contentScriptReady' message to background.");
    chrome.runtime.sendMessage({ action: "contentScriptReady" }, (response) => {
         if (chrome.runtime.lastError) { console.warn("CONTENT.JS: Error sending ready message:", chrome.runtime.lastError.message); }
         else { console.log("CONTENT.JS: Background acknowledged ready message:", response); }
    });
} else {
     console.error("CONTENT.JS: chrome.runtime.sendMessage is NOT available for ready signal.");
}

console.log("CONTENT.JS: SCRIPT EXECUTION FINISHED.");