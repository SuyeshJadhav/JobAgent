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
	element.value = value;
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

function extractPageTitle() {
	const h1 = document.querySelector('h1');
	if (h1 && h1.textContent.trim().length > 3) return h1.textContent.trim();
	const og = document.querySelector('meta[property="og:title"]');
	if (og) return og.content.trim();
	return document.title.split('|')[0].split('-')[0].trim();
}

function extractCompanyName() {
	const wd = document.querySelector('[data-automation-id="company"]');
	if (wd) return wd.textContent.trim();
	const og = document.querySelector('meta[property="og:site_name"]');
	if (og) return og.content.trim();
	try {
		const h = window.location.hostname.replace('www.', '').split('.')[0];
		return h.charAt(0).toUpperCase() + h.slice(1);
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
		marginTop: '6px', marginBottom: '12px', padding: '5px 10px',
		fontSize: '12px', fontWeight: '600', color: '#fff',
		background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
		border: 'none', borderRadius: '6px', cursor: 'pointer',
		boxShadow: '0 2px 4px rgba(99,102,241,0.3)', transition: 'all 0.2s ease',
		fontFamily: 'system-ui, sans-serif'
	});
	btn.addEventListener('mouseenter', () => btn.style.transform = 'translateY(-1px)');
	btn.addEventListener('mouseleave', () => btn.style.transform = 'translateY(0)');
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
			const mk = Object.keys(answers).find(k => normalizeKey(k) === nq);
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
		fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
		transition: 'transform 0.25s ease',
	});

	// ── Toggle Tab ──
	const toggle = document.createElement('button');
	toggle.id = 'jobagent-fam-toggle';
	toggle.textContent = '🎯';
	toggle.type = 'button';
	Object.assign(toggle.style, {
		width: '36px', height: '36px', border: 'none', cursor: 'pointer',
		background: 'linear-gradient(180deg, #4f46e5, #6366f1)',
		color: '#fff', fontSize: '18px', borderRadius: '8px 0 0 8px',
		display: 'flex', alignItems: 'center', justifyContent: 'center',
		boxShadow: '-2px 2px 8px rgba(0,0,0,0.2)',
		transition: 'background 0.2s ease',
		alignSelf: 'flex-start',
	});

	// ── Panel ──
	const panel = document.createElement('div');
	panel.id = 'jobagent-fam-panel';
	Object.assign(panel.style, {
		width: '0px', background: '#1e1b2e',
		borderRadius: '12px 0 0 12px', padding: '14px 0',
		display: 'flex', flexDirection: 'column', gap: '10px',
		boxShadow: '-4px 4px 20px rgba(0,0,0,0.35)',
		transition: 'width 0.25s ease, padding 0.25s ease, opacity 0.25s ease',
		overflow: 'hidden',
		opacity: '0',
	});

	let panelOpen = false;
	toggle.addEventListener('click', () => {
		panelOpen = !panelOpen;
		if (panelOpen) {
			panel.style.width = '220px';
			panel.style.padding = '14px 12px';
			panel.style.opacity = '1';
		} else {
			panel.style.width = '0px';
			panel.style.padding = '14px 0';
			panel.style.opacity = '0';
		}
	});

	// ── Status Badge ──
	const badge = document.createElement('div');
	badge.id = 'jobagent-fam-badge';
	Object.assign(badge.style, {
		fontSize: '11px', color: '#a5b4fc', textAlign: 'center',
		padding: '2px 0 4px 0', letterSpacing: '0.5px',
		borderBottom: '1px solid rgba(255,255,255,0.08)',
		marginBottom: '4px', fontWeight: '500',
	});
	badge.textContent = 'JobAgent';
	panel.appendChild(badge);

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
function createFAMButton(id, text, gradient, shadowColor) {
	const btn = document.createElement('button');
	btn.id = id;
	btn.textContent = text;
	btn.type = 'button';
	Object.assign(btn.style, {
		width: '100%', border: 'none', cursor: 'pointer',
		padding: '10px 12px', borderRadius: '8px',
		fontSize: '13px', fontWeight: '600', color: '#fff',
		background: gradient,
		boxShadow: `0 3px 10px ${shadowColor}`,
		transition: 'transform 0.15s ease, box-shadow 0.15s ease',
		fontFamily: 'inherit', letterSpacing: '0.2px',
	});
	btn.addEventListener('mouseenter', () => {
		btn.style.transform = 'translateY(-1px)';
	});
	btn.addEventListener('mouseleave', () => {
		btn.style.transform = 'translateY(0)';
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
		const btn = createFAMButton(
			'ja-track', '📥 Track & Score Job',
			'linear-gradient(135deg, #3b82f6, #2563eb)', 'rgba(59,130,246,0.4)'
		);
		btn.addEventListener('click', handleTrackClick);
		container.appendChild(btn);
	}

	// ── TRACKED: Show "Tailor & Preview" ──
	if (state === STATE.TRACKED) {
		const btn = createFAMButton(
			'ja-tailor', '📄 Tailor & Preview Resume',
			'linear-gradient(135deg, #8b5cf6, #7c3aed)', 'rgba(139,92,246,0.4)'
		);
		btn.addEventListener('click', handleTailorClick);
		container.appendChild(btn);
	}

	// ── TAILORED / PREVIEWED: Show "Preview" and "Inject" ──
	if (state === STATE.TAILORED || state === STATE.PREVIEWED) {
		const btnPreview = createFAMButton(
			'ja-preview-btn', '🔍 Re-Preview PDF',
			'linear-gradient(135deg, #6366f1, #4f46e5)', 'rgba(99,102,241,0.3)'
		);
		btnPreview.addEventListener('click', () => {
			if (window._ja.pendingResume) {
				const blob = base64ToBlob(window._ja.pendingResume.base64);
				const url = URL.createObjectURL(blob);
				window.open(url, '_blank');
			}
		});
		container.appendChild(btnPreview);

		const btnInject = createFAMButton(
			'ja-inject-btn', '💉 Inject & Apply',
			'linear-gradient(135deg, #10b981, #059669)', 'rgba(16,185,129,0.4)'
		);
		btnInject.addEventListener('click', () => handleInjectClick(btnInject));
		container.appendChild(btnInject);
	}

	// ── APPLIED: Show "Done" (disabled) ──
	if (state === STATE.APPLIED) {
		const btn = createFAMButton(
			'ja-done', '✅ Applied & Cleaned',
			'linear-gradient(135deg, #10b981, #059669)', 'rgba(16,185,129,0.3)'
		);
		btn.disabled = true;
		btn.style.cursor = 'default';
		btn.style.opacity = '0.8';
		container.appendChild(btn);
	}

	// ── Always show "Mark Applied" as a secondary if tracked but not yet applied ──
	if (state === STATE.TRACKED || state === STATE.TAILORED || state === STATE.PREVIEWED) {
		// Only add if not already the primary
		if (state === STATE.TRACKED || state === STATE.PREVIEWED || state === STATE.TAILORED) {
			const btn2 = createFAMButton(
				'ja-applied-secondary', '🏁 Mark Applied',
				'linear-gradient(135deg, #f59e0b, #d97706)', 'rgba(245,158,11,0.3)'
			);
			btn2.style.opacity = '0.7';
			btn2.style.fontSize = '11px';
			btn2.style.padding = '7px 10px';
			btn2.addEventListener('click', handleMarkAppliedClick);
			container.appendChild(btn2);
		}
	}

	// ── Update badge ──
	const badge = document.getElementById('jobagent-fam-badge');
	if (badge) {
		const job = window._ja.job;
		if (job && job.job_id) {
			const score = job.score ? ` · ${job.score}/10` : '';
			badge.textContent = `JobAgent${score}`;
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

	const payload = {
		url: window.location.href,
		title: extractPageTitle(),
		company: extractCompanyName(),
		page_text: document.body.innerText.substring(0, 15000),
	};

	try {
		const res = await sendBgMessage('scoutOrganic', payload);
		if (res && res.status === 200 && res.data) {
			const d = res.data;
			window._ja.job = { job_id: d.job_id, score: d.score, status: d.job_status, reason: d.reason };

			if (d.job_status === 'shortlisted') {
				btn.textContent = `✅ Tracked! Score: ${d.score}/10`;
				btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
			} else {
				btn.textContent = `⚠️ Score: ${d.score}/10 (${d.job_status})`;
				btn.style.background = 'linear-gradient(135deg, #ef4444, #dc2626)';
			}

			// Transition state after a brief pause
			setTimeout(() => {
				window._ja.state = STATE.TRACKED;
				renderFAMActions();
			}, 2000);
		} else {
			btn.textContent = '❌ Error';
			setTimeout(() => { btn.textContent = '📥 Track & Score Job'; btn.disabled = false; }, 3000);
		}
	} catch (e) {
		console.error('[JobAgent] Track error:', e);
		btn.textContent = '❌ Error';
		setTimeout(() => { btn.textContent = '📥 Track & Score Job'; btn.disabled = false; }, 3000);
	}
}

// ── Tailor & Inject Resume ──

async function handleTailorClick() {
	const btn = document.getElementById('ja-tailor');
	if (!btn) return;
	btn.textContent = '⏳ Forging Resume...'; btn.disabled = true;

	const payload = { url: window.location.href };
	if (window._ja.job?.job_id) payload.job_id = window._ja.job.job_id;

	try {
		const res = await sendBgMessage('tailorGenerate', payload);
		if (res && res.status === 200 && res.data) {
			const { resume_base64, filename, job_id } = res.data;

			window._ja.pendingResume = { base64: resume_base64, filename: filename || 'Resume.pdf' };

			// ── Open PDF in new tab automatically ──
			const blob = base64ToBlob(resume_base64);
			const url = URL.createObjectURL(blob);
			window.open(url, '_blank');

			btn.textContent = '✅ Resume Ready';
			btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';

			// ── Persist to chrome.storage.local ──
			const jid = job_id || window._ja.job?.job_id;
			if (jid) {
				try { chrome.storage.local.set({ [`tailored_${jid}`]: true }); } catch (e) { /* ok */ }
			}

			// Transition to PREVIEWED state
			setTimeout(() => {
				window._ja.state = STATE.PREVIEWED;
				renderFAMActions();
			}, 1500);
		} else if (res && res.status === 404) {
			btn.textContent = '❌ Job Not Found';
			setTimeout(() => { btn.textContent = '📄 Tailor & Preview Resume'; btn.disabled = false; }, 3000);
		} else {
			btn.textContent = '❌ Error';
			setTimeout(() => { btn.textContent = '📄 Tailor & Preview Resume'; btn.disabled = false; }, 3000);
		}
	} catch (e) {
		console.error('[JobAgent] Tailor error:', e);
		btn.textContent = '❌ Error';
		setTimeout(() => { btn.textContent = '📄 Tailor & Preview Resume'; btn.disabled = false; }, 3000);
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

async function handleInjectClick(btn) {
	if (!window._ja.pendingResume) return;
	const { base64, filename } = window._ja.pendingResume;
	const fi = document.querySelector('input[type="file"], [data-automation-id="file-upload-input-ref"]');

	if (fi) {
		const ok = injectStoredResume(fi, base64, filename);
		if (ok) {
			btn.textContent = '✅ Injected!';
			btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
			window._ja.resumeInjected = true;
			setTimeout(() => {
				window._ja.state = STATE.PREVIEWED;
				renderFAMActions();
			}, 1500);
		} else {
			btn.textContent = '❌ Failed';
		}
	} else {
		// Fallback to manual download for chatbot ATS (Paradox) or cross-origin iframes
		alert('File upload field not found on this page. Downloading your tailored resume for manual drag-and-drop.');

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
		btn.style.background = 'linear-gradient(135deg, #f59e0b, #d97706)';
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
			btn.textContent = `✅ SSD Clean (${shredCount} shredded)`;
			btn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
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
