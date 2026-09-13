# Trustify for YouTube

A Chrome extension that fact-checks YouTube videos about universities, jobs, housing and rent, and government policy. Results show under the video, just above the comments, styled like YouTube (light and dark).

## Install (developer mode)

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and pick this `extension/` folder.
4. Open a YouTube video, for example the jobs report: `https://www.youtube.com/watch?v=4sH30KUfPpM`.

## How it works

- `content.js` runs on YouTube. On each video it reads the title, tags, description, and YouTube category from the watch page.
- It skips categories like Gaming, Music, Sports, and Comedy, and only checks videos whose title, tags, or description clearly match universities, jobs, housing, or government policy.
- Relevant videos are sent to the Trustify API (`https://trustifyapp.vercel.app/api/verify`) as a YouTube link. Results are cached in the browser for 24 hours, so reopening a video is instant and doesn't use another transcript credit.
- Timestamps jump the video to that moment.
- The popup turns automatic checks on or off, and has **Check this video now** for videos the topic filter skipped.

To see why a video was or wasn't checked, open DevTools on the YouTube tab and look for `[Trustify] relevance` in the console (verbose level).

## Notes

- Checks take about a minute because the backend reads the transcript and checks each claim against official data and the web.
- Each new video uses one Supadata transcript credit (100 a month on the free plan).
- To point at a different backend, change `API` in `content.js` and the Trustify URL in `host_permissions` in `manifest.json`.
