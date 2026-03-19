/**
 * JobAgent Popup — Settings & Status Hub
 * Manages LLM provider selection, API key, and connection status.
 */

const API_BASE = 'http://localhost:8000';

// ── DOM refs ──
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const providerSelect = document.getElementById('provider-select');
const modelSelect = document.getElementById('model-select');
const apiKeyField = document.getElementById('api-key-field');
const apiKeyInput = document.getElementById('api-key-input');
const apiKeySave = document.getElementById('api-key-save');
const connBanner = document.getElementById('conn-banner');
const connText = document.getElementById('conn-text');
const btnDashboard = document.getElementById('btn-dashboard');
const btnTest = document.getElementById('btn-test');
const footerStats = document.getElementById('footer-stats');

// ── State ──
let providersData = null;
let currentSettings = null;

// ── Helpers ──

function setStatus(state, text) {
	statusDot.className = 'status-dot ' + state; // 'connected' | 'error' | 'checking'
	statusText.textContent = text;
}

function setConnBanner(type, icon, text) {
	connBanner.className = 'conn-banner ' + type; // 'ok' | 'err' | 'loading'
	connBanner.innerHTML = `<span>${icon}</span><span>${text}</span>`;
}

async function apiFetch(path, options = {}) {
	try {
		const res = await fetch(API_BASE + path, {
			...options,
			headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
		});
		return await res.json();
	} catch (e) {
		console.error(`API fetch failed (${path}):`, e);
		return null;
	}
}

// ── Bootstrap ──

async function init() {
	setStatus('checking', 'Connecting...');
	setConnBanner('loading', '⏳', 'Connecting to backend...');

	// 1. Load providers
	providersData = await apiFetch('/api/settings/providers');
	if (!providersData) {
		setStatus('error', 'Offline');
		setConnBanner('err', '❌', 'Backend not running. Start with: uvicorn backend.main:app');
		return;
	}

	// 2. Load current settings
	currentSettings = await apiFetch('/api/settings');

	// 3. Populate provider dropdown
	const currentProvider = providersData.current_provider || 'groq';
	providerSelect.value = currentProvider;

	// 4. Populate models for current provider
	populateModels(currentProvider);

	// 5. Show/hide API key field
	toggleApiKeyField(currentProvider);

	// 6. Mask existing API key if present
	if (providersData.groq?.has_api_key) {
		apiKeyInput.placeholder = '••••••••••••••••  (saved)';
	}

	// 7. Test connection
	await testConnection();

	// 8. Footer stats
	try {
		const stats = await apiFetch('/api/tracker/stats');
		if (stats) {
			const total = stats.total || 0;
			const provider = currentProvider === 'groq' ? 'Groq' : 'Ollama';
			footerStats.textContent = `v1.1 · ${provider} · ${total} jobs`;
		}
	} catch { /* ok */ }
}

function populateModels(provider) {
	modelSelect.innerHTML = '';

	const providerInfo = providersData?.[provider];
	if (!providerInfo || !providerInfo.models || providerInfo.models.length === 0) {
		const opt = document.createElement('option');
		opt.textContent = provider === 'ollama' ? 'No models found (is Ollama running?)' : 'No models available';
		opt.disabled = true;
		modelSelect.appendChild(opt);
		return;
	}

	const currentModel = providersData.current_model || '';

	providerInfo.models.forEach(m => {
		const opt = document.createElement('option');
		opt.value = m;
		// Shorten display name for readability
		opt.textContent = m.length > 40 ? m.split('/').pop() : m;
		if (m === currentModel) opt.selected = true;
		modelSelect.appendChild(opt);
	});
}

function toggleApiKeyField(provider) {
	apiKeyField.style.display = provider === 'groq' ? 'block' : 'none';
}

async function testConnection() {
	setStatus('checking', 'Testing...');
	setConnBanner('loading', '⏳', 'Testing LLM connection...');

	const result = await apiFetch('/api/settings/test_connection');

	if (!result) {
		setStatus('error', 'Offline');
		setConnBanner('err', '❌', 'Backend not running');
		return;
	}

	if (result.ok) {
		const shortModel = (result.model || '').split('/').pop();
		setStatus('connected', 'Connected');
		setConnBanner('ok', '✅', `Connected · ${result.provider} · ${shortModel}`);
	} else {
		setStatus('error', 'Failed');
		const errMsg = result.error ? result.error.substring(0, 80) : 'Connection failed';
		setConnBanner('err', '❌', errMsg);
	}
}

async function saveSettings() {
	if (!currentSettings) return;

	const provider = providerSelect.value;
	const model = modelSelect.value;

	currentSettings.llm_provider = provider;
	if (provider === 'groq') {
		currentSettings.groq_model = model;
	} else {
		currentSettings.ollama_model = model;
	}

	setConnBanner('loading', '⏳', 'Saving & testing...');

	const result = await apiFetch('/api/settings', {
		method: 'POST',
		body: JSON.stringify(currentSettings),
	});

	if (result && result.saved) {
		// Re-test connection with new settings
		await testConnection();

		// Update footer
		const provLabel = provider === 'groq' ? 'Groq' : 'Ollama';
		footerStats.textContent = footerStats.textContent.replace(/Groq|Ollama/, provLabel);
	} else {
		setConnBanner('err', '❌', 'Failed to save settings');
	}
}

// ── Event Listeners ──

providerSelect.addEventListener('change', () => {
	const provider = providerSelect.value;
	populateModels(provider);
	toggleApiKeyField(provider);
	saveSettings();
});

modelSelect.addEventListener('change', () => {
	saveSettings();
});

apiKeySave.addEventListener('click', async () => {
	const key = apiKeyInput.value.trim();
	if (!key) return;

	apiKeySave.textContent = '...';
	apiKeySave.disabled = true;

	const result = await apiFetch('/api/settings/api_key', {
		method: 'POST',
		body: JSON.stringify({ key_name: 'GROQ_API_KEY', key_value: key }),
	});

	if (result && result.saved) {
		apiKeyInput.value = '';
		apiKeyInput.placeholder = '••••••••••••••••  (saved)';
		apiKeySave.textContent = '✓';

		// Refresh providers data to reflect new key
		providersData = await apiFetch('/api/settings/providers');
		await testConnection();
	} else {
		apiKeySave.textContent = '✗';
	}

	setTimeout(() => {
		apiKeySave.textContent = 'Save';
		apiKeySave.disabled = false;
	}, 1500);
});

btnDashboard.addEventListener('click', () => {
	chrome.tabs.create({ url: 'http://localhost:8000' });
});

btnTest.addEventListener('click', async () => {
	btnTest.querySelector('span').textContent = '⏳';
	await testConnection();
	btnTest.querySelector('span').textContent = '🔌';
});

// ── Init ──
init();
