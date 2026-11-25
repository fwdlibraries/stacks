import { describe, expect, it } from 'vitest'
import { browserName, defaultChoice, pageCitationBody, parseConnection, toOrigin } from '../src/logic.js'

describe('toOrigin', () => {
  it.each([
    ['https://stacks.example.edu/lists/1', 'https://stacks.example.edu'],
    ['stacks.example.edu', 'https://stacks.example.edu'],
    ['http://localhost:5173', 'http://localhost:5173'],
    ['http://stacks.example.edu', null], // plain http only for local development
    ['', null],
  ])('%s → %s', (input, expected) => expect(toOrigin(input)).toBe(expected))
})

describe('parseConnection', () => {
  const base = 'https://stacks.example.edu'
  it('accepts a token for the address being connected', () => {
    expect(parseConnection(`#token=stx_abc&base=${encodeURIComponent(base)}`, base)).toEqual({ token: 'stx_abc', base })
  })
  it('refuses tokens for another address or that look wrong', () => {
    expect(parseConnection('#token=stx_abc&base=https%3A%2F%2Fevil.example', base)).toBeNull()
    expect(parseConnection(`#token=abc&base=${encodeURIComponent(base)}`, base)).toBeNull()
    expect(parseConnection(`#token=stx_abc&base=${encodeURIComponent(base)}`, undefined)).toBeNull()
  })
})

describe('defaultChoice', () => {
  it('preselects a good match, else the page', () => {
    expect(defaultChoice({ good_match: 0.85, candidates: [{ confidence: 0.97 }] })).toBe('match:0')
    expect(defaultChoice({ good_match: 0.85, candidates: [{ confidence: 0.6 }] })).toBe('page')
    expect(defaultChoice({ good_match: 0.85, candidates: [] })).toBe('page')
  })
})

describe('pageCitationBody', () => {
  it('sends only citation fields, with fallbacks for missing ones', () => {
    const body = pageCitationBody(
      { title: null, resource_type: null, url: 'https://example.org/a', author: [], year: 3000, metadata: { site_name: 'Ex' } },
      'Tab title',
      { is_required: false, student_note: null },
    )
    expect(body).toEqual({
      title: 'Tab title',
      resource_type: 'website',
      url: 'https://example.org/a',
      metadata: { site_name: 'Ex' },
      is_required: false,
      student_note: null,
    })
  })
})

it('names the browser for the connection', () => {
  expect(browserName('Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0')).toBe('Firefox')
  expect(browserName('Mozilla/5.0 … Chrome/131.0 Safari/537.36 Edg/131.0')).toBe('Edge')
  expect(browserName('Mozilla/5.0 … Chrome/131.0 Safari/537.36')).toBe('Chrome')
})
