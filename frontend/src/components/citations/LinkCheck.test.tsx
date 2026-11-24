import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { LinkCheck } from './LinkCheck'
import { renderRoutes } from '@/test/renderWithProviders'
import apiClient from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('LinkCheck', () => {
  it('explains where students go and what each step found', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        url: 'https://alma/sd',
        resolved_by: 'alma',
        detail: 'ScienceDirect',
        retracted: false,
        steps: [
          { step: 'libkey', outcome: 'skipped', detail: 'not set up' },
          { step: 'alma', outcome: 'found', detail: 'ScienceDirect', url: 'https://alma/sd' },
        ],
      },
    })
    renderRoutes([{ path: '/', element: <LinkCheck citationId="c1" /> }], '/')
    fireEvent.click(screen.getByRole('button', { name: 'Check link' }))

    expect(
      await screen.findByText(/Students go straight to ScienceDirect \(via Library link resolver\)/)
    ).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/citations/c1/link-check')
    expect(screen.getByText('LibKey: not set up')).toBeInTheDocument()
    expect(screen.getByText('Library link resolver: found (ScienceDirect)')).toBeInTheDocument()
  })

  it('warns about retracted articles and explains fallbacks', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { url: 'https://notice', resolved_by: 'libkey', detail: 'retraction notice', retracted: true, steps: [] },
    })
    renderRoutes([{ path: '/', element: <LinkCheck citationId="c1" /> }], '/')
    fireEvent.click(screen.getByRole('button', { name: 'Check link' }))
    expect(await screen.findByText(/has been retracted/)).toBeInTheDocument()
  })
})
