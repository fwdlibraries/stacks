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
