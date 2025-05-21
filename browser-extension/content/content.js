// content/content.js
console.log("CONTENT.JS: SCRIPT EXECUTION STARTED");

let isRecorderActive = false;
let highlightedElement = null;
let currentOverlayData = null; // Stores { targetElement, selector } for the active overlay
let currentTemplateInfo = {
    previewData: [],
    sheetName: null,
    allSheetNames: [],
    actualRowsInSheet: 0,
    actualColsInSheet: 0,
    message: null,
    error: null
};

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
function getOverlayElement() { return document.getElementById('_megara-recorder-overlay'); }

function createOverlay() {
    let overlay = getOverlayElement();
    if (overlay) return overlay;

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
                ${['CLICK','TYPE','SELECT','EXTRACT_TABLE','EXTRACT_ELEMENT','NAVIGATE','WAIT_FOR_SELECTOR','WAIT_FOR_TIMEOUT']
                  .map(act => `<option value="${act}">${act}</option>`).join('')}
            </select>
        </div>
        <div class="_mr-value-section" id="_mr-value-section" style="display: none;">
             <label for="_mr-value-input" id="_mr-value-label">Value:</label>
             <textarea id="_mr-value-input" rows="2"></textarea>
        </div>

        <div class="_mr-mapping-section" id="_mr-mapping-section" style="display: none;">
            <label>Map Extracted Data to Template Cell (Click a cell below):</label>
            <!-- Optional: Sheet Selector (for future enhancement) -->
            <div class="_mr-sheet-selector-container" style="margin-bottom: 5px; display: none;">
                 <label for="_mr-template-sheet-select" style="font-size:0.9em; margin-right:5px;">Sheet:</label>
                 <select id="_mr-template-sheet-select" style="padding:3px; font-size:0.9em;"></select>
            </div>
            <div id="_mr-template-preview-grid-container">
                <table id="_mr-template-preview-grid"></table>
                <div class="_mr-template-info-footer" style="font-size:0.8em; color:#555; margin-top:5px;"></div>
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

    // Add event listeners
    overlay.querySelector('#_mr-action-type').addEventListener('change', handleActionTypeChange);
    overlay.querySelector('#_mr-save-button').addEventListener('click', handleOverlaySave);
    overlay.querySelector('#_mr-cancel-button').addEventListener('click', hideOverlay);
    // Add listener for sheet selector later if implemented
    // overlay.querySelector('#_mr-template-sheet-select').addEventListener('change', handleSheetSelectionChange);

    return overlay;
}
// --- NEW: Function to render the template preview grid ---
// --- REVISED: Function to render the template preview grid ---
function renderTemplatePreviewGrid(templateInfo) {

    console.log("CONTENT.JS: renderTemplatePreviewGrid - Rendering with templateInfo:", JSON.parse(JSON.stringify(templateInfo)));

    const gridTable = document.getElementById('_mr-template-preview-grid');
    const infoFooter = document.querySelector('#_mr-template-preview-grid-container ._mr-template-info-footer');
    const selectedCellInput = document.getElementById('_mr-selected-template-cell');
    const sheetSelectorContainer = document.querySelector('._mr-sheet-selector-container');
    const sheetSelect = document.getElementById('_mr-template-sheet-select');

    // Clear previous grid and values
    gridTable.innerHTML = '';
    if (selectedCellInput) selectedCellInput.value = '';
    if (infoFooter) infoFooter.textContent = '';

    const previewData = templateInfo?.previewData;

    // Handle sheet selector visibility and population
    if (sheetSelectorContainer && sheetSelect && templateInfo?.allSheetNames && templateInfo.allSheetNames.length > 1) {
        sheetSelect.innerHTML = '';
        templateInfo.allSheetNames.forEach(name => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            if (name === templateInfo.sheetName) option.selected = true;
            sheetSelect.appendChild(option);
        });
        sheetSelectorContainer.style.display = 'block';
    } else if (sheetSelectorContainer) {
        sheetSelectorContainer.style.display = 'none';
    }

    // Render table if preview data is available
    if (previewData && previewData.length > 0) {
        // Create and append thead with column letters
        const anThRow = document.createElement('tr');
        const emptyHeaderCell = document.createElement('th');
        emptyHeaderCell.style.minWidth = '35px';
        anThRow.appendChild(emptyHeaderCell);

        if (previewData[0]) {
            previewData[0].forEach((_, colIndex) => {
                const colLetter = String.fromCharCode(65 + colIndex);
                const th = document.createElement('th');
                th.textContent = colLetter;
                th.style.textAlign = 'center';
                anThRow.appendChild(th);
            });
        }

        const thead = document.createElement('thead');
        thead.appendChild(anThRow);
        gridTable.appendChild(thead);

        // Create and append tbody with cell data
        const tbody = document.createElement('tbody');
        previewData.forEach((rowData, rowIndex) => {
            const tr = document.createElement('tr');

            const rowNumCell = document.createElement('th');
            rowNumCell.textContent = rowIndex + 1;
            rowNumCell.style.textAlign = 'center';
            rowNumCell.style.backgroundColor = '#f0f0f0';
            tr.appendChild(rowNumCell);

            rowData.forEach((cellData, colIndex) => {
                const td = document.createElement('td');
                td.textContent = cellData || '';
                const colLetter = String.fromCharCode(65 + colIndex);
                const cellRef = `${colLetter}${rowIndex + 1}`;
                td.dataset.cellRef = cellRef;
                td.title = `Cell: ${cellRef}\nValue: ${cellData || ""}`;

                td.addEventListener('click', function () {
                    const currentSelected = gridTable.querySelector('._mr-cell-selected');
                    if (currentSelected) currentSelected.classList.remove('_mr-cell-selected');
                    this.classList.add('_mr-cell-selected');
                    if (selectedCellInput) selectedCellInput.value = this.dataset.cellRef;
                    console.log("Content.JS: Template cell selected:", this.dataset.cellRef);
                });

                tr.appendChild(td);
            });

            tbody.appendChild(tr);
        });

        gridTable.appendChild(tbody);

        // Add footer info
        if (infoFooter) {
            infoFooter.textContent = `Sheet: '${templateInfo.sheetName}'. Displaying ${previewData.length} of ${templateInfo.actualRowsInSheet} rows, ${previewData[0] ? previewData[0].length : 0} of ${templateInfo.actualColsInSheet} columns.`;
        }
    } else {
        if (infoFooter) infoFooter.textContent = templateInfo?.message || "No template preview available or sheet is empty.";
        console.log("Content.JS: No preview data to render.");
    }
}



function handleActionTypeChange(event) {
    const selectedAction = event.target.value;
    const valueSection = document.getElementById('_mr-value-section');
    const valueLabel = document.getElementById('_mr-value-label');
    const valueInput = document.getElementById('_mr-value-input');
    const mappingSection = document.getElementById('_mr-mapping-section');

    // Reset value input
    if (valueInput) valueInput.value = '';

    // Logic for Value Section
    if (['TYPE', 'SELECT', 'NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(selectedAction)) {
        if (valueLabel) {
            valueLabel.textContent = 'Value / URL / Option Value / Timeout (ms):';
        }
        if (valueInput) {
            valueInput.placeholder = 
                selectedAction === 'TYPE' ? 'Enter text...' :
                selectedAction === 'NAVIGATE' ? 'http://...' :
                selectedAction === 'SELECT' ? 'Option Value' :
                '1000';
        }
        if (valueSection) valueSection.style.display = 'block';
    } else if (['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction)) {
        if (valueLabel) {
            valueLabel.textContent = 'Label for Extracted Data (Optional):';
        }
        if (valueInput) {
            valueInput.placeholder = 'e.g., login_message, user_table';
        }
        if (valueSection) valueSection.style.display = 'block';
    } else if (selectedAction === 'WAIT_FOR_SELECTOR') {
        if (valueLabel) {
            valueLabel.textContent = 'State[:Timeout] (e.g., visible:10000):';
        }
        if (valueInput) {
            valueInput.placeholder = 'visible';
        }
        if (valueSection) valueSection.style.display = 'block';
    } else {
        if (valueSection) valueSection.style.display = 'none';
    }

    // Logic for Mapping Section
    if (
        ['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction) &&
        typeof currentTemplateInfo !== 'undefined' &&
        currentTemplateInfo.previewData &&
        currentTemplateInfo.previewData.length > 0
    ) {
        if (mappingSection) mappingSection.style.display = 'block';
    } else {
        if (mappingSection) mappingSection.style.display = 'none';
    }
}



function showOverlay(targetElement, selector) {
    const overlay = createOverlay(); // Ensure overlay is created and elements exist
    currentOverlayData = { targetElement, selector };
    const errorDiv = overlay.querySelector('#_mr-error-message');
    const actionSelect = overlay.querySelector('#_mr-action-type');
    const valueInput = overlay.querySelector('#_mr-value-input');
    const selectedCellInput = document.getElementById('_mr-selected-template-cell');

    if (errorDiv) { errorDiv.textContent = ''; errorDiv.style.display = 'none'; }
    if (valueInput) valueInput.value = '';
    if (selectedCellInput) selectedCellInput.value = '';

    overlay.querySelector('#_mr-element-tag').textContent = `<${targetElement.tagName.toLowerCase()}>`;
    overlay.querySelector('#_mr-element-selector').textContent = selector;

    let suggestedAction = 'CLICK';
    const tagName = targetElement.tagName.toLowerCase();
    const inputType = targetElement.type?.toLowerCase();
    if (tagName === 'a') suggestedAction = 'NAVIGATE';
    else if (tagName === 'button' || ['submit', 'button', 'reset'].includes(inputType)) suggestedAction = 'CLICK';
    else if ((tagName === 'input' && ['text', 'password', 'email', 'search', 'tel', 'url', 'number'].includes(inputType)) || tagName === 'textarea') suggestedAction = 'TYPE';
    else if (tagName === 'select') suggestedAction = 'SELECT';
    else if (tagName === 'table') suggestedAction = 'EXTRACT_TABLE';
    actionSelect.value = suggestedAction;

    console.log("CONTENT.JS: showOverlay - currentTemplateInfo before render:", currentTemplateInfo);

    renderTemplatePreviewGrid(currentTemplateInfo); // Pass the whole object

    handleActionTypeChange({ target: actionSelect }); // Update visibility

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
    const valueInputText = overlay.querySelector('#_mr-value-input').value.trim(); // Use specific var name
    const selector = currentOverlayData.selector;
    const errorDiv = overlay.querySelector('#_mr-error-message');
    const mappingTargetCell = document.getElementById('_mr-selected-template-cell').value || null;

    errorDiv.textContent = ''; errorDiv.style.display = 'none';

    if (!actionType) { errorDiv.textContent = "Please select an Action Type."; errorDiv.style.display = 'block'; return; }
    if (!selector && !['NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(actionType) ) {
         errorDiv.textContent = "Selector is missing or invalid."; errorDiv.style.display = 'block'; return;
     }

    const stepData = {
        action_type: actionType,
        selector: selector,
        value: valueInputText || null, // Use trimmed value
        mapping_target_cell: mappingTargetCell
    };

    console.log("Content Script: Sending step data to background:", stepData);
    overlay.querySelector('#_mr-save-button').disabled = true;
    overlay.querySelector('#_mr-cancel-button').disabled = true;

    chrome.runtime.sendMessage({ action: "saveStep", data: stepData }, (response) => {
         overlay.querySelector('#_mr-save-button').disabled = false;
         overlay.querySelector('#_mr-cancel-button').disabled = false;

        if (chrome.runtime.lastError || !response) {
            console.error("CS: Error sending/receiving saveStep:", chrome.runtime.lastError?.message || "No response");
            errorDiv.textContent = `Error: ${chrome.runtime.lastError?.message || 'Communication error.'}`;
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
    // If not recording, or if there's no event target,
    // OR if the event target IS the overlay itself,
    // OR if the event target is a DESCENDANT of the overlay, then do nothing.
    if (!isRecorderActive ||
        !event.target ||
        event.target.id === '_megara-recorder-overlay' ||
        event.target.closest('#_megara-recorder-overlay')) {

        // If the mouse is currently over the overlay, ensure any
        // highlight on the main page (from a previous mouseover) is removed.
        // We check event.target.closest() again because the above condition could be true
        // due to !isRecorderActive or !event.target as well.
        if (event.target && event.target.closest && event.target.closest('#_megara-recorder-overlay')) {
            if (highlightedElement && highlightedElement !== event.target.closest('#_megara-recorder-overlay')) {
                // This ensures we only remove highlights from page elements, not trying to remove
                // a highlight from the overlay itself (which it shouldn't have).
                removeHighlight();
            }
        }
        return; // Stop further processing for this event
    }

    // If we reach here, the event is on a page element and we are recording.
    removeHighlight(); // Remove previous highlight from other page elements
    try {
        event.target.classList.add('_megara-recorder-highlight');
        highlightedElement = event.target;
    } catch (e) {
        console.warn("Error applying highlight class:", e, "to element:", event.target);
        highlightedElement = null; // Reset if error
    }
}
function removeHighlight() {
    if (highlightedElement) {
        highlightedElement.classList.remove('_megara-recorder-highlight');
        highlightedElement = null;
    }
}

// --- Click Handling ---
function handleClick(event) {
    // If not recording, or if there's no event target,
    // OR if the event target IS the overlay itself,
    // OR if the event target is a DESCENDANT of the overlay, then do nothing.
    if (!isRecorderActive ||
        !event.target ||
        event.target.id === '_megara-recorder-overlay' ||
        event.target.closest('#_megara-recorder-overlay')) {

        // If the click originated from within the overlay, do not process it as a page interaction.
        // The overlay's own buttons (Save, Cancel) have their specific event listeners.
        console.debug("Click inside overlay ignored by general page handleClick.");
        return; // Stop further processing for this event
    }

    // If we reach here, the click is on a page element and we are recording.
    event.preventDefault(); // Stop the default click action on the page
    event.stopPropagation(); // Stop the click bubbling up on the page

    const targetElement = event.target;
    removeHighlight(); // Remove highlight from the element just clicked on the page

    console.log("Recorder Clicked on page:", targetElement.tagName, targetElement);

    const selector = generateRobustSelector(targetElement);
    console.log("  Generated Selector (robust):", selector);

    if (!selector) {
        alert("Could not generate a reliable selector for the clicked element. Please try a different element or inspect manually.");
        return; // Don't show overlay if no selector found
    }

    // Show the overlay for the user to define the step
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
        console.log("CONTENT.JS: MESSAGE LISTENER - Received message:", message.action);
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
        } else if (message.action === "setTemplatePreview") {

            console.log("CONTENT.JS: setTemplatePreview - Full message received:", message);
            console.log("CONTENT.JS: setTemplatePreview - message.previewData:", message.previewData);

            currentTemplateInfo = { // Store all parts of the preview info
                previewData: message.previewData || [],
                sheetName: message.sheetName,
                allSheetNames: message.allSheetNames || [],
                actualRowsInSheet: message.actualRowsInSheet,
                actualColsInSheet: message.actualColsInSheet,
                message: message.message,
                error: message.error
            };
            const overlay = getOverlayElement();
            if (overlay && overlay.style.display === 'block') { // If overlay is active, refresh its grid
                renderTemplatePreviewGrid(currentTemplateInfo);
                 const actionSelect = overlay.querySelector('#_mr-action-type');
                 if (actionSelect) handleActionTypeChange({target: actionSelect});
            }
            sendResponse({status: "Template preview data processed by content script"});
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