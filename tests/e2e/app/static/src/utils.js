export function formatDate(isoString) {
    if (!isoString) return '-';
    return new Date(isoString).toLocaleString();
}

export function formatDuration(ms) {
    if (!ms) return '0ms';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
}
