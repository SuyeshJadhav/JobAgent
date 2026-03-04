document.getElementById('fetchBtn').addEventListener('click', async () => {
	const jobId = document.getElementById('jobId').value;
	const statusDiv = document.getElementById('status');
	statusDiv.innerText = "Fetching...";
	try {
		const res = await fetch(`http://localhost:8000/api/apply/${jobId}/payload`);
		if (!res.ok) throw new Error("Job not found");
		const data = await res.json();
		statusDiv.innerText = `Ready to apply at ${data.company}!\nResume: ${data.resume_path}`;
		// Next step: save to chrome.storage and send message to content script
	} catch (err) {
		statusDiv.innerText = `Error: ${err.message}`;
	}
});
