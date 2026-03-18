/**
 * JobAgent Background Service Worker
 * Bridges content script messages to the local FastAPI backend.
 */

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
	if (request.action === 'fillProfile') {
		console.log('Sending payload:', request.payload);

		fetch('http://localhost:8000/api/profile/fill', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(async (res) => {
				if (!res.ok) {
					const errBody = await res.text();
					console.error('API Error:', res.status, errBody);
					throw new Error(errBody);
				}
				return res.json();
			})
			.then((data) => {
				sendResponse(data);
			})
			.catch((err) => {
				console.error('JobAgent background fetch error:', err);
				sendResponse({ error: err.message });
			});

		// Return true to keep the message channel open for the async response
		return true;
	}

	if (request.action === 'completeApplication') {
		fetch('http://localhost:8000/api/profile/application_complete', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(res => res.json())
			.then(data => console.log('Application tracking complete:', data))
			.catch(err => console.error('Tracking error:', err));
		return true;
	}

	if (request.action === 'sniperAnswer') {
		fetch('http://localhost:8000/api/sniper/answer', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(async (res) => {
				if (res.status === 404) {
					sendResponse({ status: 404, data: null });
					return;
				}
				if (!res.ok) throw new Error(`API Error: ${res.status}`);
				return res.json();
			})
			.then(data => {
				if (data) sendResponse({ status: 200, data });
			})
			.catch(err => {
				console.error('Sniper Answer error:', err);
				sendResponse({ status: 500, error: err.message });
			});
		return true; // Keep message channel open for async fetch
	}

	if (request.action === 'sniperComplete') {
		fetch('http://localhost:8000/api/sniper/complete', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(res => res.json())
			.then(data => sendResponse({ status: 200, data }))
			.catch(err => {
				console.error('Sniper Complete error:', err);
				sendResponse({ status: 500, error: err.message });
			});
		return true; // Keep message channel open for async fetch
	}

	if (request.action === 'scoutCheckUrl') {
		const encoded = encodeURIComponent(request.payload.url);
		fetch(`http://localhost:8000/api/scout/check_url?url=${encoded}`)
			.then(res => res.json())
			.then(data => sendResponse({ status: 200, data }))
			.catch(err => {
				console.error('Scout Check URL error:', err);
				sendResponse({ status: 500, error: err.message });
			});
		return true;
	}

	if (request.action === 'scoutOrganic') {
		fetch('http://localhost:8000/api/scout/organic', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(async (res) => {
				if (!res.ok) {
					const errBody = await res.text();
					throw new Error(errBody);
				}
				return res.json();
			})
			.then(data => sendResponse({ status: 200, data }))
			.catch(err => {
				console.error('Scout Organic error:', err);
				sendResponse({ status: 500, error: err.message });
			});
		return true;
	}

	if (request.action === 'tailorGenerate') {
		fetch('http://localhost:8000/api/tailor/generate', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(async (res) => {
				if (res.status === 404) {
					sendResponse({ status: 404, data: null });
					return;
				}
				if (!res.ok) throw new Error(`API Error: ${res.status}`);
				return res.json();
			})
			.then(data => {
				if (data) sendResponse({ status: 200, data });
			})
			.catch(err => {
				console.error('Tailor Generate error:', err);
				sendResponse({ status: 500, error: err.message });
			});
		return true;
	}

	if (request.action === 'coverLetterGenerate') {
		fetch('http://localhost:8000/api/tailor/generate_cover_letter', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(request.payload),
		})
			.then(async (res) => {
				if (res.status === 404) {
					sendResponse({ status: 404, data: null });
					return;
				}
				if (!res.ok) throw new Error(`API Error: ${res.status}`);
				return res.json();
			})
			.then(data => {
				if (data) sendResponse({ status: 200, data });
			})
			.catch(err => {
				console.error('Cover Letter Generate error:', err);
				sendResponse({ status: 500, error: err.message });
			});
		return true;
	}
});
