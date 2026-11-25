import { describe, expect, it } from 'vitest'
import { isExtensionReturn } from './extension'

describe('isExtensionReturn', () => {
  it.each([
    ['chrome-extension://abcdefghijklmnop/connected.html', true],
    ['moz-extension://1234-5678/connected.html', true],
    ['https://evil.example/connected.html', false],
    ['chrome-extension://abc/other.html', false],
    ['javascript:alert(1)//connected.html', false],
    [null, false],
    ['not a url', false],
  ])('%s → %s', (value, expected) => {
    expect(isExtensionReturn(value)).toBe(expected)
  })
})
