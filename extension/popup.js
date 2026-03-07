let intervalId = null;

async function fetchState() {
	try {
		const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
		if (!tab) return;

		chrome.tabs.sendMessage(tab.id, { action: 'get_fam_state' }, (response) => {
			if (chrome.runtime.lastError) {
				document.getElementById('jobagent-fam-actions').innerHTML = '<div id="loading" style="color: #fca5a5;">JobAgent is not active on this page.</div>';
				return;
			}

			if (response && response.enabled) {
				document.getElementById('jobagent-fam-badge').textContent = response.badge;

				const container = document.getElementById('jobagent-fam-actions');
				container.innerHTML = '';

				if (response.buttons.length === 0) {
					container.innerHTML = '<div id="loading" style="color: #a5b4fc;">Initializing...</div>';
					return;
				}

				response.buttons.forEach(bInfo => {
					const btn = document.createElement('button');
					btn.textContent = bInfo.text;
					btn.disabled = bInfo.disabled;

					if (bInfo.background) btn.style.background = bInfo.background;
					if (bInfo.color) btn.style.color = bInfo.color;
					if (bInfo.opacity) btn.style.opacity = bInfo.opacity;
					if (bInfo.cursor) btn.style.cursor = bInfo.cursor;
					if (bInfo.padding) btn.style.padding = bInfo.padding;
					if (bInfo.fontSize) btn.style.fontSize = bInfo.fontSize;

					btn.addEventListener('click', () => {
						btn.style.opacity = '0.8';
						chrome.tabs.sendMessage(tab.id, { action: 'trigger_fam_btn', btnId: bInfo.id });
					});

					container.appendChild(btn);
				});
			} else {
				document.getElementById('jobagent-fam-actions').innerHTML = '<div id="loading" style="color: #fca5a5;">JobAgent is initializing...</div>';
			}
		});
	} catch (err) {
		console.error(err);
	}
}

intervalId = setInterval(fetchState, 500);
fetchState();
