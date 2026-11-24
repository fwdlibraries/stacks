import { describe, expect, it } from 'vitest'
import { getLinkLabel, resolveCitationLink } from './citationLink'

describe('resolveCitationLink', () => {
  it('prefers DOI links', () => {
    expect(resolveCitationLink({ doi: '10.1000/xyz', url: 'https://example.org' })).toBe(
      'https://doi.org/10.1000/xyz'
    )
  })

  it('skips the DOI when use_doi_for_linking is false', () => {
    expect(
      resolveCitationLink({ doi: '10.1000/xyz', use_doi_for_linking: false, url: 'https://example.org' })
    ).toBe('https://example.org')
  })

  it('builds an OpenURL link when the org has a resolver', () => {
    const link = resolveCitationLink(
      { openurl: 'rft.title=Foo' },
      { base_url: 'https://resolver.example.edu/openurl', extra_params: { sid: 'stacks' } }
    )
    expect(link).toBe('https://resolver.example.edu/openurl?rft.title=Foo&sid=stacks')
  })

  it('returns null for physical-only resources', () => {
    expect(resolveCitationLink({})).toBeNull()
    expect(getLinkLabel({})).toBeNull()
  })
})

describe('server-built links', () => {
  it('uses the link the API built, with a label for its kind', () => {
    const citation = {
      doi: '10.1/x',
      url: 'https://example.org',
      link_url: 'https://abc.primo.exlibrisgroup.com/discovery/openurl?rft_id=info:doi/10.1/x',
      link_kind: 'full_text',
    }
    expect(resolveCitationLink(citation)).toBe(citation.link_url)
    expect(getLinkLabel(citation)).toBe('Find full text')
    expect(getLinkLabel({ ...citation, link_kind: 'library_record' })).toBe('View in the library')
  })
})
