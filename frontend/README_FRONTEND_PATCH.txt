
// Add this function inside App(), near the other action() helpers:
async function refreshUniverse() {
  await action('/refresh-universe');
  await refresh();
}

// Add this button in the Overview "Quick Actions" actions div:
<button onClick={() => refreshUniverse()}>Refresh Stocks Weekly</button>

// Optional display in Live Summary:
<div><span>Last universe refresh</span><b>{status.weeklyRefresh?.lastRefreshDate || 'Never'}</b></div>
<div><span>Refresh count</span><b>{status.weeklyRefresh?.lastRefreshCount ?? 0}</b></div>
