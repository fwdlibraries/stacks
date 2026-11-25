/** Pure helpers for the popup (tested in test/logic.test.js). */

export const SOURCE_LABELS = {
  alma: 'Your library',
  primo: 'Library search',
  crossref: 'Crossref',
  openlibrary: 'Open Library',
}

/** Normalize what someone typed as their Stacks address to an origin, or null. */
export function toOrigin(input) {
  const value = (input || '').trim()
  if (!value) return null
  try {
    const url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`)
    if (url.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(url.hostname)) return null
    return url.origin
  } catch {
    return null
  }
}

/** "chrome-extension://…/connected.html#token=…&base=…" → { token, base }, or null */
export function parseConnection(hash, expectedBase) {
  const params = new URLSearchParams((hash || '').replace(/^#/, ''))
  const token = params.get('token')
  const base = params.get('base')
  if (!token || !token.startsWith('stx_') || !base || base !== expectedBase) return null
  return { token, base }
}

/** Which option to preselect: the best match if it's good enough, else the page itself. */
export function defaultChoice(result) {
  const best = result.candidates[0]
  return best && best.confidence >= result.good_match ? 'match:0' : 'page'
}

const CITATION_FIELDS = [
  'resource_type', 'title', 'author', 'editor', 'year', 'publisher', 'place_of_publication', 'edition',
  'volume', 'issue', 'pages', 'isbn', 'issn', 'doi', 'url', 'metadata',
]

/** The page "as is" as a POST /sections/{id}/citations body. */
export function pageCitationBody(page, fallbackTitle, extras) {
  const body = {}
  for (const field of CITATION_FIELDS) {
    const value = page[field]
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) continue
    body[field] = value
  }
  body.title = body.title || fallbackTitle || body.url || 'Untitled'
  body.resource_type = body.resource_type || 'website'
  if (body.year && (body.year < 1000 || body.year > 2100)) delete body.year
  return { ...body, ...extras }
}

export function describeCandidate(candidate) {
  const c = candidate.citation
  const parts = [c.author && c.author[0], c.year, c.metadata && c.metadata.journal_name].filter(Boolean)
  return parts.join(' · ')
}

export function browserName(userAgent) {
  if (/Firefox\//.test(userAgent)) return 'Firefox'
  if (/Edg\//.test(userAgent)) return 'Edge'
  return 'Chrome'
}
