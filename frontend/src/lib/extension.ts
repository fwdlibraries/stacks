/**
 * The extension connect page hands its token only to the extension's own page
 * (chrome-extension:// or moz-extension://…/connected.html), so a website can't
 * use that page to obtain one.
 */
export function isExtensionReturn(value: string | null): value is string {
  if (!value) return false
  try {
    const url = new URL(value)
    return ['chrome-extension:', 'moz-extension:'].includes(url.protocol) && url.pathname === '/connected.html'
  } catch {
    return false
  }
}
