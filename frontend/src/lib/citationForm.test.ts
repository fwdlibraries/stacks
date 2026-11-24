import { describe, expect, it } from 'vitest'
import { citationToForm, emptyCitationForm, formToCitationInput, validateCitationForm } from './citationForm'
import type { Citation } from '@/api/hooks/useLists'

describe('citation form', () => {
  it('splits authors by line and converts the year', () => {
    const input = formToCitationInput({
      ...emptyCitationForm(),
      title: '  What Is History? ',
      authors: 'Carr, Edward Hallett\n\n  Evans, Richard J.  \n',
      year: '1961',
    })
    expect(input.title).toBe('What Is History?')
    expect(input.author).toEqual(['Carr, Edward Hallett', 'Evans, Richard J.'])
    expect(input.year).toBe(1961)
  })

  it('sends a blank year as null so it can be cleared', () => {
    expect(formToCitationInput({ ...emptyCitationForm(), title: 'T' }).year).toBeNull()
  })

  it('only sends fields that apply to the resource type', () => {
    const base = { ...emptyCitationForm(), title: 'T', volume: '91', isbn: '978' }
    const article = formToCitationInput({ ...base, resource_type: 'journal_article' })
    expect(article.volume).toBe('91')
    expect(article).not.toHaveProperty('isbn')

    const website = formToCitationInput({ ...base, resource_type: 'website' })
    expect(website).not.toHaveProperty('volume')
    expect(website).not.toHaveProperty('isbn')
  })

  it('round-trips an existing citation', () => {
    const citation: Citation = {
      id: 'c1',
      title: 'Gender',
      resource_type: 'journal_article',
      author: ['Scott, Joan W.'],
      year: 1986,
      volume: '91',
      doi: '10.2307/1864376',
      use_doi_for_linking: true,
      is_required: false,
      sort_order: 0,
      metadata: {},
    }
    const input = formToCitationInput(citationToForm(citation))
    expect(input).toMatchObject({
      title: 'Gender',
      author: ['Scott, Joan W.'],
      year: 1986,
      volume: '91',
      doi: '10.2307/1864376',
      is_required: false,
    })
  })

  it.each([
    [{ title: '' }, 'title'],
    [{ year: '86' }, 'year'],
    [{ url: 'javascript:alert(1)' }, 'url'],
    [{ url: 'www.example.org' }, 'url'],
    [{ doi: 'not-a-doi' }, 'doi'],
  ])('flags %o', (patch, field) => {
    const errors = validateCitationForm({ ...emptyCitationForm(), title: 'T', ...patch })
    expect(Object.keys(errors)).toEqual([field])
  })

  it('accepts DOI URLs and http(s) links', () => {
    const errors = validateCitationForm({
      ...emptyCitationForm(),
      title: 'T',
      doi: 'https://doi.org/10.2307/1864376',
      url: 'https://example.org',
    })
    expect(errors).toEqual({})
  })
})
