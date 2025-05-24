// content/content.js
console.log("CONTENT.JS: SCRIPT EXECUTION STARTED");

let isRecorderActive = false;
let highlightedElement = null;
let currentOverlayData = null; 
let currentTemplateInfo = {
    previewData: [],
    sheetName: null,
    allSheetNames: [],
    actualRowsInSheet: 0,
    actualColsInSheet: 0,
    message: null,
    error: null
};

// --- Helper: Robust Selector Generation (Keep as is) ---
function isSelectorUnique(selector) {
    if (!selector) { console.debug("[isSelectorUnique] Received empty/null selector."); return false; }
    try {
        const elements = document.querySelectorAll(selector);
        const count = elements.length;
        console.debug(`[isSelectorUnique] Selector: '${selector}', Found elements: ${count}`);
        return count === 1;
    } catch (e) {
        console.warn(`[isSelectorUnique] Invalid or error during querySelectorAll for selector: '${selector}'`, e);
        return false;
    }
}
function getStableClasses(classList) {
    if (!classList || classList.length === 0) return [];
    const unstablePatterns = [ /^(fa-|fas-|far-|fal-|fab-)/, /^(?:col|row|container|grid|flex|d|m|p|mx|my|px|py|pt|pb|pl|pr|ms|me|mt|mb|g|gap)-(?:[0-9]+|auto|xs|sm|md|lg|xl|xxl|none|inline|block|flex|grid|table|contents|list-item|inline-block|inline-flex|inline-grid|inline-table)/, /^(active|focus|hover|disabled|selected|open|closed|collapsed|expanded|current|loading|loaded|dragging|dragover|dropping|error|success|warning|info|modal|tooltip|popover|dropdown|nav|navbar|header|footer|sidebar|main|content|wrapper|container|page|section)/i, /\d/, /^[a-z]{1,2}$/, /^(is-|has-|js-|ui-)/, ];
    const stableClasses = [];
    for (const className of classList) {
        if (className && !unstablePatterns.some(pattern => pattern.test(className))) {
            stableClasses.push(CSS.escape(className));
        }
    }
    console.debug("[getStableClasses] Original:", Array.from(classList), "Filtered:", stableClasses);
    return stableClasses;
}
function generateRobustSelector(element, maxDepth = 3) {
    if (!element || !(element instanceof Element) || element.tagName === 'HTML' || element.tagName === 'BODY' || maxDepth <= 0) {
        console.debug("[generateRobustSelector] Base case: Invalid element, body/html, or maxDepth reached.");
        return null;
    }
    let selector = null; const tagName = element.tagName.toLowerCase();
    console.debug(`[generateRobustSelector] Trying for: <${tagName}>, Depth: ${maxDepth}`, element);
    if (element.id) {
        const idSelector = `#${CSS.escape(element.id)}`; console.debug("[generateRobustSelector] Trying ID:", idSelector);
        if (isSelectorUnique(idSelector)) { console.log("[generateRobustSelector] SUCCESS: Using unique ID:", idSelector); return idSelector; }
        selector = `${tagName}${idSelector}`; console.debug("[generateRobustSelector] Trying Tagged ID:", selector);
        if (isSelectorUnique(selector)) { console.log("[generateRobustSelector] SUCCESS: Using non-unique ID with tag:", selector); return selector; }
    }
    const testAttrs = ['data-testid', 'data-cy', 'data-qa', 'data-test-id', 'data-test', 'data-component'];
    for (const attr of testAttrs) {
        if (element.hasAttribute(attr)) {
            const val = CSS.escape(element.getAttribute(attr)); selector = `${tagName}[${attr}="${val}"]`;
            console.debug(`[generateRobustSelector] Trying Test Attribute ${attr}:`, selector);
            if (isSelectorUnique(selector)) { console.log(`[generateRobustSelector] SUCCESS: Using unique test attribute ${attr}:`, selector); return selector; }
        }
    }
    if (element.name) {
        selector = `${tagName}[name="${CSS.escape(element.name)}"]`; console.debug("[generateRobustSelector] Trying Name attribute:", selector);
        if (isSelectorUnique(selector)) { console.log("[generateRobustSelector] SUCCESS: Using unique name attribute:", selector); return selector; }
    }
    const stableClasses = getStableClasses(element.classList);
    if (stableClasses.length > 0) {
        selector = `${tagName}.${stableClasses.join('.')}`; console.debug("[generateRobustSelector] Trying stable classes:", selector);
        if (isSelectorUnique(selector)) { console.log("[generateRobustSelector] SUCCESS: Using stable classes:", selector); return selector; }
    }
    const parent = element.parentElement;
    if (parent) {
        console.debug("[generateRobustSelector] Trying parent strategy for element:", element);
        const parentSelector = generateRobustSelector(parent, maxDepth - 1);
        if (parentSelector) {
            console.debug("[generateRobustSelector] Parent selector found:", parentSelector);
            selector = `${parentSelector} > ${tagName}`; console.debug("[generateRobustSelector] Trying Parent + child tag:", selector);
            if (isSelectorUnique(selector)) { console.log("[generateRobustSelector] SUCCESS: Using parent + child tag:", selector); return selector; }
            if (stableClasses.length > 0) {
                 const classPart = `.${stableClasses.join('.')}`; selector = `${parentSelector} > ${tagName}${classPart}`;
                 console.debug("[generateRobustSelector] Trying Parent + child tag/class:", selector);
                 if (isSelectorUnique(selector)) { console.log("[generateRobustSelector] SUCCESS: Using parent + child tag/class:", selector); return selector; }
            }
             let index = 1; let sibling = element.previousElementSibling;
             while (sibling) { if (sibling.tagName === element.tagName) { index++; } sibling = sibling.previousElementSibling; }
             const positionalSelector = `${tagName}:nth-of-type(${index})`; selector = `${parentSelector} > ${positionalSelector}`;
             console.debug("[generateRobustSelector] Trying Parent + child position (:nth-of-type):", selector);
              if (isSelectorUnique(selector)) { console.log("[generateRobustSelector] SUCCESS: Using parent + child position:", selector); return selector; }
        } else { console.debug("[generateRobustSelector] No robust selector found for parent."); }
    }
    if (document.querySelectorAll(tagName).length < 5 && document.querySelectorAll(tagName).length > 0) {
        console.warn(`[generateRobustSelector] Could not find unique selector. Falling back to less reliable tagName: ${tagName}`);
        return tagName;
    }
    console.error("[generateRobustSelector] All strategies failed to produce a sufficiently unique selector. Returning null.", element);
    return null;
}
// --- END Robust Selector Generation Logic ---


// --- Overlay Management Functions ---
function getOverlayElement() { return document.getElementById('_megara-recorder-overlay'); }
function createOverlay() { /* Keep as is */
    let overlay = getOverlayElement();
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = '_megara-recorder-overlay';
    overlay.innerHTML = `<h4>Record Step</h4><div class="_mr-element-info">Element: <code id="_mr-element-tag">N/A</code><br>Selector: <code id="_mr-element-selector">N/A</code></div><div><label for="_mr-action-type">Action Type:</label><select id="_mr-action-type">${['CLICK','TYPE','SELECT','EXTRACT_TABLE','EXTRACT_ELEMENT','NAVIGATE','WAIT_FOR_SELECTOR','WAIT_FOR_TIMEOUT'].map(act => `<option value="${act}">${act}</option>`).join('')}</select></div><div class="_mr-value-section" id="_mr-value-section" style="display: none;"><label for="_mr-value-input" id="_mr-value-label">Value:</label><textarea id="_mr-value-input" rows="2"></textarea></div><div class="_mr-mapping-section" id="_mr-mapping-section" style="display: none;"><label>Map Extracted Data to Template Cell (Click a cell below):</label><div class="_mr-sheet-selector-container" style="margin-bottom: 5px; display: none;"><label for="_mr-template-sheet-select" style="font-size:0.9em; margin-right:5px;">Sheet:</label><select id="_mr-template-sheet-select" style="padding:3px; font-size:0.9em;"></select></div><div id="_mr-template-preview-grid-container"><table id="_mr-template-preview-grid"></table><div class="_mr-template-info-footer" style="font-size:0.8em; color:#555; margin-top:5px;"></div></div><input type="hidden" id="_mr-selected-template-cell" /></div><div class="_mr-error-message" id="_mr-error-message" style="display: none;"></div><div class="_mr-button-group"><button class="_mr-cancel-button" id="_mr-cancel-button">Cancel</button><button class="_mr-save-button" id="_mr-save-button">Save Step</button></div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#_mr-action-type').addEventListener('change', handleActionTypeChange);
    overlay.querySelector('#_mr-save-button').addEventListener('click', handleOverlaySave);
    overlay.querySelector('#_mr-cancel-button').addEventListener('click', hideOverlay);
    return overlay;
}
function renderTemplatePreviewGrid(templateInfo) { /* Keep as is */
    console.log("CONTENT.JS: renderTemplatePreviewGrid - Rendering with templateInfo:", JSON.parse(JSON.stringify(templateInfo)));
    const gridTable = document.getElementById('_mr-template-preview-grid');
    const infoFooter = document.querySelector('#_mr-template-preview-grid-container ._mr-template-info-footer');
    const selectedCellInput = document.getElementById('_mr-selected-template-cell');
    const sheetSelectorContainer = document.querySelector('._mr-sheet-selector-container');
    const sheetSelect = document.getElementById('_mr-template-sheet-select');
    gridTable.innerHTML = '';
    if (selectedCellInput) selectedCellInput.value = '';
    if (infoFooter) infoFooter.textContent = '';
    const previewData = templateInfo?.previewData;
    if (sheetSelectorContainer && sheetSelect && templateInfo?.allSheetNames && templateInfo.allSheetNames.length > 1) {
        sheetSelect.innerHTML = '';
        templateInfo.allSheetNames.forEach(name => {
            const option = document.createElement('option'); option.value = name; option.textContent = name;
            if (name === templateInfo.sheetName) option.selected = true; sheetSelect.appendChild(option);
        });
        sheetSelectorContainer.style.display = 'block';
    } else if (sheetSelectorContainer) { sheetSelectorContainer.style.display = 'none'; }
    if (previewData && previewData.length > 0) {
        const anThRow = document.createElement('tr'); const emptyHeaderCell = document.createElement('th'); emptyHeaderCell.style.minWidth = '35px'; anThRow.appendChild(emptyHeaderCell);
        if (previewData[0]) { previewData[0].forEach((_, colIndex) => { const colLetter = String.fromCharCode(65 + colIndex); const th = document.createElement('th'); th.textContent = colLetter; th.style.textAlign = 'center'; anThRow.appendChild(th); }); }
        const thead = document.createElement('thead'); thead.appendChild(anThRow); gridTable.appendChild(thead);
        const tbody = document.createElement('tbody');
        previewData.forEach((rowData, rowIndex) => {
            const tr = document.createElement('tr'); const rowNumCell = document.createElement('th'); rowNumCell.textContent = rowIndex + 1; rowNumCell.style.textAlign = 'center'; rowNumCell.style.backgroundColor = '#f0f0f0'; tr.appendChild(rowNumCell);
            rowData.forEach((cellData, colIndex) => {
                const td = document.createElement('td'); td.textContent = cellData || ''; const colLetter = String.fromCharCode(65 + colIndex); const cellRef = `${colLetter}${rowIndex + 1}`; td.dataset.cellRef = cellRef; td.title = `Cell: ${cellRef}\nValue: ${cellData || ""}`;
                td.addEventListener('click', function () { const currentSelected = gridTable.querySelector('._mr-cell-selected'); if (currentSelected) currentSelected.classList.remove('_mr-cell-selected'); this.classList.add('_mr-cell-selected'); if (selectedCellInput) selectedCellInput.value = this.dataset.cellRef; console.log("Content.JS: Template cell selected:", this.dataset.cellRef); });
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        gridTable.appendChild(tbody);
        if (infoFooter) { infoFooter.textContent = `Sheet: '${templateInfo.sheetName}'. Displaying ${previewData.length} of ${templateInfo.actualRowsInSheet} rows, ${previewData[0] ? previewData[0].length : 0} of ${templateInfo.actualColsInSheet} columns.`; }
    } else { if (infoFooter) infoFooter.textContent = templateInfo?.message || "No template preview available or sheet is empty."; console.log("Content.JS: No preview data to render."); }
}
function handleActionTypeChange(event) { /* Keep as is */
    const selectedAction = event.target.value;
    const valueSection = document.getElementById('_mr-value-section');
    const valueLabel = document.getElementById('_mr-value-label');
    const valueInput = document.getElementById('_mr-value-input');
    const mappingSection = document.getElementById('_mr-mapping-section');
    if (valueInput) valueInput.value = '';
    if (['TYPE', 'SELECT', 'NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(selectedAction)) {
        if (valueLabel) { valueLabel.textContent = 'Value / URL / Option Value / Timeout (ms):'; }
        if (valueInput) { valueInput.placeholder = selectedAction === 'TYPE' ? 'Enter text...' : selectedAction === 'NAVIGATE' ? 'http://...' : selectedAction === 'SELECT' ? 'Option Value' : '1000'; }
        if (valueSection) valueSection.style.display = 'block';
    } else if (['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction)) {
        if (valueLabel) { valueLabel.textContent = 'Label for Extracted Data (Optional):'; }
        if (valueInput) { valueInput.placeholder = 'e.g., login_message, user_table'; }
        if (valueSection) valueSection.style.display = 'block';
    } else if (selectedAction === 'WAIT_FOR_SELECTOR') {
        if (valueLabel) { valueLabel.textContent = 'State[:Timeout] (e.g., visible:10000):'; }
        if (valueInput) { valueInput.placeholder = 'visible'; }
        if (valueSection) valueSection.style.display = 'block';
    } else { if (valueSection) valueSection.style.display = 'none'; }
    if ( ['EXTRACT_ELEMENT', 'EXTRACT_TABLE'].includes(selectedAction) && typeof currentTemplateInfo !== 'undefined' && currentTemplateInfo.previewData && currentTemplateInfo.previewData.length > 0 ) {
        if (mappingSection) mappingSection.style.display = 'block';
    } else { if (mappingSection) mappingSection.style.display = 'none'; }
}

// --- MODIFIED showOverlay function ---
function showOverlay(targetElement, selector) {
    const overlay = createOverlay();
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
    renderTemplatePreviewGrid(currentTemplateInfo);
    handleActionTypeChange({ target: actionSelect });

    // --- Dynamic Positioning Logic ---
    const targetRect = targetElement.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const scrollY = window.scrollY;
    const scrollX = window.scrollX;

    // Temporarily make overlay visible but off-screen to measure its actual dimensions
    overlay.style.visibility = 'hidden';
    overlay.style.display = 'block'; // Use 'block' or the display type it will eventually have
    const overlayWidth = overlay.offsetWidth;
    const overlayHeight = overlay.offsetHeight; // This will consider max-height if content is long
    overlay.style.display = 'none'; // Hide again before final positioning
    overlay.style.visibility = 'visible';

    const offset = 10; // Desired space between target element and overlay

    // Attempt to position below the target element
    let desiredTop = targetRect.bottom + scrollY + offset;
    let desiredLeft = targetRect.left + scrollX;

    // If positioning below makes it go off-screen (or not enough space considering max-height):
    // Check if there's enough space below. overlayHeight here uses the actual rendered height due to max-height
    if (desiredTop + overlayHeight > scrollY + viewportHeight) {
        // Try placing it above the target element
        let potentialTopAbove = targetRect.top + scrollY - overlayHeight - offset;
        if (potentialTopAbove >= scrollY) { // Check if there's space above
            desiredTop = potentialTopAbove;
        } else {
            // Not enough space above or below, try to fit it as best as possible.
            // If it's taller than the viewport (even with max-height and scrolling),
            // this won't fully solve it, but it tries to keep it within bounds.
            if (overlayHeight < viewportHeight - 2 * offset) { // Can it fit with margins?
                 desiredTop = scrollY + (viewportHeight - overlayHeight) / 2; // Vertically center if cannot fit above/below target
            } else {
                 desiredTop = scrollY + offset; // Stick to top with margin
            }
        }
    }
     // Ensure it doesn't go above the viewport top
    if (desiredTop < scrollY) {
        desiredTop = scrollY + offset;
    }
    // Ensure it doesn't go below the viewport bottom if it can be helped
    if (desiredTop + overlayHeight > scrollY + viewportHeight) {
        desiredTop = Math.max(scrollY + offset, scrollY + viewportHeight - overlayHeight - offset);
    }


    // Horizontal positioning: try to align left with target.
    // If it goes off the right edge, shift it left.
    if (desiredLeft + overlayWidth > scrollX + viewportWidth) {
        desiredLeft = scrollX + viewportWidth - overlayWidth - offset; // Align to right edge with offset
    }
    // Ensure it doesn't go off the left edge
    if (desiredLeft < scrollX) {
        desiredLeft = scrollX + offset;
    }

    overlay.style.top = `${desiredTop}px`;
    overlay.style.left = `${desiredLeft}px`;
    overlay.style.display = 'block';
    // --- End of Dynamic Positioning Logic ---
}
// --- END OF MODIFIED showOverlay function ---

function hideOverlay() { /* Keep as is */
    const overlay = getOverlayElement();
    if (overlay) { overlay.style.display = 'none'; }
    currentOverlayData = null;
}
function handleOverlaySave() { /* Keep as is */
    if (!currentOverlayData) return;
    const overlay = getOverlayElement();
    const actionType = overlay.querySelector('#_mr-action-type').value;
    const valueInputText = overlay.querySelector('#_mr-value-input').value.trim();
    const selector = currentOverlayData.selector;
    const errorDiv = overlay.querySelector('#_mr-error-message');
    const mappingTargetCell = document.getElementById('_mr-selected-template-cell').value || null;
    errorDiv.textContent = ''; errorDiv.style.display = 'none';
    if (!actionType) { errorDiv.textContent = "Please select an Action Type."; errorDiv.style.display = 'block'; return; }
    if (!selector && !['NAVIGATE', 'WAIT_FOR_TIMEOUT'].includes(actionType) ) { errorDiv.textContent = "Selector is missing or invalid."; errorDiv.style.display = 'block'; return; }
    const stepData = { action_type: actionType, selector: selector, value: valueInputText || null, mapping_target_cell: mappingTargetCell };
    console.log("Content Script: Sending step data to background:", stepData);
    overlay.querySelector('#_mr-save-button').disabled = true; overlay.querySelector('#_mr-cancel-button').disabled = true;
    chrome.runtime.sendMessage({ action: "saveStep", data: stepData }, (response) => {
         overlay.querySelector('#_mr-save-button').disabled = false; overlay.querySelector('#_mr-cancel-button').disabled = false;
        if (chrome.runtime.lastError || !response) {
            console.error("CS: Error sending/receiving saveStep:", chrome.runtime.lastError?.message || "No response");
            errorDiv.textContent = `Error: ${chrome.runtime.lastError?.message || 'Communication error.'}`; errorDiv.style.display = 'block';
        } else {
            console.log("CS: Background response for saveStep:", response);
            if (!response.success) { errorDiv.textContent = `Error saving: ${response.message || 'Unknown API error'}`; errorDiv.style.display = 'block'; }
            else { console.log("Step saved successfully!"); hideOverlay(); }
        }
    });
}

// --- Highlighting Functions (Keep as is) ---
function addHighlight(event) { if (!isRecorderActive || !event.target || event.target.id === '_megara-recorder-overlay' || event.target.closest('#_megara-recorder-overlay')) { if (event.target && event.target.closest && event.target.closest('#_megara-recorder-overlay')) { if (highlightedElement && highlightedElement !== event.target.closest('#_megara-recorder-overlay')) { removeHighlight(); } } return; } removeHighlight(); try { event.target.classList.add('_megara-recorder-highlight'); highlightedElement = event.target; } catch (e) { console.warn("Error applying highlight class:", e, "to element:", event.target); highlightedElement = null; } }
function removeHighlight() { if (highlightedElement) { highlightedElement.classList.remove('_megara-recorder-highlight'); highlightedElement = null; } }

// --- Click Handling (Keep as is) ---
function handleClick(event) { if (!isRecorderActive || !event.target || event.target.id === '_megara-recorder-overlay' || event.target.closest('#_megara-recorder-overlay')) { console.debug("Click inside overlay ignored by general page handleClick."); return; } event.preventDefault(); event.stopPropagation(); const targetElement = event.target; removeHighlight(); console.log("Recorder Clicked on page:", targetElement.tagName, targetElement); const selector = generateRobustSelector(targetElement); console.log("  Generated Selector (robust):", selector); if (!selector) { alert("Could not generate a reliable selector for the clicked element. Please try a different element or inspect manually."); return; } showOverlay(targetElement, selector); }

// --- Event Listeners Setup (Keep as is) ---
function addListeners() { console.log("CONTENT.JS: Adding event listeners (mouseover, mouseout, click)."); document.addEventListener('mouseover', addHighlight, true); document.addEventListener('mouseout', removeHighlight, true); document.addEventListener('click', handleClick, true); }
function removeListeners() { console.log("CONTENT.JS: Removing event listeners."); removeHighlight(); document.removeEventListener('mouseover', addHighlight, true); document.removeEventListener('mouseout', removeHighlight, true); document.removeEventListener('click', handleClick, true); }

// --- Message Listener & Ready Signal (Keep as is) ---
if (chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        console.log("CONTENT.JS: MESSAGE LISTENER - Received message:", message.action);
        if (message.action === "activateRecording") { if (isRecorderActive) { sendResponse({ status: "Already active" }); return true; } isRecorderActive = true; addListeners(); console.log("CONTENT.JS: Recording ACTIVATED."); sendResponse({ status: "Recording activated in content script" });
        } else if (message.action === "deactivateRecording") { if (!isRecorderActive) { sendResponse({ status: "Already inactive" }); return true; } isRecorderActive = false; removeListeners(); hideOverlay(); console.log("CONTENT.JS: Recording DEACTIVATED."); sendResponse({ status: "Recording deactivated in content script" });
        } else if (message.action === "setTemplatePreview") {
            console.log("CONTENT.JS: setTemplatePreview - Full message received:", message); console.log("CONTENT.JS: setTemplatePreview - message.previewData:", message.previewData);
            currentTemplateInfo = { previewData: message.previewData || [], sheetName: message.sheetName, allSheetNames: message.allSheetNames || [], actualRowsInSheet: message.actualRowsInSheet, actualColsInSheet: message.actualColsInSheet, message: message.message, error: message.error };
            const overlay = getOverlayElement(); if (overlay && overlay.style.display === 'block') { renderTemplatePreviewGrid(currentTemplateInfo); const actionSelect = overlay.querySelector('#_mr-action-type'); if (actionSelect) handleActionTypeChange({target: actionSelect}); }
            sendResponse({status: "Template preview data processed by content script"});
        } else { console.log("CONTENT.JS: Received unhandled message action:", message.action); }
        return true;
    });
    console.log("CONTENT.JS: chrome.runtime.onMessage.addListener has been SET UP.");
} else { console.error("CONTENT.JS: chrome.runtime.onMessage is NOT available."); }
if (chrome.runtime && chrome.runtime.sendMessage) {
    console.log("CONTENT.JS: Sending 'contentScriptReady' message to background.");
    chrome.runtime.sendMessage({ action: "contentScriptReady" }, (response) => { if (chrome.runtime.lastError) { console.warn("CONTENT.JS: Error sending ready message:", chrome.runtime.lastError.message); } else { console.log("CONTENT.JS: Background acknowledged ready message:", response); } });
} else { console.error("CONTENT.JS: chrome.runtime.sendMessage is NOT available for ready signal."); }
console.log("CONTENT.JS: SCRIPT EXECUTION FINISHED.");