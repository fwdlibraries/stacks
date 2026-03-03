/**
 * Link resolution for citations.
 *
 * Priority order (per ADR-004):
 * 1. DOI link (doi.org) — if doi present and use_doi_for_linking
 * 2. Link resolver URL — if openurl and org resolver configured
 * 3. Direct URL — raw url field
 * 4. null — physical-only resource, no link
 */

interface CitationLinkable {
  doi?: string | null
  use_doi_for_linking?: boolean
  openurl?: string | null
  link_resolver_url?: string | null
  url?: string | null
}

interface OrgLinkResolver {
  base_url?: string
  standard?: 'openurl_1_0' | 'openurl_0_1'
  extra_params?: Record<string, string>
}

export function resolveCitationLink(
  citation: CitationLinkable,
  resolver?: OrgLinkResolver | null
): string | null {
  if (citation.doi && citation.use_doi_for_linking !== false) {
    return `https://doi.org/${citation.doi}`
  }

  if (citation.openurl && resolver?.base_url) {
    const params = new URLSearchParams(citation.openurl)
    if (resolver.extra_params) {
      Object.entries(resolver.extra_params).forEach(([k, v]) => params.set(k, v))
    }
    return `${resolver.base_url}?${params.toString()}`
  }

  if (citation.link_resolver_url) {
    return citation.link_resolver_url
  }

  if (citation.url) {
    return citation.url
  }

  return null
}

/** Returns a human-readable label for the link source */
export function getLinkLabel(citation: CitationLinkable): string | null {
  if (citation.doi && citation.use_doi_for_linking !== false) return 'View via DOI'
  if (citation.openurl || citation.link_resolver_url) return 'Find at library'
  if (citation.url) return 'View online'
  return null
}
