// The official SDK imports xjiang-ui only for its loading overlay. Our panel
// renders connection status accessibly in the page, without a blocking modal.
export function loading() { return {close() {}}; }
export function popup() { return {close() {}}; }
