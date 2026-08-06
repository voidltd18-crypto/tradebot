TradeBot V16.5.4 — Lazy Dashboard Loading

Replace the frontend package contents inside the existing frontend directory.

Changes:
- Overview and Positions poll only /status and /banking-status.
- Reports loads only when the Reports tab is opened.
- AI Portfolio loads only while its tab is mounted.
- AI Intelligence loads only endpoints required by the selected subsection.
- Heavy pages use React lazy loading/code splitting.
- Trading logic and backend are unchanged.

After upload, deploy to Vercel without build cache and hard refresh the browser.
