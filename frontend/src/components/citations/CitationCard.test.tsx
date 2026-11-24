import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CitationCard } from './CitationCard'
import type { Citation } from '@/api/hooks/useLists'

const CITATION: Citation = {
  id: 'c1',
  title: 'Electricity pricing',
  resource_type: 'journal_article',
  use_doi_for_linking: true,
  is_required: true,
  sort_order: 0,
  metadata: {},
  link_url: '/api/v1/go/c1',
  link_kind: 'full_text',
}

describe('CitationCard links', () => {
  it('sends students through Stacks click-through links', () => {
    render(<CitationCard citation={CITATION} />)
    expect(screen.getByRole('link', { name: 'Electricity pricing' })).toHaveAttribute('href', '/api/v1/go/c1')
    expect(screen.getByRole('button', { name: /Find full text/ })).toHaveAttribute('href', '/api/v1/go/c1')
  })

  it('marks editor clicks as previews and shows click counts', () => {
    render(<CitationCard citation={CITATION} linkPreview clicks={{ total: 12, last_30_days: 3 }} />)
    expect(screen.getByRole('link', { name: 'Electricity pricing' })).toHaveAttribute(
      'href',
      '/api/v1/go/c1?preview=true'
    )
    expect(screen.getByText('12 student clicks · 3 in the last 30 days')).toBeInTheDocument()
  })

  it('leaves other links alone in preview mode', () => {
    render(<CitationCard citation={{ ...CITATION, link_url: 'https://example.org/x', link_kind: 'web' }} linkPreview />)
    expect(screen.getByRole('link', { name: 'Electricity pricing' })).toHaveAttribute('href', 'https://example.org/x')
  })
})
