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
});
