// background/background.js

// --- State Management using chrome.storage.local ---
const STORAGE_KEYS = {
    IS_RECORDING: 'isRecording',
    ACTIVE_TAB_ID: 'activeTabId',
    CURRENT_SCENARIO_ID: 'currentScenarioId', // This will be set when recording starts
    AUTH_TOKEN: 'authToken'
};

// In-memory set for tabs where content script is ready
const readyTabs = new Set();

// --- Helper to get state from storage ---
async function getState() {
    try {
        const result = await chrome.storage.local.get([
            STORAGE_KEYS.IS_RECORDING,
            STORAGE_KEYS.ACTIVE_TAB_ID,
            STORAGE_KEYS.CURRENT_SCENARIO_ID
        ]);
        return {
            isRecording: result[STORAGE_KEYS.IS_RECORDING] || false,
            activeTabId: result[STORAGE_KEYS.ACTIVE_TAB_ID] || null,
            currentScenarioId: result[STORAGE_KEYS.CURRENT_SCENARIO_ID] || null
        };
    } catch (error) {
        console.error("BG: Error getting state from storage:", error);
        return { isRecording: false, activeTabId: null, currentScenarioId: null };
    }
}

// --- Helper to set state in storage ---
async function setState(newState) {
    try {
        const stateToSave = {};
        for (const key in newState) {
             if (newState[key] !== undefined) { stateToSave[key] = newState[key]; }
        }
        if (Object.keys(stateToSave).length > 0) {
             await chrome.storage.local.set(stateToSave);
             console.log("BG: State saved to storage:", stateToSave);
        }
    } catch (error) { console.error("BG: Error saving state to storage:", error); }
}

// --- Helper to get JWT token from storage ---
async function getStoredToken() {
    try {
        const result = await chrome.storage.local.get([STORAGE_KEYS.AUTH_TOKEN]);
        return result.authToken;
    } catch (error) { console.error("BG: Error getting token from storage:", error); return null; }
}

// --- Helper to get username from token (for display in popup) ---
function getUsernameFromToken(token) {
    if (!token) return null;
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
        const payload = JSON.parse(jsonPayload);
        return payload?.username || payload?.user_id?.toString() || 'User';
    } catch (e) { console.error("BG: Error decoding token for username:", e); return 'Error'; }
}

console.log("Background script loaded (MV3).");

// --- Main Message Listener (from popup or content scripts) ---
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const action = message?.action || 'Unknown';
    console.log(`BG: Received Action: '${action}'`, message);
    let isAsync = true; // Assume async response unless explicitly set to false

    switch (action) {
        case "contentScriptReady":
            if(sender.tab?.id) { readyTabs.add(sender.tab.id); console.log(`BG: Content script ready Tab ${sender.tab.id}`); }
            sendResponse({ status: "Acknowledged ready" });
            break;

        case "apiLogin":
            const { username, password } = message;
            if (!username || !password) { sendResponse({ success: false, message: "Username/password missing." }); break; }
            const loginApiUrl = `http://localhost:5051/auth/api/login`;
            console.log(`BG: Attempting API login for ${username}...`);
            fetch(loginApiUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' }, body: JSON.stringify({ username, password }) })
            .then(response => {
                if (!response.ok) { return response.json().catch(() => ({})).then(errData => { throw new Error(errData?.message || `API Login Error ${response.status}`); }); }
                return response.json();
            })
            .then(data => {
                if (data.success && data.token) {
                    console.log("BG: API Login successful. Storing token.");
                    chrome.storage.local.set({ [STORAGE_KEYS.AUTH_TOKEN]: data.token })
                        .then(() => { console.log("BG: Token stored."); sendResponse({ success: true, token: data.token, username: username }); })
                        .catch(e => { console.error("BG: Error saving token:", e); sendResponse({ success: false, message: "Storage error" }); });
                } else { throw new Error(data.message || "Invalid login response"); }
            })
            .catch(error => { console.error("BG: API Login error:", error); sendResponse({ success: false, message: error.message || "Login failed" }); });
            break;

        case "apiLogout":
             console.log("BG: Clearing token and recording state.");
             chrome.storage.local.remove([STORAGE_KEYS.AUTH_TOKEN, STORAGE_KEYS.IS_RECORDING, STORAGE_KEYS.ACTIVE_TAB_ID, STORAGE_KEYS.CURRENT_SCENARIO_ID])
             .then(() => { console.log("BG: Token/state removed."); sendResponse({ success: true }); })
             .catch(e => { console.error("BG: Error removing token/state:", e); sendResponse({ success: false, message: "Logout storage error"}); });
             break;

        case "checkAuthStatus":
             getStoredToken().then(token => {
                  if (token) { sendResponse({ isLoggedIn: true, username: getUsernameFromToken(token), token: token }); }
                  else { sendResponse({ isLoggedIn: false }); }
             });
             break;

        case "getScenarioList":
            const listApiUrl = `http://localhost:5051/scenarios/api/scenarios/list`;
            console.log(`BG: Fetching scenario list from ${listApiUrl}`);
            getStoredToken().then(token => {
                if (!token) { sendResponse({ success: false, message: "Not logged in" }); return; }
                fetch(listApiUrl, { headers: { 'Accept': 'application/json', 'Authorization': `Bearer ${token}` } })
                .then(response => {
                    if (response.status === 401) throw new Error("Unauthorized (Token invalid/expired?)");
                    if (!response.ok) throw new Error(`API Error ${response.status}: ${response.statusText}`);
                    return response.json();
                })
                .then(data => { if (data?.success) { sendResponse(data); } else { throw new Error(data?.message || "Invalid API response for scenarios."); } })
                .catch(error => { console.error("BG: Error fetching scenarios:", error); sendResponse({ success: false, message: error.message }); });
            });
            break;

        case "startRecording":
            const scenarioIdFromPopup = message.scenarioId;
            if (!scenarioIdFromPopup) { sendResponse({ status: "Status: Error (No Scenario Selected)" }); break; }
            (async () => {
                const currentState = await getState();
                if (currentState.isRecording) { sendResponse({ status: "Status: Already Recording" }); return; }
                const token = await getStoredToken();
                if (!token) { sendResponse({ status: "Status: Error (Not Logged In)" }); return; }

                chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
                    if (!tabs || tabs.length === 0) { sendResponse({ status: "Status: Error (No active tab)" }); return; }
                    const tabIdToRecord = tabs[0].id;

                    const trySendingActivation = (attempt = 1) => {
                        return new Promise((resolve, reject) => {
                            console.log(`BG: Attempt ${attempt} to activate Tab ${tabIdToRecord} for Scenario ${scenarioIdFromPopup}`);
                            chrome.tabs.sendMessage(tabIdToRecord, { action: "activateRecording" }, (response) => {
                                if (chrome.runtime.lastError) {
                                    const errorMsg = chrome.runtime.lastError.message || "Unknown connection error";
                                    console.error(`BG: Attempt ${attempt} - Activate error:`, errorMsg);
                                    if (errorMsg.includes("Receiving end does not exist") && attempt < 3) {
                                        setTimeout(() => trySendingActivation(attempt + 1).then(resolve).catch(reject), 500);
                                    } else { reject(new Error(errorMsg)); }
                                } else { console.log("BG: Activation successful. Response:", response); resolve(true); }
                            });
                        });
                    };

                    try {
                        await trySendingActivation();
                        await setState({
                            [STORAGE_KEYS.IS_RECORDING]: true,
                            [STORAGE_KEYS.ACTIVE_TAB_ID]: tabIdToRecord,
                            [STORAGE_KEYS.CURRENT_SCENARIO_ID]: scenarioIdFromPopup
                         });
                        sendResponse({ status: "Status: Recording..." });
                    } catch (error) {
                        console.error("BG: Final activation attempt failed:", error);
                        await setState({ [STORAGE_KEYS.IS_RECORDING]: false, [STORAGE_KEYS.ACTIVE_TAB_ID]: null, [STORAGE_KEYS.CURRENT_SCENARIO_ID]: null });
                        sendResponse({ status: "Status: Error Activating Content Script" });
                    }
                }); // End chrome.tabs.query
            })(); // Execute async IIFE
            break;

        case "stopRecording":
             (async () => {
                 const currentState = await getState();
                 if (!currentState.isRecording) { sendResponse({ status: "Status: Not Recording" }); return; }
                 const tabToDeactivate = currentState.activeTabId;
                 console.log(`BG: Stopping recording Tab ${tabToDeactivate} Scenario ${currentState.currentScenarioId}`);
                 await setState({ [STORAGE_KEYS.IS_RECORDING]: false, [STORAGE_KEYS.ACTIVE_TAB_ID]: null, [STORAGE_KEYS.CURRENT_SCENARIO_ID]: null });
                 if (tabToDeactivate) readyTabs.delete(tabToDeactivate);
                 if (tabToDeactivate) {
                     chrome.tabs.sendMessage(tabToDeactivate, { action: "deactivateRecording" }, (response) => {
                         if (chrome.runtime.lastError) console.warn("BG: Error sending deactivate:", chrome.runtime.lastError.message);
                         else console.log("BG: Deactivation sent. Response:", response);
                         sendResponse({ status: "Status: Idle" });
                     });
                 } else { sendResponse({ status: "Status: Idle (No active tab ID)" }); }
             })();
             break;

        case "saveStep":
             (async () => {
                 const currentState = await getState();
                 if (!currentState.isRecording || !currentState.currentScenarioId) { sendResponse({ success: false, message: "Not recording/no scenario" }); return; }
                 const token = await getStoredToken();
                 if (!token) { sendResponse({ success: false, message: "Not logged in" }); return; }

                 console.log(`BG: Saving step for Scenario ${currentState.currentScenarioId}:`, message.data);
                 const apiUrl = `http://localhost:5051/scenarios/api/scenarios/${currentState.currentScenarioId}/steps`;
                 const fetchOptions = { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }, body: JSON.stringify(message.data) };

                 try {
                      console.log(`BG: Sending step data to API: ${apiUrl}`);
                      const response = await fetch(apiUrl, fetchOptions);
                      if (response.status === 401) { throw new Error("Unauthorized"); }
                      if (!response.ok) { const text = await response.text(); throw new Error(`API Error ${response.status}: ${text || response.statusText}`); }
                      const contentType = response.headers.get("content-type");
                      let data = contentType?.includes("application/json") ? await response.json() : { success: true, message: "Step saved (non-JSON OK)." };
                      console.log("BG: Step save API response:", data);
                      if (data?.success) { sendResponse({ success: true, message: "Step saved." }); }
                      else { throw new Error(data?.message || "API reported failure."); }
                 } catch (error) { console.error("BG: Error saving step via API:", error); sendResponse({ success: false, message: `API Error: ${error.message}` }); }
             })();
             break;

        default:
            console.warn("BG: Unhandled message action:", action);
            isAsync = false; // No async operation for default
            break;
    }
    return isAsync; // Keep channel open for async responses
});

// --- Listener for tab removal ---
chrome.tabs.onRemoved.addListener(async (tabId, removeInfo) => {
    if (readyTabs.has(tabId)) { readyTabs.delete(tabId); console.log(`BG: Tab ${tabId} removed, cleared ready.`); }
    const currentState = await getState();
    if (currentState.isRecording && currentState.activeTabId === tabId) {
         console.warn(`BG: Recording tab ${tabId} removed! Stopping state.`);
         await setState({ [STORAGE_KEYS.IS_RECORDING]: false, [STORAGE_KEYS.ACTIVE_TAB_ID]: null, [STORAGE_KEYS.CURRENT_SCENARIO_ID]: null });
    }
});

console.log("Background script event listeners added.");