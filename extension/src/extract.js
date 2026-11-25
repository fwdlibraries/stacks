/**
 * Runs inside the page (via chrome.scripting.executeScript), so it must be
 * self-contained: no imports, no references to anything outside the function.
 * Collects only bibliographic metadata the page publishes for citation tools:
 * <meta> tags and schema.org JSON-LD. Nothing else on the page is read.
 */
export function extractPageMetadata() {
  const MAX_KEYS = 300
  const MAX_VALUES = 20
  const MAX_VALUE = 2000
  const MAX_JSONLD = 20
  const MAX_JSONLD_CHARS = 100000

  const meta = {}
  let keys = 0
  for (const el of document.querySelectorAll('meta[name], meta[property]')) {
    const key = (el.getAttribute('name') || el.getAttribute('property') || '').trim().slice(0, 100)
    const content = (el.getAttribute('content') || '').trim()
    if (!key || !content) continue
    if (!meta[key]) {
      if (keys >= MAX_KEYS) continue
      meta[key] = []
      keys += 1
    }
    if (meta[key].length < MAX_VALUES) meta[key].push(content.slice(0, MAX_VALUE))
  }

  const jsonld = []
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    if (jsonld.length >= MAX_JSONLD) break
    const text = script.textContent || ''
    if (text.length > MAX_JSONLD_CHARS) continue
    try {
      jsonld.push(JSON.parse(text))
    } catch {
      // Malformed JSON-LD is common; skip it
    }
  }

  return { url: location.href, title: document.title || null, meta, jsonld }
}
