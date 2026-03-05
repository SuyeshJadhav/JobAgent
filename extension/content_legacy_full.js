// ARCHIVED: Full autofill logic including radio/dropdown parsing. Kept for reference.

// ─── Inject the floating autofill button ─────────────────────────────────

function injectAutofillButton() {
	if (document.getElementById('jobagent-autofill-btn')) return;

	const btn = document.createElement('button');
	btn.id = 'jobagent-autofill-btn';
	btn.textContent = '\u{1FA84} Autofill with JobAgent';
	Object.assign(btn.style, {
		position: 'fixed',
		bottom: '30px',
		right: '30px',
		zIndex: '2147483647',
		fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
		background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
		color: '#ffffff',
		border: 'none',
		padding: '16px 24px',
		borderRadius: '24px',
		fontSize: '16px',
		fontWeight: '600',
		cursor: 'pointer',
		boxShadow: '0 8px 24px rgba(99, 102, 241, 0.5)',
		transition: 'transform 0.15s ease, box-shadow 0.15s ease',
		letterSpacing: '0.3px',
	});

	btn.addEventListener('mouseenter', () => {
		btn.style.transform = 'scale(1.05)';
		btn.style.boxShadow = '0 12px 32px rgba(99, 102, 241, 0.6)';
	});
	btn.addEventListener('mouseleave', () => {
		btn.style.transform = 'scale(1)';
		btn.style.boxShadow = '0 8px 24px rgba(99, 102, 241, 0.5)';
	});

	document.body.appendChild(btn);

	btn.addEventListener('click', handleAutofillClick);
}

window.addEventListener('load', () => {
	injectAutofillButton();
	injectSaveJobButton();
	injectMarkAppliedButton();

	const observer = new MutationObserver(() => {
		injectAutofillButton();
		injectSaveJobButton();
		injectMarkAppliedButton();
	});
	observer.observe(document.body, { childList: true, subtree: true });
});

// ─── Helper: extract a question/label for any element ────────────────────

function extractQuestion(el) {
	let question = '';

	// Priority 1: Explicit <label> via "for" attribute
	if (el.id) {
		const label = document.querySelector(`label[for="${el.id}"]`);
		if (label) question = label.textContent.trim();
	}

	// Priority 2: aria-labelledby or aria-label
	if (!question && el.getAttribute('aria-labelledby')) {
		const labelId = el.getAttribute('aria-labelledby');
		const labelEl = document.getElementById(labelId);
		if (labelEl) question = labelEl.textContent.trim();
	}

	if (!question && el.getAttribute('aria-label')) {
		question = el.getAttribute('aria-label').trim();
	}

	// Priority 3: Workday specific data-automation-id label matching
	if (!question && el.hasAttribute('data-automation-id')) {
		const autoId = el.getAttribute('data-automation-id');
		const relatedLabel = document.querySelector(`[data-automation-id="label-${autoId}"], [data-automation-id*="${autoId}"] label`);
		if (relatedLabel) {
			question = relatedLabel.textContent.trim();
		} else {
			// Parse the attribute itself. e.g. "legalNameSection_firstName" -> "First Name"
			const parts = autoId.split('_');
			const lastPart = parts[parts.length - 1] || '';
			question = lastPart.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase()).trim();
		}
	}

	// Priority 4: Placeholder
	if (!question && el.placeholder) {
		question = el.placeholder.trim();
	}

	// Priority 5: Walk up to find nearest standard label or legend
	if (!question) {
		const parent = el.closest(
			'.form-group, .field, fieldset, [class*="field"], [class*="question"]'
		);
		if (parent) {
			const lbl = parent.querySelector('label, legend, [class*="label"]');
			if (lbl) question = lbl.textContent.trim();
		}
	}

	// Priority 7: Deep Label Search for custom wrapping divs (Workday, Lever, etc.)
	if (!question) {
		let current = el.parentElement;
		while (current && current !== document.body && !question) {
			if (current.className && typeof current.className === 'string' &&
				(current.className.includes('css-') || current.className.includes('field') || current.className.includes('container'))) {
				const lbl = current.querySelector('[class*="label"], [id*="label"], label');
				if (lbl && lbl !== el && !lbl.contains(el)) {
					question = lbl.textContent.trim();
				}
			}
			current = current.parentElement;
		}
	}

	// Priority 8: Workday H3 Contextual Traversal
	if (!question || question.toLowerCase().includes('upload a file')) {
		const group = el.closest('div[role="group"], [data-automation-id*="formField"], .form-group');
		if (group) {
			const h3 = group.querySelector('h3');
			if (h3) {
				const sectionTitle = h3.textContent.trim();
				question = question ? `${sectionTitle} - ${question}` : sectionTitle;
			}
		}
	}

	// Priority 9: Name attribute as last resort
	if (!question && el.name) {
		question = el.name.replace(/[_\-]/g, ' ').trim();
	}

	return question;
}

// ─── Helper: extract an option label specifically for a radio button ───────
function getRadioLabel(radio) {
	if (radio.id) {
		const lbl = document.querySelector(`label[for="${radio.id}"]`);
		if (lbl) return lbl.textContent.trim();
	}
	if (radio.getAttribute('aria-label')) {
		return radio.getAttribute('aria-label').trim();
	}
	return radio.value || '';
}

// ─── Helper: Normalize strings for robust matching ────────────────────────
const normalizeKey = (str) => str ? str.toLowerCase().replace(/[^a-z0-9]/g, '') : '';

// ─── Shared form parsing helpers ─────────────────────────────────────────

function parseTextInputs(selectors) {
	const fields = [];
	document.querySelectorAll(selectors.join(', ')).forEach((el) => {
		if (el.offsetParent === null && el.type !== 'hidden') return;
		if (el.type === 'hidden') return;

		const question = extractQuestion(el);
		if (question) {
			fields.push({ type: 'text', element: el, question });
		}
	});
	return fields;
}

function parseSelectFields() {
	const fields = [];
	document.querySelectorAll('select').forEach((el) => {
		if (el.offsetParent === null) return;

		let question = extractQuestion(el);
		if (!question) return;

		const options = [];
		for (const opt of el.options) {
			const text = opt.textContent.trim();
			if (text && !text.startsWith('--') && !text.toLowerCase().startsWith('select')) {
				options.push(text);
			}
		}

		if (options.length > 0) {
			question += ` (Options: ${options.join(', ')})`;
		}

		fields.push({ type: 'select', element: el, question });
	});
	return fields;
}

function parseRadioGroupFields() {
	const fields = [];
	const radioGroups = new Map();

	document.querySelectorAll('input[type="radio"]').forEach((radio) => {
		if (radio.offsetParent === null) return;
		const groupName = radio.name;
		if (!groupName) return;

		if (!radioGroups.has(groupName)) {
			radioGroups.set(groupName, []);
		}
		radioGroups.get(groupName).push(radio);
	});

	radioGroups.forEach((radios, groupName) => {
		let question = '';

		const fieldset = radios[0].closest('fieldset');
		if (fieldset) {
			const legend = fieldset.querySelector('legend');
			if (legend) question = legend.textContent.trim();
		}

		if (!question) {
			const parent = radios[0].closest(
				'.form-group, .field, [class*="field"], [class*="question"], [role="group"]'
			);
			if (parent) {
				const lbl = parent.querySelector(
					'label, legend, [class*="label"], [class*="question"]'
				);
				if (lbl && !lbl.querySelector('input')) {
					question = lbl.textContent.trim();
				}
			}
		}

		if (!question) {
			question = groupName.replace(/[_\-]/g, ' ').trim();
		}

		const optionLabels = radios.map(getRadioLabel).filter(Boolean);
		if (optionLabels.length > 0) {
			question += ` (Options: ${optionLabels.join(', ')})`;
		}

		fields.push({
			type: 'radio',
			elements: radios,
			element: radios[0],
			question,
		});
	});

	return fields;
}

// ─── Site-specific form parsers ──────────────────────────────────────────

function parseWorkdayFields(container) {
	const textSelectors = [
		'input[type="text"]',
		'input[type="email"]',
		'input[type="tel"]',
		'input[type="url"]',
		'input:not([type])',
		'textarea',
		'input[data-automation-id]',
		'textarea[data-automation-id]',
		'input[placeholder="Search"]',
		'input[type="file"]',
	];

	const fields = [
		...parseTextInputs(textSelectors),
		...parseSelectFields(),
		...parseRadioGroupFields(),
	];

	// Workday-specific: "Add" buttons for sections like Websites
	document.querySelectorAll('button[data-automation-id="add-button"]').forEach((btn) => {
		if (btn.offsetParent === null) return;

		let question = '';
		const group = btn.closest('div[role="group"], [data-automation-id*="section"], .form-group');
		if (group) {
			const h3 = group.querySelector('h3');
			if (h3) question = h3.textContent.trim();
		}

		if (!question) question = btn.innerText.trim();

		fields.push({
			type: 'add_button',
			element: btn,
			question: question || 'Add Section'
		});
	});

	return fields;
}

function parseGreenhouseFields(container) {
	const textSelectors = [
		'input[type="text"]',
		'input[type="email"]',
		'input[type="tel"]',
		'input[type="url"]',
		'input:not([type])',
		'textarea',
		'input[type="file"]',
	];

	return [
		...parseTextInputs(textSelectors),
		...parseSelectFields(),
		...parseRadioGroupFields(),
	];
}

function parseLeverFields(container) {
	const textSelectors = [
		'input[type="text"]',
		'input[type="email"]',
		'input[type="tel"]',
		'input[type="url"]',
		'input:not([type])',
		'textarea',
		'input[type="file"]',
	];

	return [
		...parseTextInputs(textSelectors),
		...parseSelectFields(),
		...parseRadioGroupFields(),
	];
}

function parseGenericFields(container) {
	const textSelectors = [
		'input[type="text"]',
		'input[type="email"]',
		'input[type="tel"]',
		'input[type="url"]',
		'input:not([type])',
		'textarea',
		'input[type="file"]',
	];

	return [
		...parseTextInputs(textSelectors),
		...parseSelectFields(),
		...parseRadioGroupFields(),
	];
}

// ─── Form scraping router ────────────────────────────────────────────────

function scrapeFormFields() {
	const hostname = window.location.hostname;
	const container = document.body;

	if (hostname.includes('myworkdayjobs.com') || hostname.includes('workday.com')) {
		return parseWorkdayFields(container);
	}
	if (hostname.includes('greenhouse.io') || hostname.includes('boards.greenhouse.io')) {
		return parseGreenhouseFields(container);
	}
	if (hostname.includes('lever.co') || hostname.includes('jobs.lever.co')) {
		return parseLeverFields(container);
	}

	return parseGenericFields(container);
}

function scrapeJobDescription() {
	// Try common JD selectors
	const selectors = [
		'[data-automation-id="jobPostingDescription"]',
		'.job-description',
		'#content',
		'.description',
		'[class*="jobDescription"]'
	];
	for (const sel of selectors) {
		const el = document.querySelector(sel);
		if (el) return el.innerText.trim();
	}
	return '';
}

/**
 * Injects a value into a form element using React-safe event dispatching.
 * Fires both 'input' and 'change' events with bubbling so React/Angular detect it.
 */
function injectReactSafeValue(element, value) {
	element.value = value;
	element.dispatchEvent(new Event('input', { bubbles: true }));
	element.dispatchEvent(new Event('change', { bubbles: true }));
}

/**
 * Injects a Base64-encoded PDF into a file input via the DataTransfer API.
 */
function injectBase64File(fileInput, base64String, filename) {
	try {
		const byteCharacters = atob(base64String);
		const byteNumbers = new Array(byteCharacters.length);
		for (let i = 0; i < byteCharacters.length; i++) {
			byteNumbers[i] = byteCharacters.charCodeAt(i);
		}
		const byteArray = new Uint8Array(byteNumbers);
		const blob = new Blob([byteArray], { type: 'application/pdf' });
		const file = new File([blob], filename, { type: 'application/pdf' });

		const dataTransfer = new DataTransfer();
		dataTransfer.items.add(file);
		fileInput.files = dataTransfer.files;

		fileInput.dispatchEvent(new Event('change', { bubbles: true }));
		console.log(`Successfully injected file: ${filename}`);
		return true;
	} catch (e) {
		console.error('File injection failed:', e);
		return false;
	}
}

const BLOCKLIST = ['name', 'email', 'phone', 'address', 'city', 'state', 'zip', 'title', 'company', 'url', 'linkedin', 'github', 'portfolio', 'salary', 'date'];

function scrapeSniperFields() {
	const fields = [];
	const textSelectors = [
		'input[type="text"]',
		'textarea',
		'input:not([type])',
		'textarea[data-automation-id]',
		'input[data-automation-id]'
	];

	document.querySelectorAll(textSelectors.join(', ')).forEach((el) => {
		if (el.offsetParent === null && el.type !== 'hidden') return;
		if (el.type === 'hidden' || el.readOnly || el.disabled) return;

		const question = extractQuestion(el);
		if (!question) return;

		const qLower = question.toLowerCase();
		const isBlocked = BLOCKLIST.some(block => qLower.includes(block));

		if (!isBlocked) {
			fields.push({ element: el, question });
		}
	});

	return fields;
}

// ─── Autofill pipeline helpers ───────────────────────────────────────────

function getAutofillButton() {
	return document.getElementById('jobagent-autofill-btn');
}

function showLoadingState() {
	const btn = getAutofillButton();
	btn.textContent = '🎯 Sniping answers...';
	btn.disabled = true;
}

function showSuccessState() {
	const btn = getAutofillButton();
	btn.textContent = '✅ Sniped!';
}

function showErrorState(message = '❌ Error') {
	const btn = getAutofillButton();
	btn.textContent = message;
}

function showNoFieldsState() {
	const btn = getAutofillButton();
	btn.textContent = '⚠️ No fields found';
	setTimeout(() => {
		btn.textContent = '\u{1FA84} Autofill with JobAgent';
		btn.disabled = false;
	}, 2000);
}

function resetButtonState(delay = 3000) {
	const btn = getAutofillButton();
	setTimeout(() => {
		btn.textContent = '\u{1FA84} Autofill with JobAgent';
		btn.disabled = false;
	}, delay);
}

function buildApiPayload(fields) {
	return {
		url: window.location.href,
		questions: fields.map(f => f.question),
	};
}

/**
 * Sends the payload to the backend sniper endpoint.
 * Returns parsed JSON answers, or null if job not found (404).
 * Throws on network/server errors.
 */
async function fetchAnswersFromBackend(payload) {
	const response = await fetch('http://localhost:8000/api/sniper/answer', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload),
	});

	if (response.status === 404) return null;
	if (!response.ok) throw new Error(`Server responded with ${response.status}`);

	return response.json();
}

/**
 * Maps backend answers to their corresponding DOM elements and injects values.
 * Handles resume file injection if resume_base64 is present.
 */
function applyAnswersToDOM(answers, scraped) {
	let filledCount = 0;
	const responseKeys = Object.keys(answers);

	scraped.forEach((field) => {
		const normQuestion = normalizeKey(field.question);
		const matchingKey = responseKeys.find(k => normalizeKey(k) === normQuestion);
		const answer = matchingKey ? answers[matchingKey] : null;

		if (!answer || answer === 'Could not generate answer.' || answer.startsWith('Error')) return;

		injectReactSafeValue(field.element, answer);
		filledCount++;
	});

	if (answers.resume_base64) {
		const fileInput = document.querySelector('input[type="file"], [data-automation-id="file-upload-input-ref"]');
		if (fileInput) {
			const injected = injectBase64File(
				fileInput,
				answers.resume_base64,
				answers.resume_filename || 'Resume.pdf'
			);
			if (injected) filledCount++;
		}
	}

	return filledCount;
}

// ─── Autofill click handler (flattened pipeline) ─────────────────────────

async function handleAutofillClick() {
	showLoadingState();

	const fields = scrapeFormFields();
	if (fields.length === 0) {
		showNoFieldsState();
		return;
	}

	const payload = buildApiPayload(fields);

	try {
		const answers = await fetchAnswersFromBackend(payload);

		if (answers === null) {
			showErrorState('❌ Job not found');
			showManualIdInput(payload.questions, fields);
			return;
		}

		applyAnswersToDOM(answers, fields);
		showSuccessState();
	} catch (error) {
		console.error('Sniper error:', error);
		showErrorState();
	}

	resetButtonState();
}

function showManualIdInput(questionsToAnswer, scraped) {
	if (document.getElementById('jobagent-manual-id-container')) return;

	const container = document.createElement('div');
	container.id = 'jobagent-manual-id-container';
	Object.assign(container.style, {
		position: 'fixed',
		bottom: '90px',
		right: '30px',
		zIndex: '2147483647',
		background: '#ffffff',
		padding: '16px',
		borderRadius: '12px',
		boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
		display: 'flex',
		flexDirection: 'column',
		gap: '8px',
		fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
	});

	const label = document.createElement('label');
	label.textContent = 'Job not found. Enter Job ID manually:';
	label.style.fontSize = '14px';
	label.style.fontWeight = '600';
	label.style.color = '#333';

	const input = document.createElement('input');
	input.type = 'text';
	input.placeholder = 'Job ID';
	input.style.padding = '8px';
	input.style.border = '1px solid #ccc';
	input.style.borderRadius = '4px';

	const submitBtn = document.createElement('button');
	submitBtn.textContent = 'Submit';
	Object.assign(submitBtn.style, {
		background: '#6366f1',
		color: 'white',
		border: 'none',
		padding: '8px 12px',
		borderRadius: '4px',
		cursor: 'pointer',
		fontWeight: '600'
	});

	submitBtn.addEventListener('click', async () => {
		const jobId = input.value.trim();
		if (jobId) {
			container.remove();
			await executeSniperWithPayload({ job_id: jobId, questions: questionsToAnswer }, scraped);
		}
	});

	container.appendChild(label);
	container.appendChild(input);
	container.appendChild(submitBtn);
	document.body.appendChild(container);
}

async function executeSniperWithPayload(payload, scraped) {
	showLoadingState();

	try {
		const answers = await fetchAnswersFromBackend(payload);
		if (!answers) throw new Error('Job not found');

		applyAnswersToDOM(answers, scraped);
		showSuccessState();
	} catch (error) {
		console.error('Sniper error:', error);
		showErrorState();
	}

	resetButtonState();
}

// ─── Type-aware value setter ─────────────────────────────────────────────

/**
 * Apply an LLM answer to a field based on its type.
 * Returns true if the value was successfully set.
 */
function applyAnswer(field, answer) {
	switch (field.type) {
		case 'select':
			return applySelectAnswer(field.element, answer);
		case 'radio':
			return applyRadioAnswer(field.elements || [field.element], answer);
		default:
			setNativeValue(field.element, answer);
			return true;
	}
}

/**
 * Set a <select> dropdown to the option whose text or value best matches the answer.
 */
function applySelectAnswer(selectEl, answer) {
	const answerLower = answer.toLowerCase().trim();

	// Pass 1: exact text match
	for (const opt of selectEl.options) {
		if (opt.textContent.trim().toLowerCase() === answerLower) {
			setNativeValue(selectEl, opt.value);
			return true;
		}
	}

	// Pass 2: option text contains the answer or vice versa
	for (const opt of selectEl.options) {
		const optText = opt.textContent.trim().toLowerCase();
		if (optText.includes(answerLower) || answerLower.includes(optText)) {
			setNativeValue(selectEl, opt.value);
			return true;
		}
	}

	// Pass 3: value attribute match
	for (const opt of selectEl.options) {
		if (opt.value.toLowerCase() === answerLower) {
			setNativeValue(selectEl, opt.value);
			return true;
		}
	}

	return false;
}

/**
 * Check the radio input whose label/value best matches the answer.
 */
function applyRadioAnswer(radios, answer) {
	const answerLower = answer.toLowerCase().trim();

	for (const radio of radios) {
		// Get the label text for this radio
		const labelText = getRadioLabel(radio).toLowerCase();

		const valueLower = (radio.value || '').toLowerCase();

		// Match against label text or value
		if (
			labelText === answerLower ||
			valueLower === answerLower ||
			labelText.includes(answerLower) ||
			answerLower.includes(labelText) ||
			valueLower.includes(answerLower) ||
			answerLower.includes(valueLower)
		) {
			radio.checked = true;
			radio.dispatchEvent(new Event('change', { bubbles: true }));
			radio.dispatchEvent(new Event('click', { bubbles: true }));
			return true;
		}
	}

	return false;
}

/**
 * Sets a value on an input/textarea in a way that React, Angular,
 * and other frameworks detect. Dispatches both 'input' and 'change'
 * events with bubbling enabled.
 */
function setNativeValue(element, value) {
	let prototype = window.HTMLInputElement.prototype;
	if (element instanceof HTMLTextAreaElement) {
		prototype = window.HTMLTextAreaElement.prototype;
	} else if (element instanceof HTMLSelectElement) {
		prototype = window.HTMLSelectElement.prototype;
	}

	const nativeInputValueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;

	if (nativeInputValueSetter) {
		nativeInputValueSetter.call(element, value);
	} else {
		element.value = value;
	}

	element.dispatchEvent(new Event('input', { bubbles: true }));
	element.dispatchEvent(new Event('change', { bubbles: true }));
}

// ─── Inject the "Save Job" button ─────────────────────────────────────────

function injectSaveJobButton() {
	if (document.getElementById('jobagent-savejob-btn')) return;

	const btn = document.createElement('button');
	btn.id = 'jobagent-savejob-btn';
	btn.textContent = '🎯 Save Job';
	Object.assign(btn.style, {
		position: 'fixed',
		bottom: '90px',
		right: '30px',
		zIndex: '2147483647',
		fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
		background: 'linear-gradient(135deg, #10b981, #059669)',
		color: '#ffffff',
		border: 'none',
		padding: '16px 24px',
		borderRadius: '24px',
		fontSize: '16px',
		fontWeight: '600',
		cursor: 'pointer',
		boxShadow: '0 8px 24px rgba(16, 185, 129, 0.5)',
		transition: 'transform 0.15s ease, box-shadow 0.15s ease',
		letterSpacing: '0.3px',
	});

	btn.addEventListener('mouseenter', () => {
		btn.style.transform = 'scale(1.05)';
		btn.style.boxShadow = '0 12px 32px rgba(16, 185, 129, 0.6)';
	});
	btn.addEventListener('mouseleave', () => {
		btn.style.transform = 'scale(1)';
		btn.style.boxShadow = '0 8px 24px rgba(16, 185, 129, 0.5)';
	});

	document.body.appendChild(btn);

	btn.addEventListener('click', handleSaveJobClick);
}

async function handleSaveJobClick() {
	const btn = document.getElementById('jobagent-savejob-btn');
	const originalText = btn.textContent;
	btn.textContent = '⏳ Saving...';
	btn.disabled = true;

	const jobDescription = typeof scrapeJobDescription === 'function' ? scrapeJobDescription() : '';
	const title = document.title || 'Unknown Title';
	const company = document.title.split('-')[0].trim() || 'Unknown Company';

	const payload = {
		title: title,
		company: company,
		url: window.location.href,
		job_description: jobDescription
	};

	try {
		const res = await fetch('http://localhost:8000/track_job', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload)
		});
		if (res.ok) {
			btn.textContent = '✅ Saved!';
			btn.style.background = 'linear-gradient(135deg, #059669, #047857)';
		} else {
			btn.textContent = '❌ Failed';
		}
	} catch (e) {
		console.error('Save Job error:', e);
		btn.textContent = '❌ Error';
	}

	setTimeout(() => {
		btn.textContent = originalText;
		btn.disabled = false;
		btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
	}, 3000);
}

// ─── Inject the "Mark Applied" button ─────────────────────────────────────

function injectMarkAppliedButton() {
	if (document.getElementById('jobagent-markapplied-btn')) return;

	const btn = document.createElement('button');
	btn.id = 'jobagent-markapplied-btn';
	btn.textContent = '🏁 Mark Applied';
	Object.assign(btn.style, {
		position: 'fixed',
		bottom: '150px',
		right: '30px',
		zIndex: '2147483647',
		fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
		background: 'linear-gradient(135deg, #f59e0b, #d97706)',
		color: '#ffffff',
		border: 'none',
		padding: '16px 24px',
		borderRadius: '24px',
		fontSize: '16px',
		fontWeight: '600',
		cursor: 'pointer',
		boxShadow: '0 8px 24px rgba(245, 158, 11, 0.5)',
		transition: 'transform 0.15s ease, box-shadow 0.15s ease',
		letterSpacing: '0.3px',
	});

	btn.addEventListener('mouseenter', () => {
		btn.style.transform = 'scale(1.05)';
		btn.style.boxShadow = '0 12px 32px rgba(245, 158, 11, 0.6)';
	});
	btn.addEventListener('mouseleave', () => {
		btn.style.transform = 'scale(1)';
		btn.style.boxShadow = '0 8px 24px rgba(245, 158, 11, 0.5)';
	});

	document.body.appendChild(btn);

	btn.addEventListener('click', handleMarkAppliedClick);
}

async function handleMarkAppliedClick() {
	const btn = document.getElementById('jobagent-markapplied-btn');
	const originalText = btn.textContent;
	btn.textContent = '⏳ Completing...';
	btn.disabled = true;

	try {
		const res = await fetch('http://localhost:8000/api/sniper/complete', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ url: window.location.href })
		});
		if (res.ok) {
			btn.textContent = '🎉 Done!';
			btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
		} else {
			btn.textContent = '❌ Failed';
		}
	} catch (e) {
		console.error('Mark Applied error:', e);
		btn.textContent = '❌ Error';
	}

	setTimeout(() => {
		btn.textContent = originalText;
		btn.disabled = false;
		btn.style.background = 'linear-gradient(135deg, #f59e0b, #d97706)';
	}, 3000);
}
