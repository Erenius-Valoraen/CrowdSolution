'use strict';

const enabled = document.getElementById('enabled');
const checkButton = document.getElementById('check');
const status = document.getElementById('status');

chrome.storage.local.get('enabled').then(({ enabled: on = true }) => { enabled.checked = on; });
enabled.addEventListener('change', () => chrome.storage.local.set({ enabled: enabled.checked }));

chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  const onVideo = /^https:\/\/www\.youtube\.com\/watch\?/.test(tab?.url || '');
  checkButton.disabled = !onVideo;
  if (!onVideo) status.textContent = 'Open a YouTube video to check it.';
  checkButton.addEventListener('click', async () => {
    try {
      await chrome.tabs.sendMessage(tab.id, { type: 'trustify:check-now' });
      status.textContent = 'Checking. Results will appear under the video.';
    } catch {
      status.textContent = 'Reload the YouTube tab, then try again.';
    }
  });
});
