import { beforeEach, describe, expect, it } from 'vitest'
import { extractPageMetadata } from '../src/extract.js'

beforeEach(() => {
  document.head.innerHTML = ''
  document.title = ''
})

describe('extractPageMetadata', () => {
  it('collects meta tags (repeated ones too) and JSON-LD', () => {
    document.head.innerHTML = `
      <meta name="citation_title" content="Gender: A Useful Category">
      <meta name="citation_author" content="Scott, Joan W.">
      <meta name="citation_author" content="Second, Author">
      <meta property="og:site_name" content="Journal">
      <meta name="empty" content="  ">
      <meta charset="utf-8">
      <script type="application/ld+json">{"@type": "ScholarlyArticle", "name": "Gender"}</script>
      <script type="application/ld+json">{ not json </script>`
    document.title = 'Gender | AHR'
    const result = extractPageMetadata()
    expect(result.title).toBe('Gender | AHR')
    expect(result.url).toBe(location.href)
    expect(result.meta).toEqual({
      citation_title: ['Gender: A Useful Category'],
      citation_author: ['Scott, Joan W.', 'Second, Author'],
      'og:site_name': ['Journal'],
    })
    expect(result.jsonld).toEqual([{ '@type': 'ScholarlyArticle', name: 'Gender' }])
  })

  it('caps what it sends', () => {
    document.head.innerHTML = Array.from({ length: 30 }, () => '<meta name="dc.subject" content="x">').join('')
    expect(extractPageMetadata().meta['dc.subject']).toHaveLength(20)
  })

  it('is self-contained, so it can be injected into a page', () => {
    // executeScript serializes the function: it must not use imports or outer variables
    const injected = new Function(`return (${extractPageMetadata.toString()})()`)
    expect(injected().url).toBe(location.href)
  })
})
