// ─── extension/content.js — Floating Action Menu + SPA-Safe + State Persistent ──
// §1: Utility Helpers
// §2: Inline Suggestion UI (decorates textareas in-place — NOT moved to FAM)
// §3: State Engine (backend truth + chrome.storage.local cache)
// §4: Floating Action Menu (FAM) — collapsible panel
// §5: Action Handlers (Track, Tailor, Mark Applied)
// §6: SPA-Safe MutationObserver + Initialization
// ─────────────────────────────────────────────────────────────────────────────

// ═══════════════════════════════════════════════════════════════════════════
// §1  UTILITY HELPERS
// ═══════════════════════════════════════════════════════════════════════════

const normalizeKey = (str) => str ? str.toLowerCase().replace(/[^a-z0-9]/g, '') : '';

function extractQuestion(el) {
	let question = '';
	if (el.id) {
		const label = document.querySelector(`label[for="${el.id}"]`);
		if (label) question = label.textContent.trim();
	}
	if (!question && el.getAttribute('aria-labelledby')) {
		const labelEl = document.getElementById(el.getAttribute('aria-labelledby'));
		if (labelEl) question = labelEl.textContent.trim();
	}
	if (!question && el.getAttribute('aria-label')) {
		question = el.getAttribute('aria-label').trim();
	}
	if (!question && el.hasAttribute('data-automation-id')) {
		const autoId = el.getAttribute('data-automation-id');
		const relatedLabel = document.querySelector(`[data-automation-id="label-${autoId}"], [data-automation-id*="${autoId}"] label`);
		if (relatedLabel) {
			question = relatedLabel.textContent.trim();
		} else {
			const parts = autoId.split('_');
			const lastPart = parts[parts.length - 1] || '';
			question = lastPart.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase()).trim();
		}
	}
	if (!question && el.placeholder) question = el.placeholder.trim();
	if (!question) {
		const parent = el.closest('.form-group, .field, fieldset, [class*="field"], [class*="question"]');
		if (parent) {
			const lbl = parent.querySelector('label, legend, [class*="label"]');
			if (lbl) question = lbl.textContent.trim();
		}
	}
	if (!question) {
		let cur = el.parentElement;
		while (cur && cur !== document.body && !question) {
			if (cur.className && typeof cur.className === 'string' &&
				(cur.className.includes('css-') || cur.className.includes('field') || cur.className.includes('container'))) {
				const lbl = cur.querySelector('[class*="label"], [id*="label"], label');
				if (lbl && lbl !== el && !lbl.contains(el)) question = lbl.textContent.trim();
			}
			cur = cur.parentElement;
		}
	}
	if (!question || question.toLowerCase().includes('upload a file')) {
		const group = el.closest('div[role="group"], [data-automation-id*="formField"], .form-group');
		if (group) {
			const h3 = group.querySelector('h3');
			if (h3) {
				const st = h3.textContent.trim();
				question = question ? `${st} - ${question}` : st;
			}
		}
	}
	if (!question && el.name) question = el.name.replace(/[_\-]/g, ' ').trim();
	return question;
}

function injectReactSafeValue(element, value) {
	try {
		const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
		const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;

		if (element.tagName === 'TEXTAREA' && nativeTextAreaValueSetter) {
			nativeTextAreaValueSetter.call(element, value);
		} else if (element.tagName === 'INPUT' && nativeInputValueSetter) {
			nativeInputValueSetter.call(element, value);
		} else {
			element.value = value;
		}
	} catch (e) {
		element.value = value;
	}

	element.dispatchEvent(new Event('input', { bubbles: true }));
	element.dispatchEvent(new Event('change', { bubbles: true }));
}

function injectStoredResume(fileInput, base64String, filename) {
	try {
		const bc = atob(base64String);
		const bn = new Array(bc.length);
		for (let i = 0; i < bc.length; i++) bn[i] = bc.charCodeAt(i);
		const ba = new Uint8Array(bn);
		const blob = new Blob([ba], { type: 'application/pdf' });
		const file = new File([blob], filename, { type: 'application/pdf' });
		const dt = new DataTransfer();
		dt.items.add(file);
		fileInput.files = dt.files;
		fileInput.dispatchEvent(new Event('change', { bubbles: true }));
		return true;
	} catch (e) {
		console.error('[JobAgent] File injection failed:', e);
		return false;
	}
}

function sendBgMessage(action, payload) {
	return new Promise(resolve => {
		chrome.runtime.sendMessage({ action, payload }, resolve);
	});
}

// ── Toast Notification System ──
function showToast(message, type = 'success', duration = 3500) {
	const TOAST_ID = 'jobagent-toast';
	let existing = document.getElementById(TOAST_ID);
	if (existing) existing.remove();

	const colors = {
		success: { bg: '#00ff00', fg: '#000' },
		error:   { bg: '#ff3333', fg: '#fff' },
		info:    { bg: '#fff', fg: '#000' },
	};
	const c = colors[type] || colors.info;

	const toast = document.createElement('div');
	toast.id = TOAST_ID;
	Object.assign(toast.style, {
		position: 'fixed', bottom: '24px', right: '24px', zIndex: '9999999',
		padding: '12px 18px', background: c.bg, color: c.fg,
		fontFamily: 'monospace', fontSize: '13px', fontWeight: 'bold',
		border: '2px solid #000', boxShadow: '4px 4px 0px #000',
		maxWidth: '320px', lineHeight: '1.4',
		transform: 'translateY(80px)', opacity: '0',
		transition: 'transform 0.25s ease, opacity 0.25s ease',
	});
	toast.textContent = message;
	document.body.appendChild(toast);

	// Slide in
	requestAnimationFrame(() => {
		toast.style.transform = 'translateY(0)';
		toast.style.opacity = '1';
	});

	// Auto-dismiss
	setTimeout(() => {
		toast.style.transform = 'translateY(80px)';
		toast.style.opacity = '0';
		setTimeout(() => toast.remove(), 300);
	}, duration);
}

// ── Progress Bar Helper ──
function showProgress(text, fraction = 0) {
	const bar = document.getElementById('jobagent-fam-progress');
	const label = document.getElementById('jobagent-fam-progress-label');
	const fill = document.getElementById('jobagent-fam-progress-fill');
	if (!bar || !label || !fill) return;
	bar.style.display = 'block';
	label.textContent = text;
	fill.style.width = Math.round(fraction * 100) + '%';
}

function hideProgress() {
	const bar = document.getElementById('jobagent-fam-progress');
	if (bar) bar.style.display = 'none';
}

function extractPageTitle() {
	// Generic words that are page sections, NOT real job titles
	const GARBAGE = new Set(['careers', 'career', 'jobs', 'job boards', 'career opportunities',
		'hiring', 'opportunities', 'internship', 'apply', 'position', 'openings',
		'home', 'search', 'results', 'welcome', 'about']);

	const _isGarbage = (s) => !s || GARBAGE.has(s.toLowerCase().trim());

	// 1. ATS-specific selectors (most reliable)
	const atsSelectors = [
		'[data-automation-id="jobPostingHeader"]',  // Workday
		'.app-title',                                // Greenhouse
		'.posting-headline h2',                      // Lever
		'.job-title',                                // SmartRecruiters / generic
		'.jv-job-detail-header h1',                  // Jobvite
		'[class*="jobTitle"]',                       // Generic ATS
		'[class*="job-title"]',                      // Generic ATS
	];
	for (const sel of atsSelectors) {
		try {
			const el = document.querySelector(sel);
			if (el && el.textContent.trim().length > 3 && !_isGarbage(el.textContent.trim())) {
				return el.textContent.trim();
			}
		} catch { /* skip invalid selectors */ }
	}

	// 2. H1 within main content area (skip nav/header h1s)
	const mainH1 = document.querySelector('main h1, article h1, [role="main"] h1');
	if (mainH1 && mainH1.textContent.trim().length > 3 && !_isGarbage(mainH1.textContent.trim())) {
		return mainH1.textContent.trim();
	}

	// 3. Any h1 on the page
	const h1 = document.querySelector('h1');
	if (h1 && h1.textContent.trim().length > 3 && !_isGarbage(h1.textContent.trim())) {
		return h1.textContent.trim();
	}

	// 4. OpenGraph title
	const og = document.querySelector('meta[property="og:title"]');
	if (og && og.content.trim().length > 3 && !_isGarbage(og.content.trim())) {
		return og.content.trim();
	}

	// 5. Document title — take the first meaningful segment
	const parts = document.title.split(/[|\-—–]/);
	for (const p of parts) {
		const t = p.trim();
		if (t.length > 3 && !_isGarbage(t)) return t;
	}
	return document.title.trim() || 'Unknown Title';
}

function extractCompanyName() {
	// Generic words that are page sections, NOT real company names
	const GARBAGE = new Set(['careers', 'career', 'jobs', 'job-boards', 'job boards',
		'career opportunities', 'hiring', 'opportunities', 'internship', 'apply',
		'position', 'openings', 'home', 'search', 'results', 'welcome', 'about']);

	const _isGarbage = (s) => !s || GARBAGE.has(s.toLowerCase().trim());

	// 1. ATS-specific selectors (most reliable)
	const atsSelectors = [
		'[data-automation-id="company"]',            // Workday
		'.company-name',                             // Greenhouse
		'[class*="company-name"]',                   // Generic ATS
		'.posting-categories .sort-by-team',         // Lever
		'[itemprop="hiringOrganization"] [itemprop="name"]', // Schema.org
	];
	for (const sel of atsSelectors) {
		try {
			const el = document.querySelector(sel);
			if (el && el.textContent.trim().length > 1 && !_isGarbage(el.textContent.trim())) {
				return el.textContent.trim();
			}
		} catch { /* skip invalid selectors */ }
	}

	// 2. OpenGraph site_name (very reliable when present)
	const og = document.querySelector('meta[property="og:site_name"]');
	if (og && og.content.trim().length > 1 && !_isGarbage(og.content.trim())) {
		return og.content.trim();
	}

	// 3. Document title — company is often the LAST segment after | or -
	const parts = document.title.split(/[|\-—–]/);
	if (parts.length > 1) {
		const lastPart = parts[parts.length - 1].trim();
		if (lastPart.length > 1 && !_isGarbage(lastPart)) return lastPart;
	}

	// 4. Hostname fallback (e.g., careers.netapp.com → Netapp)
	try {
		const host = window.location.hostname.replace('www.', '');
		const parts = host.split('.');
		// Skip common subdomains like 'careers', 'jobs', 'apply'
		const meaningful = parts.find(p => !GARBAGE.has(p) && p.length > 2 && !['com', 'org', 'net', 'io', 'co'].includes(p));
		if (meaningful) return meaningful.charAt(0).toUpperCase() + meaningful.slice(1);
		// Fallback to second-level domain
		const sld = parts.length >= 2 ? parts[parts.length - 2] : parts[0];
		return sld.charAt(0).toUpperCase() + sld.slice(1);
	} catch { return 'Unknown'; }
}

// ═══════════════════════════════════════════════════════════════════════════
// §2  INLINE SUGGESTION UI  (stays in-place next to textareas — NOT in FAM)
// ═══════════════════════════════════════════════════════════════════════════

const BLOCKLIST = ['name', 'email', 'phone', 'address', 'city', 'state', 'zip',
	'title', 'company', 'url', 'linkedin', 'github', 'portfolio', 'salary', 'date'];
const TARGET_KEYWORDS = /why|describe|experience with|please explain/i;

function detectAndDecorateFields() {
	const sel = 'textarea, textarea[data-automation-id], input[type="text"], input:not([type]), input[data-automation-id]';
	document.querySelectorAll(sel).forEach((el) => {
		if (el.dataset.sniperDecorated) return;
		if (el.offsetParent === null && el.type !== 'hidden') return;
		if (el.type === 'hidden' || el.readOnly || el.disabled) return;
		const question = extractQuestion(el);
		if (!question) return;
		const qL = question.toLowerCase();
		if (BLOCKLIST.some(b => qL.includes(b))) return;
		if (el.tagName.toLowerCase() === 'textarea' || TARGET_KEYWORDS.test(qL)) {
			el.dataset.sniperDecorated = 'true';
			injectSuggestionButton(el, question);
		}
	});
}

function injectSuggestionButton(inputEl, question) {
	const btn = document.createElement('button');
	btn.textContent = '✨ Suggest Answer';
	btn.type = 'button';
	btn.dataset.jobagentSuggestBtn = 'true';
	Object.assign(btn.style, {
		display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
		marginTop: '6px', marginBottom: '12px', padding: '8px 16px',
		fontSize: '12px', fontWeight: 'bold', color: '#000',
		background: '#fff',
		border: '2px solid #000', borderRadius: '0', cursor: 'pointer',
		boxShadow: '4px 4px 0px #000', transition: 'all 0.1s ease',
		fontFamily: 'monospace'
	});
	btn.addEventListener('mouseenter', () => { btn.style.transform = 'translate(2px, 2px)'; btn.style.boxShadow = '2px 2px 0px #000'; btn.style.background = '#000'; btn.style.color = '#fff'; });
	btn.addEventListener('mouseleave', () => { btn.style.transform = 'translate(0, 0)'; btn.style.boxShadow = '4px 4px 0px #000'; btn.style.background = '#fff'; btn.style.color = '#000'; });
	btn.addEventListener('click', async (e) => { e.preventDefault(); await handleSuggestClick(btn, inputEl, question); });
	if (inputEl.nextSibling) inputEl.parentNode.insertBefore(btn, inputEl.nextSibling);
	else inputEl.parentNode.appendChild(btn);
}

async function handleSuggestClick(btn, inputEl, question) {
	const orig = btn.textContent;
	btn.textContent = '⏳ Generating...'; btn.disabled = true;
	const payload = { url: window.location.href, questions: [question] };
	try {
		let res = await sendBgMessage('sniperAnswer', payload);
		if (res && res.status === 404) {
			const mid = prompt('Job not found. Enter Job ID:');
			if (mid) { payload.job_id = mid; res = await sendBgMessage('sniperAnswer', payload); }
			else { btn.textContent = '❌ Not Found'; setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000); return; }
		}
		if (res && res.status === 200 && res.data) {
			const answers = res.data;
			const nq = normalizeKey(question);
			const validKeys = Object.keys(answers).filter(k => k !== 'resume_base64' && k !== 'resume_filename');
			const mk = validKeys.find(k => normalizeKey(k) === nq) || validKeys[0];
			const ans = mk ? answers[mk] : null;
			if (ans && !ans.startsWith('Error') && ans !== 'Could not generate answer.') {
				injectReactSafeValue(inputEl, ans);
				btn.textContent = '✅ Suggested';
				if (answers.resume_base64 && !window._jaResumeInjected) {
					const fi = document.querySelector('input[type="file"], [data-automation-id="file-upload-input-ref"]');
					if (fi) { injectStoredResume(fi, answers.resume_base64, answers.resume_filename || 'Resume.pdf'); window._jaResumeInjected = true; }
				}
			} else { btn.textContent = '❌ Failed'; }
		} else { btn.textContent = '❌ Error'; }
	} catch (e) { console.error('[JobAgent] Suggest error:', e); btn.textContent = '❌ Error'; }
	setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 3000);
}

// ═══════════════════════════════════════════════════════════════════════════
// §3  STATE ENGINE  — backend truth + chrome.storage.local cache
// ═══════════════════════════════════════════════════════════════════════════

// Possible UI states for the FAM:  untracked → tracked → tailored → applied
const STATE = { UNTRACKED: 'untracked', TRACKED: 'tracked', TAILORED: 'tailored', PREVIEWED: 'previewed', APPLIED: 'applied' };

window._ja = {
	state: STATE.UNTRACKED,
	job: null,          // {job_id, score, status, reason, ...}
	pendingResume: null, // {base64, filename}
	pendingCoverLetter: null, // {base64, filename, url}
	resumeInjected: false,
};

/**
 * Determine the correct UI state from two sources:
 *   1. Backend truth (scoutCheckUrl → job row)
 *   2. chrome.storage.local cache (instant on SPA re-inject)
 */
async function resolveState() {
	// ── Backend truth via scoutCheckUrl ──
	try {
		const res = await sendBgMessage('scoutCheckUrl', { url: window.location.href });
		if (res && res.status === 200 && res.data && res.data.tracked) {
			const job = res.data.job;
			window._ja.job = job;

			const status = (job.status || '').toLowerCase();
			if (status === 'applied') {
				window._ja.state = STATE.APPLIED;
			} else if (status === 'tailored' || job.resume_path) {
				window._ja.state = STATE.TAILORED;
			} else {
				window._ja.state = STATE.TRACKED;
			}
			return;
		}
	} catch (e) { console.error('[JobAgent] resolveState backend error:', e); }

	// ── Default: untracked ──
	window._ja.state = STATE.UNTRACKED;
}

// ═══════════════════════════════════════════════════════════════════════════
// §4  FLOATING ACTION MENU  — collapsible panel, docked right-center
// ═══════════════════════════════════════════════════════════════════════════

const FAM_ID = 'jobagent-fam-root';
let _famObserverPaused = false; // prevents re-injection loops

function buildFAM() {
	if (document.getElementById(FAM_ID)) return; // already exists

	// ── Root Container ──
	const root = document.createElement('div');
	root.id = FAM_ID;
	Object.assign(root.style, {
		position: 'fixed', right: '0', top: '30%',
		zIndex: '999999', display: 'flex', flexDirection: 'row',
		fontFamily: 'monospace',
		transition: 'transform 0.25s ease',
	});

	// ── Toggle Tab ──
	const toggle = document.createElement('button');
	toggle.id = 'jobagent-fam-toggle';
	toggle.textContent = 'AGENT';
	toggle.type = 'button';
	Object.assign(toggle.style, {
		width: 'auto', height: 'auto', border: '2px solid #000', cursor: 'pointer',
		background: '#00ff00', padding: '10px',
		color: '#000', fontSize: '14px', borderRadius: '0', fontWeight: 'bold',
		display: 'flex', alignItems: 'center', justifyContent: 'center',
		boxShadow: '-4px 4px 0px #000',
		transition: 'all 0.1s ease',
		alignSelf: 'flex-start',
		writingMode: 'vertical-rl',
		textOrientation: 'mixed'
	});

	// ── Panel ──
	const panel = document.createElement('div');
	panel.id = 'jobagent-fam-panel';
	Object.assign(panel.style, {
		width: '0px', background: '#f4f4f0', border: 'none',
		borderRadius: '0', padding: '14px 0',
		display: 'flex', flexDirection: 'column', gap: '12px',
		boxShadow: '-6px 6px 0px #000',
		transition: 'width 0.25s ease, padding 0.25s ease, opacity 0.25s ease',
		overflow: 'hidden',
		opacity: '0',
	});

	let panelOpen = false;
	toggle.addEventListener('click', () => {
		panelOpen = !panelOpen;
		if (panelOpen) {
			panel.style.width = '240px';
			panel.style.padding = '16px 16px';
			panel.style.border = '2px solid #000';
			panel.style.opacity = '1';
		} else {
			panel.style.width = '0px';
			panel.style.padding = '14px 0';
			panel.style.border = 'none';
			panel.style.opacity = '0';
		}
	});

	// ── Status Badge ──
	const badge = document.createElement('div');
	badge.id = 'jobagent-fam-badge';
	Object.assign(badge.style, {
		fontSize: '12px', color: '#000', textAlign: 'center',
		padding: '4px 0 8px 0', letterSpacing: '0px',
		borderBottom: '2px solid #000',
		marginBottom: '8px', fontWeight: 'bold', textTransform: 'uppercase'
	});
	badge.textContent = 'JobAgent';
	panel.appendChild(badge);

	// ── Progress Bar ──
	const progressWrap = document.createElement('div');
	progressWrap.id = 'jobagent-fam-progress';
	Object.assign(progressWrap.style, {
		display: 'none', marginBottom: '8px',
	});

	const progressLabel = document.createElement('div');
	progressLabel.id = 'jobagent-fam-progress-label';
	Object.assign(progressLabel.style, {
		fontSize: '11px', color: '#000', marginBottom: '4px',
		fontWeight: 'bold', fontFamily: 'monospace',
	});
	progressLabel.textContent = 'Working...';

	const progressTrack = document.createElement('div');
	Object.assign(progressTrack.style, {
		width: '100%', height: '6px', background: '#ddd',
		border: '1px solid #000', overflow: 'hidden',
	});

	const progressFill = document.createElement('div');
	progressFill.id = 'jobagent-fam-progress-fill';
	Object.assign(progressFill.style, {
		width: '0%', height: '100%', background: '#00ff00',
		transition: 'width 0.4s ease',
	});
	progressTrack.appendChild(progressFill);
	progressWrap.appendChild(progressLabel);
	progressWrap.appendChild(progressTrack);
	panel.appendChild(progressWrap);

	// ── Action Buttons Container ──
	const actionsDiv = document.createElement('div');
	actionsDiv.id = 'jobagent-fam-actions';
	actionsDiv.style.display = 'flex';
	actionsDiv.style.flexDirection = 'column';
	actionsDiv.style.gap = '8px';
	panel.appendChild(actionsDiv);

	root.appendChild(toggle);
	root.appendChild(panel);

	_famObserverPaused = true;
	document.body.appendChild(root);
	requestAnimationFrame(() => { _famObserverPaused = false; });

	renderFAMActions();
}

/** Creates a styled button for the FAM panel */
function createFAMButton(id, text, isPrimary = false) {
	const btn = document.createElement('button');
	btn.id = id;
	btn.textContent = text;
	btn.type = 'button';

	const bg = isPrimary ? '#00ff00' : '#fff';
	const fg = '#000';

	Object.assign(btn.style, {
		width: '100%', border: '2px solid #000', cursor: 'pointer',
		padding: '12px 16px', borderRadius: '0',
		fontSize: '14px', fontWeight: 'bold', color: fg,
		background: bg,
		boxShadow: '4px 4px 0px #000',
		transition: 'all 0.1s ease',
		fontFamily: 'monospace', letterSpacing: '0',
		textTransform: 'uppercase'
	});
	btn.addEventListener('mouseenter', () => {
		if (isPrimary) {
			btn.style.transform = 'translate(2px, 2px)';
			btn.style.boxShadow = '2px 2px 0px #000';
		} else {
			btn.style.background = '#000';
			btn.style.color = '#fff';
		}
	});
	btn.addEventListener('mouseleave', () => {
		if (isPrimary) {
			btn.style.transform = 'translate(0, 0)';
			btn.style.boxShadow = '4px 4px 0px #000';
		} else {
			btn.style.background = '#fff';
			btn.style.color = '#000';
		}
	});
	return btn;
}

/**
 * Render the correct set of buttons inside the FAM based on window._ja.state.
 */
function renderFAMActions() {
	const container = document.getElementById('jobagent-fam-actions');
	if (!container) return;

	// Clear existing buttons
	container.innerHTML = '';

	const state = window._ja.state;

	// ── UNTRACKED: Show "Track & Score" ──
	if (state === STATE.UNTRACKED) {
		const btn = createFAMButton('ja-track', '📥 Track & Score', true);
		btn.addEventListener('click', handleTrackClick);
		container.appendChild(btn);
	}

	// ── TRACKED: Show "Tailor & Preview" ──
	if (state === STATE.TRACKED) {
		const btn = createFAMButton('ja-tailor', '📄 Tailor Resume', true);
		btn.addEventListener('click', handleTailorClick);
		container.appendChild(btn);

		const btnCover = createFAMButton('ja-cover-generate', '✍️ Generate Cover Letter', false);
		btnCover.addEventListener('click', handleCoverLetterClick);
		container.appendChild(btnCover);
	}

	// ── TAILORED / PREVIEWED: Show "Preview" and "Inject" ──
	if (state === STATE.TAILORED || state === STATE.PREVIEWED) {
		const btnPreview = createFAMButton('ja-preview-btn', '🔍 Preview PDF', false);
		btnPreview.addEventListener('click', async () => {
			if (await ensureResumeLoaded()) {
				window.open(window._ja.pendingResume.url, '_blank');
			}
		});
		container.appendChild(btnPreview);

		const btnCover = createFAMButton('ja-cover-preview-btn', '✍️ Cover Letter', false);
		btnCover.addEventListener('click', handleCoverLetterClick);
		container.appendChild(btnCover);

		const btnInject = createFAMButton('ja-inject-btn', '💉 Inject & Apply', true);
		btnInject.addEventListener('click', () => handleInjectClick(btnInject));
		container.appendChild(btnInject);
	}

	// ── APPLIED: Show "Done" (disabled) ──
	if (state === STATE.APPLIED) {
		const btn = createFAMButton('ja-done', '✅ Applied', false);
		btn.disabled = true;
		btn.style.cursor = 'default';
		btn.style.opacity = '0.5';
		btn.style.boxShadow = 'none';
		btn.style.transform = 'none';
		btn.style.borderStyle = 'dashed';
		container.appendChild(btn);
	}

	// ── Always show "Mark Applied" as a secondary if tracked but not yet applied ──
	if (state === STATE.TRACKED || state === STATE.TAILORED || state === STATE.PREVIEWED) {
		// Only add if not already the primary
		if (state === STATE.TRACKED || state === STATE.PREVIEWED || state === STATE.TAILORED) {
			const btn2 = createFAMButton('ja-applied-secondary', '🏁 Mark Applied', false);
			Object.assign(btn2.style, {
				padding: '8px 10px',
				fontSize: '12px'
			});
			btn2.addEventListener('click', handleMarkAppliedClick);
			container.appendChild(btn2);
		}
	}

	// ── Update badge with color-coded score ──
	const badge = document.getElementById('jobagent-fam-badge');
	if (badge) {
		const job = window._ja.job;
		if (job && job.job_id) {
			const s = parseInt(job.score || 0);
			const scoreColor = s >= 7 ? '#00ff00' : s >= 5 ? '#ffcc00' : '#ff3333';
			badge.innerHTML = `JOBAGENT <span style="color:${scoreColor};font-size:14px;">${s}/10</span>`;
			// Click badge to see reasoning
			if (job.reason && !badge.dataset.reasonBound) {
				badge.style.cursor = 'pointer';
				badge.addEventListener('click', () => {
					showToast(job.reason.substring(0, 200), 'info', 6000);
				});
				badge.dataset.reasonBound = 'true';
			}
		}
	}
}

// ═══════════════════════════════════════════════════════════════════════════
// §5  ACTION HANDLERS
// ═══════════════════════════════════════════════════════════════════════════

// ── Track & Score ──

async function handleTrackClick() {
	const btn = document.getElementById('ja-track');
	if (!btn) return;
	btn.textContent = '⏳ Scoring...'; btn.disabled = true;
	showProgress('Analyzing job description...', 0.3);

	const payload = {
		url: window.location.href,
		title: extractPageTitle(),
		company: extractCompanyName(),
		page_text: document.body.innerText.substring(0, 15000),
	};

	try {
		showProgress('Scoring with LLM...', 0.6);
		const res = await sendBgMessage('scoutOrganic', payload);
		showProgress('Done!', 1.0);

		if (res && res.status === 200 && res.data) {
			const d = res.data;
			window._ja.job = { job_id: d.job_id, score: d.score, status: d.job_status, reason: d.reason };

			if (d.job_status === 'shortlisted') {
				showToast(`✅ Tracked! Score: ${d.score}/10`, 'success');
				btn.textContent = `✅ ${d.score}/10`;
				btn.style.background = '#00ff00';
			} else {
				showToast(`⚠️ Score: ${d.score}/10 — ${d.job_status}`, 'error', 5000);
				btn.textContent = `⚠️ ${d.score}/10`;
				btn.style.background = '#ff3333';
				btn.style.color = '#fff';
			}

			setTimeout(() => {
				hideProgress();
				window._ja.state = STATE.TRACKED;
				renderFAMActions();
			}, 1500);
		} else {
			hideProgress();
			showToast('❌ Failed to track job', 'error');
			btn.textContent = '❌ Error';
			setTimeout(() => { btn.textContent = '📥 Track & Score'; btn.disabled = false; }, 3000);
		}
	} catch (e) {
		console.error('[JobAgent] Track error:', e);
		hideProgress();
		showToast('❌ Connection error — is the backend running?', 'error', 5000);
		btn.textContent = '❌ Error';
		setTimeout(() => { btn.textContent = '📥 Track & Score'; btn.disabled = false; }, 3000);
	}
}

// ── Tailor & Inject Resume ──

async function handleTailorClick() {
	const btn = document.getElementById('ja-tailor');
	if (!btn) return;
	btn.textContent = '⏳ Tailoring...'; btn.disabled = true;

	// Phased progress animation
	const phases = [
		{ text: '🔍 Reading job description...', frac: 0.15 },
		{ text: '🧠 Extracting keywords...', frac: 0.30 },
		{ text: '✍️ Generating tailored content...', frac: 0.55 },
		{ text: '📐 Ranking projects...', frac: 0.70 },
		{ text: '📄 Compiling PDF...', frac: 0.90 },
	];
	let phaseIdx = 0;
	showProgress(phases[0].text, phases[0].frac);

	// Advance phases on a timer (the actual pipeline is server-side)
	const phaseTimer = setInterval(() => {
		phaseIdx++;
		if (phaseIdx < phases.length) {
			showProgress(phases[phaseIdx].text, phases[phaseIdx].frac);
		}
	}, 2000);

	const payload = { url: window.location.href };
	if (window._ja.job?.job_id) payload.job_id = window._ja.job.job_id;

	try {
		const res = await sendBgMessage('tailorGenerate', payload);
		clearInterval(phaseTimer);

		if (res && res.status === 200 && res.data) {
			showProgress('✅ Done!', 1.0);
			const { resume_base64, filename, job_id } = res.data;

			const blob = base64ToBlob(resume_base64);
			const url = URL.createObjectURL(blob);
			window._ja.pendingResume = { base64: resume_base64, filename: filename || 'Resume.pdf', url: url };

			showToast('✅ Resume tailored and ready!', 'success');

			const jid = job_id || window._ja.job?.job_id;
			if (jid) {
				try { chrome.storage.local.set({ [`tailored_${jid}`]: true }); } catch (e) { /* ok */ }
			}

			setTimeout(() => {
				hideProgress();
				window._ja.state = STATE.PREVIEWED;
				renderFAMActions();
			}, 800);
		} else if (res && res.status === 404) {
			hideProgress();
			showToast('❌ Job not found — track it first', 'error');
			btn.textContent = '📄 Tailor Resume'; btn.disabled = false;
		} else {
			hideProgress();
			showToast('❌ Tailoring failed', 'error');
			btn.textContent = '📄 Tailor Resume'; btn.disabled = false;
		}
	} catch (e) {
		clearInterval(phaseTimer);
		hideProgress();
		console.error('[JobAgent] Tailor error:', e);
		showToast('❌ Connection error — is the backend running?', 'error', 5000);
		btn.textContent = '📄 Tailor Resume'; btn.disabled = false;
	}
}

async function handleCoverLetterClick() {
	const btn = document.getElementById('ja-cover-generate') || document.getElementById('ja-cover-preview-btn');
	if (!btn) return;

	const originalText = btn.textContent;
	btn.textContent = '⏳ Writing Cover Letter...';
	btn.disabled = true;

	try {
		const ready = await ensureCoverLetterLoaded(btn, originalText);
		if (!ready) return;

		window.open(window._ja.pendingCoverLetter.url, '_blank');

		btn.textContent = '✅ Cover Letter Ready';
		btn.style.background = '#fff';
		btn.style.color = '#000';

		setTimeout(() => {
			btn.textContent = originalText;
			btn.disabled = false;
		}, 1500);
	} catch (e) {
		console.error('[JobAgent] Cover Letter error:', e);
		btn.textContent = '❌ Error';
		setTimeout(() => {
			btn.textContent = originalText;
			btn.disabled = false;
		}, 2000);
	}
}

/** Helper to convert base64 to Blob */
function base64ToBlob(base64, type = 'application/pdf') {
	const bc = atob(base64);
	const bn = new Array(bc.length);
	for (let i = 0; i < bc.length; i++) bn[i] = bc.charCodeAt(i);
	const ba = new Uint8Array(bn);
	return new Blob([ba], { type });
}

/**
 * Ensures the cover letter base64/URL is loaded in memory.
 * This flow is intentionally separate from resume generation.
 */
async function ensureCoverLetterLoaded(targetBtn = null, fallbackText = '') {
	if (window._ja.pendingCoverLetter && (window._ja.pendingCoverLetter.base64 || window._ja.pendingCoverLetter.url)) {
		if (targetBtn) { targetBtn.disabled = false; }
		return true;
	}

	const btn = targetBtn || document.getElementById('ja-cover-generate') || document.getElementById('ja-cover-preview-btn');
	const origText = fallbackText || (btn ? btn.textContent : '✍️ Cover Letter');
	if (btn) {
		btn.textContent = '⏳ Loading...';
		btn.disabled = true;
	}

	try {
		const payload = { url: window.location.href };
		if (window._ja.job?.job_id) payload.job_id = window._ja.job.job_id;

		const res = await sendBgMessage('coverLetterGenerate', payload);
		if (res && res.status === 200 && res.data) {
			const { cover_letter_base64, filename } = res.data;
			const blob = base64ToBlob(cover_letter_base64, 'text/markdown;charset=utf-8');
			const url = URL.createObjectURL(blob);

			if (window._ja.pendingCoverLetter?.url) {
				try { URL.revokeObjectURL(window._ja.pendingCoverLetter.url); } catch (e) { /* noop */ }
			}

			window._ja.pendingCoverLetter = {
				base64: cover_letter_base64,
				filename: filename || 'cover letter.md',
				url,
			};

			if (btn) {
				btn.textContent = origText;
				btn.disabled = false;
			}
			return true;
		}
	} catch (e) {
		console.error('[JobAgent] ensureCoverLetterLoaded error:', e);
	}

	if (btn) {
		btn.textContent = '❌ Failed';
		setTimeout(() => {
			btn.textContent = origText;
			btn.disabled = false;
		}, 2000);
	}
	return false;
}

/** 
 * Ensures the tailored resume base64/URL is loaded in memory.
 * If missing (e.g. after refresh), it fetches it from the JIT endpoint.
 */
async function ensureResumeLoaded() {
	if (window._ja.pendingResume && (window._ja.pendingResume.base64 || window._ja.pendingResume.url)) {
		return true;
	}

	const btn = document.getElementById('ja-preview-btn') || document.getElementById('ja-inject-btn') || document.getElementById('ja-tailor');
	const origText = btn ? btn.textContent : '';
	if (btn) { btn.textContent = '⏳ Loading...'; btn.disabled = true; }

	try {
		const payload = { url: window.location.href };
		if (window._ja.job?.job_id) payload.job_id = window._ja.job.job_id;

		const res = await sendBgMessage('tailorGenerate', payload);
		if (res && res.status === 200 && res.data) {
			const { resume_base64, filename } = res.data;
			const blob = base64ToBlob(resume_base64);
			const url = URL.createObjectURL(blob);
			window._ja.pendingResume = { base64: resume_base64, filename: filename || 'Resume.pdf', url: url };
			if (btn) { btn.textContent = origText; btn.disabled = false; }
			return true;
		}
	} catch (e) {
		console.error('[JobAgent] ensureResumeLoaded error:', e);
	}

	if (btn) {
		btn.textContent = '❌ Failed';
		setTimeout(() => { btn.textContent = origText; btn.disabled = false; }, 2000);
	}
	return false;
}

async function handleInjectClick(btn) {
	if (!(await ensureResumeLoaded())) return;
	const { base64, filename } = window._ja.pendingResume;
	const fi = document.querySelector('input[type="file"], [data-automation-id="file-upload-input-ref"]');

	if (fi) {
		const ok = injectStoredResume(fi, base64, filename);
		if (ok) {
			showToast('✅ Resume injected into upload field!', 'success');
			btn.textContent = '✅ Injected!';
			btn.style.background = '#fff';
			btn.style.color = '#000';
			window._ja.resumeInjected = true;
			setTimeout(() => {
				window._ja.state = STATE.PREVIEWED;
				renderFAMActions();
			}, 1500);
		} else {
			showToast('❌ Injection failed — try manual upload', 'error');
			btn.textContent = '❌ Failed';
		}
	} else {
		showToast('📥 No upload field found — downloading resume for manual upload', 'info', 5000);

		const blob = base64ToBlob(base64);
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);

		btn.textContent = '📥 Downloaded!';
		btn.style.background = '#fff';
		btn.style.color = '#000';
		window._ja.resumeInjected = true;

		setTimeout(() => {
			window._ja.state = STATE.PREVIEWED;
			renderFAMActions();
		}, 2000);
	}
}

// ── Mark Applied (Shredder) ──

async function handleMarkAppliedClick() {
	// Find whichever "mark applied" button exists
	const btn = document.getElementById('ja-applied') || document.getElementById('ja-applied-secondary');
	if (!btn) return;
	btn.textContent = '🧹 Cleaning up...'; btn.disabled = true;

	const payload = { url: window.location.href };
	if (window._ja.job?.job_id) payload.job_id = window._ja.job.job_id;

	try {
		const res = await sendBgMessage('sniperComplete', payload);
		if (res && res.status === 200 && res.data) {
			const shredCount = res.data.shredded ? res.data.shredded.length : 0;
			showToast(`✅ Marked applied! ${shredCount} artifact(s) cleaned up.`, 'success');
			btn.textContent = `✅ Applied`;
			btn.style.background = '#fff';
			btn.style.color = '#000';
			btn.style.cursor = 'default';

			// ── Clear chrome.storage.local cache ──
			const jid = window._ja.job?.job_id;
			if (jid) {
				try { chrome.storage.local.remove(`tailored_${jid}`); } catch (e) { /* ok */ }
			}

			// Transition to APPLIED
			window._ja.state = STATE.APPLIED;
			setTimeout(() => renderFAMActions(), 1500);
		} else {
			btn.textContent = '❌ Failed';
			setTimeout(() => { btn.textContent = '🏁 Mark Applied'; btn.disabled = false; }, 3000);
		}
	} catch (e) {
		console.error('[JobAgent] Mark Applied error:', e);
		btn.textContent = '❌ Error';
		setTimeout(() => { btn.textContent = '🏁 Mark Applied'; btn.disabled = false; }, 3000);
	}
}

// ═══════════════════════════════════════════════════════════════════════════
// §6  SPA-SAFE OBSERVER + INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════

/**
 * The MutationObserver serves two purposes:
 *   1. Detects when ATS SPA navigation destroys the FAM → re-injects it
 *   2. Continues decorating new textarea fields as they appear
 */
function startObserver() {
	const observer = new MutationObserver(() => {
		if (_famObserverPaused) return; // prevent re-injection loops

		// Re-inject FAM if it was destroyed by SPA navigation
		if (!document.getElementById(FAM_ID)) {
			buildFAM();
		}

		// Continue decorating textareas
		detectAndDecorateFields();
	});

	observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Main initialization — called once on page load.
 */
async function init() {
	// 1. Resolve state from backend + chrome.storage.local
	await resolveState();

	// 2. Build the FAM with the correct state
	buildFAM();

	// 3. Decorate Q&A fields with inline suggestion buttons
	detectAndDecorateFields();

	// 4. Start the SPA-safe MutationObserver
	startObserver();
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
	if (request.action === 'get_fam_state') {
		const container = document.getElementById('jobagent-fam-actions');
		if (!container) { sendResponse({ enabled: false }); return; }
		const badge = document.getElementById('jobagent-fam-badge');
		const buttons = Array.from(container.querySelectorAll('button')).map(b => ({
			id: b.id,
			text: b.textContent,
			disabled: b.disabled,
			background: b.style.background,
			color: b.style.color,
			opacity: b.style.opacity,
			cursor: b.style.cursor,
			padding: b.style.padding,
			fontSize: b.style.fontSize
		}));
		sendResponse({ enabled: true, badge: badge ? badge.textContent : 'JobAgent', buttons });
		return true;
	}
	if (request.action === 'trigger_fam_btn') {
		const btn = document.getElementById(request.btnId);
		if (btn) btn.click();
		sendResponse({ status: 'ok' });
		return true;
	}
});

window.addEventListener('load', init);
