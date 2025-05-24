// popup/popup.js
const startButton = document.getElementById('startRecord');
const stopButton = document.getElementById('stopRecord');
const statusDiv = document.getElementById('status');
const scenarioSelect = document.getElementById('scenarioSelect');

// Login/Logout Elements
const loginSection = document.getElementById('loginSection');
const loggedInSection = document.getElementById('loggedInSection');
const loginButton = document.getElementById('loginButton');
const logoutButton = document.getElementById('logoutButton');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const loginErrorDiv = document.getElementById('loginError');
const separator = document.getElementById('separator');
const userInfoDiv = document.getElementById('userInfo');
const loggedInUserSpan = document.getElementById('loggedInUser');

// Temporary token storage in popup scope (cleared on popup close)
// Background script manages the authoritative token in chrome.storage.local
let currentPopupToken = null;

// --- UI State Functions ---
function showLoginUI() {
    console.log("[Popup] showLoginUI called");
    loginSection.classList.remove('hidden');
    loggedInSection.classList.add('hidden');
    separator.classList.add('hidden');
    updateStatus('Needs Login', 'idle');
    loginErrorDiv.classList.add('hidden');
    loginErrorDiv.textContent = '';
    scenarioSelect.innerHTML = '<option value=""> Log In To Load </option>';
    scenarioSelect.disabled = true;
}

function showLoggedInUI(username = 'User') {
    console.log("[Popup] showLoggedInUI called with username:", username);
    loginSection.classList.add('hidden');
    loggedInSection.classList.remove('hidden');
    separator.classList.remove('hidden');
    updateStatus('Idle', 'idle');
    loggedInUserSpan.textContent = username || 'User';
    loginErrorDiv.classList.add('hidden');
    loginErrorDiv.textContent = '';
    loadScenarios(); // Load scenarios now that UI is ready
}

function showLoginError(message) {
    loginErrorDiv.textContent = message;
    loginErrorDiv.classList.remove('hidden');
    updateStatus('Login Error', 'error');
}

function updateStatus(text, type = 'idle') { // types: idle, recording, error, success
    statusDiv.textContent = `Status: ${text}`;
    statusDiv.className = `status-bar status-${type}`;
}

// --- Function to fetch and populate scenarios ---
async function loadScenarios() {
    console.log("Popup: Requesting scenario list from background.");
    updateStatus('Loading Scenarios...', 'idle');
    scenarioSelect.disabled = true;
    scenarioSelect.innerHTML = '<option value=""> Loading... --</option>';

    try {
        const response = await new Promise((resolve, reject) => {
            chrome.runtime.sendMessage({ action: "getScenarioList" }, (res) => {
                if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
                else resolve(res);
            });
        });

        scenarioSelect.innerHTML = ''; // Clear placeholder
        console.log("[Popup] Received scenario list response:", response);

        if (!response) { throw new Error("No response from background for scenario list."); }

        if (response.success && Array.isArray(response.scenarios)) {
            console.log("[Popup] Response success. Scenario count:", response.scenarios.length);
            if (response.scenarios.length === 0) {
                const option = document.createElement('option'); option.value = ""; option.textContent = " No Scenarios Found "; scenarioSelect.appendChild(option);
                updateStatus('Idle (No Scenarios)', 'idle');
            } else {
                 const defaultOption = document.createElement('option'); defaultOption.value = ""; defaultOption.textContent = " Select a Scenario "; scenarioSelect.appendChild(defaultOption);
                response.scenarios.forEach(scenario => {
                    console.log("[Popup] Adding scenario:", scenario);
                    const option = document.createElement('option');
                    option.value = scenario.id;
                    option.textContent = scenario.name;
                    scenarioSelect.appendChild(option);
                });
                updateStatus('Idle', 'idle');
                scenarioSelect.disabled = false;
            }
        } else {
            const errorMsg = response.message || "Invalid response structure for scenarios.";
            console.error("[Popup] Scenario list response indicates failure:", errorMsg);
            updateStatus(`Error: ${errorMsg}`, 'error');
            const option = document.createElement('option'); option.value = ""; option.textContent = " Error Parsing List "; scenarioSelect.appendChild(option);
        }
    } catch (error) {
        console.error("Popup: Exception in loadScenarios:", error);
        updateStatus(`Exception: ${error.message || error}`, 'error');
        scenarioSelect.innerHTML = '<option value=""> Error Loading </option>';
    }
}

// --- Login Button Listener ---
loginButton.addEventListener('click', () => {
    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();
    if (!username || !password) { showLoginError("Username/password required."); return; }

    loginErrorDiv.classList.add('hidden'); updateStatus('Logging in...', 'idle');
    console.log("Popup: Sending login request to background.");
    chrome.runtime.sendMessage({ action: "apiLogin", username, password }, (response) => {
         if (chrome.runtime.lastError || !response) {
             showLoginError(`Login failed: ${chrome.runtime.lastError?.message || "No response."}`); return;
         }
         console.log("Popup: Login response received:", response);
         if (response.success && response.token) {
             currentPopupToken = response.token; // Store for UI checks
             showLoggedInUI(username);
         } else { showLoginError(response.message || "Login failed (API error)."); }
    });
});

// --- Logout Button Listener ---
logoutButton.addEventListener('click', () => {
     console.log("Popup: Sending logout request to background.");
     updateStatus('Logging out...', 'idle');
     chrome.runtime.sendMessage({ action: "apiLogout" }, (response) => {
          if (chrome.runtime.lastError || !response?.success) { console.error("Popup: Error logging out:", chrome.runtime.lastError?.message || response?.message); }
          else { console.log("Popup: Logout successful."); }
          currentPopupToken = null; // Clear popup's token
          showLoginUI();
     });
});

// --- Start Recording Button Listener ---
startButton.addEventListener('click', () => {
    console.log("Popup: Start Recording button CLICKED!");
    const selectedScenarioId = scenarioSelect.value;

    if (!currentPopupToken) { alert("Please log in first."); return; } // Check popup token
    if (!selectedScenarioId) { alert("Please select a scenario from the dropdown."); return; }

    console.log(`Popup: Requesting START Recording for Scenario ID: ${selectedScenarioId}`);
    updateStatus('Starting Recording...', 'idle');

    chrome.runtime.sendMessage({ action: "startRecording", scenarioId: selectedScenarioId }, (response) => {
        if (chrome.runtime.lastError || !response) {
            const errorMsg = chrome.runtime.lastError?.message || "No response.";
            console.error("Popup: Error sending start message:", errorMsg);
            updateStatus(`Error Starting: ${errorMsg}`, 'error');
        } else {
            console.log("Popup: Start message sent, response:", response);
            const statusText = response.status || 'Unknown Status';
            if (statusText.includes('Recording')) updateStatus('Recording...', 'recording');
            else if (statusText.includes('Error')) updateStatus(statusText, 'error');
            else updateStatus(statusText, 'idle');
        }
    });
});

// --- Stop Recording Button Listener ---
stopButton.addEventListener('click', () => {
    console.log("Popup: Requesting STOP Recording");
    updateStatus('Stopping Recording...', 'idle');
    chrome.runtime.sendMessage({ action: "stopRecording" }, (response) => {
         if (chrome.runtime.lastError || !response) {
             const errorMsg = chrome.runtime.lastError?.message || "No response.";
             console.error("Popup: Error sending stop message:", errorMsg);
             updateStatus(`Error Stopping: ${errorMsg}`, 'error');
        } else {
            console.log("Popup: Stop message sent, response:", response);
             updateStatus('Idle', 'idle');
            loadScenarios(); // Reload scenarios after stopping
        }
    });
});

// --- Initial Check on Popup Open (DOMContentLoaded) ---
document.addEventListener('DOMContentLoaded', async () => {
    console.log("Popup: DOM Loaded. Checking initial auth status.");
    try {
        const authResponse = await new Promise((resolve, reject) => {
            chrome.runtime.sendMessage({ action: "checkAuthStatus" }, (res) => {
                if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
                else resolve(res);
            });
        });
        console.log("[Popup] Initial Auth Status Response:", authResponse);

        if (authResponse?.isLoggedIn) {
            currentPopupToken = authResponse.token; // Set popup's temp token
            showLoggedInUI(authResponse.username); // Pass username from auth check
        } else {
            showLoginUI();
        }
    } catch (error) {
        console.warn("Popup: Error during initial auth check:", error.message || error);
        showLoginUI();
    }
});