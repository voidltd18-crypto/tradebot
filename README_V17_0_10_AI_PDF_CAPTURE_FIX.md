# TradeBot V17.0.10 — AI PDF Capture Fix

Fixes the blank multi-page AI Intelligence export from V17.0.9.

Cause: V17.0.9 attempted to rasterise the entire 12-section Intelligence report into one extremely tall browser canvas. Large reports can exceed browser canvas limits, producing a valid PDF containing blank pages.

Fix:
- captures each of the 12 AI Intelligence sections separately;
- slices oversized individual sections across A4 landscape pages;
- stitches all captured pages into one PDF with jsPDF;
- waits until all 12 sections are mounted and fonts/data have rendered before capture;
- retains the same one-click EXPORT FULL AI REPORT PDF button;
- trading/backend logic is unchanged.
