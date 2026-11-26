import { useEffect, useState, type ChangeEvent } from 'react'
import { Alert, Button, Card, Col, Form, Row, Spinner } from 'react-bootstrap'
import {
  usePreviewTheme,
  useRemoveLogo,
  useSaveTheme,
  useTheme,
  useUploadLogo,
  type ThemeSettings,
  type ThemeState,
  type ThemeTokens,
} from '@/api/hooks/useAdmin'
import { useTenant, logoUrl } from '@/api/hooks/useTenant'
import { apiErrorMessage } from '@/lib/apiError'

const COLORS: [keyof ThemeTokens, string][] = [
  ['primary', 'Primary (buttons, highlights)'],
  ['link', 'Links'],
  ['text', 'Text'],
  ['background', 'Page background'],
  ['surface', 'Cards and panels'],
  ['border', 'Borders'],
]

const LMS_NAMES: Record<string, string> = { brightspace: 'Brightspace', canvas: 'Canvas', moodle: 'Moodle' }

export default function LookAndFeelView() {
  const theme = useTheme()
  if (theme.isLoading) return <Spinner animation="border" role="status"><span className="visually-hidden">Loading…</span></Spinner>
  if (theme.isError || !theme.data) return <Alert variant="danger">{apiErrorMessage(theme.error, 'Settings could not be loaded.')}</Alert>
  return <ThemeForm key={JSON.stringify(theme.data)} saved={theme.data} />
}

const settingsOf = (t: ThemeState): ThemeSettings => ({
  mode: t.mode, lms: t.lms, lms_primary: t.lms_primary, tokens: t.tokens, custom_css: t.custom_css,
})

function ColorField({ label, value, onChange, id }: { label: string; value: string; onChange: (v: string) => void; id: string }) {
  return (
    <Form.Group className="mb-3" controlId={id}>
      <Form.Label className="small">{label}</Form.Label>
      <div className="d-flex gap-2">
        <Form.Control type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} aria-label={`${label} picker`} style={{ width: '3rem' }} />
        <Form.Control value={value} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: '8rem' }} />
      </div>
    </Form.Group>
  )
}

function ThemeForm({ saved }: { saved: ThemeState }) {
  const [settings, setSettings] = useState<ThemeSettings>(settingsOf(saved))
  const save = useSaveTheme()
  const preview = usePreviewTheme()
  const setTokens = (patch: Partial<ThemeTokens>) => setSettings((s) => ({ ...s, tokens: { ...s.tokens, ...patch } }))

  // Live preview: re-render (debounced) as the settings change
  const json = JSON.stringify(settings)
  useEffect(() => {
    const timer = setTimeout(() => preview.mutate(JSON.parse(json)), 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [json])

  const warnings = preview.data?.warnings ?? saved.warnings
  const showPreview = settings.mode !== 'stacks'

  return (
    <>
      <fieldset className="mb-4">
        <legend className="h5">Style</legend>
        <Form.Check type="radio" id="mode-stacks" name="mode" className="mb-2" checked={settings.mode === 'stacks'}
          onChange={() => setSettings((s) => ({ ...s, mode: 'stacks' }))}
          label={<><strong>Standard Stacks</strong><span className="d-block small text-body-secondary">The Stacks look, with your logo if you add one.</span></>} />
        <Form.Check type="radio" id="mode-lms" name="mode" className="mb-2" checked={settings.mode === 'lms'}
          onChange={() => setSettings((s) => ({ ...s, mode: 'lms' }))}
          label={<><strong>Match your LMS</strong><span className="d-block small text-body-secondary">Looks like Brightspace, Canvas or Moodle, in your institution’s colors, so reading lists feel at home inside courses.</span></>} />
        <Form.Check type="radio" id="mode-custom" name="mode" checked={settings.mode === 'custom'}
          onChange={() => setSettings((s) => ({ ...s, mode: 'custom' }))}
          label={<><strong>Custom</strong><span className="d-block small text-body-secondary">Your own colors, fonts and corners, and optionally your own CSS.</span></>} />
      </fieldset>

      {settings.mode === 'lms' && (
        <Card className="mb-4"><Card.Body>
          {settings.lms === 'auto' && !saved.detected_lms && (
            <Alert variant="info" className="small">
              Stacks doesn’t know which LMS you use yet: it learns from launches. Until then this uses the Stacks
              look in your institution’s color, or choose your LMS below.
            </Alert>
          )}
          <Row>
            <Col md={6}>
              <Form.Group className="mb-3" controlId="lms-which">
                <Form.Label className="small">LMS</Form.Label>
                <Form.Select value={settings.lms} onChange={(e) => setSettings((s) => ({ ...s, lms: e.target.value as ThemeSettings['lms'] }))}>
                  <option value="auto">
                    Automatic{saved.detected_lms ? ` (${LMS_NAMES[saved.detected_lms] ?? saved.detected_lms})` : ''}
                  </option>
                  {Object.entries(LMS_NAMES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col md={6}>
              <ColorField id="lms-primary" label="Your institution’s main color in the LMS (optional)"
                value={settings.lms_primary ?? '#000000'}
                onChange={(v) => setSettings((s) => ({ ...s, lms_primary: v }))} />
              {settings.lms_primary && (
                <Button size="sm" variant="link" className="p-0 mb-3" onClick={() => setSettings((s) => ({ ...s, lms_primary: null }))}>
                  Use the LMS’s standard color
                </Button>
              )}
            </Col>
          </Row>
        </Card.Body></Card>
      )}

      {settings.mode === 'custom' && (
        <Card className="mb-4"><Card.Body>
          <Row>
            {COLORS.map(([key, label]) => (
              <Col sm={6} md={4} key={key}>
                <ColorField id={`token-${key}`} label={label} value={settings.tokens[key] as string} onChange={(v) => setTokens({ [key]: v })} />
              </Col>
            ))}
          </Row>
          <Row>
            {(['heading_font', 'body_font'] as const).map((key) => (
              <Col md={4} key={key}>
                <Form.Group className="mb-3" controlId={`token-${key}`}>
                  <Form.Label className="small">{key === 'heading_font' ? 'Heading font' : 'Text font'}</Form.Label>
                  <Form.Select value={settings.tokens[key]} onChange={(e) => setTokens({ [key]: e.target.value })}>
                    {saved.fonts.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                  </Form.Select>
                </Form.Group>
              </Col>
            ))}
            <Col md={4}>
              <Form.Group className="mb-3" controlId="token-corners">
                <Form.Label className="small">Corners</Form.Label>
                <Form.Select value={settings.tokens.corners} onChange={(e) => setTokens({ corners: e.target.value as ThemeTokens['corners'] })}>
                  <option value="square">Square</option>
                  <option value="standard">Slightly rounded</option>
                  <option value="rounded">Rounded</option>
                </Form.Select>
              </Form.Group>
            </Col>
          </Row>
          <Form.Group controlId="custom-css">
            <Form.Label className="small">Custom CSS (optional)</Form.Label>
            <Form.Control as="textarea" rows={6} className="font-monospace small" value={settings.custom_css}
              onChange={(e) => setSettings((s) => ({ ...s, custom_css: e.target.value }))} placeholder=".card { border-width: 2px; }" />
            <Form.Text>
              Applies to the whole site after saving (not in the preview). For safety it can’t load anything: no
              <code> @import</code>, <code>url()</code> or <code>@font-face</code>.
            </Form.Text>
          </Form.Group>
        </Card.Body></Card>
      )}

      {showPreview && (
        <section aria-label="Preview" className="mb-4">
          <h2 className="h5">Preview</h2>
          {preview.data && <style>{preview.data.css}</style>}
          <div className="stacks-theme-preview border p-3">
            <h3>Week 1 · Required</h3>
            <p>Read the introduction before class. <a href="#preview" onClick={(e) => e.preventDefault()}>A link</a>.</p>
            <div className="card mb-3"><div className="card-body">
              <span className="badge bg-primary me-2">Book</span>
              <strong>What is history?</strong>
              <div className="small" style={{ color: 'var(--bs-secondary-color)' }}>Carr, Edward Hallett · 1961</div>
            </div></div>
            <div className="d-flex gap-2 align-items-center">
              <button type="button" className="btn btn-primary">Primary button</button>
              <button type="button" className="btn btn-outline-primary">Outline button</button>
              <input className="form-control" style={{ maxWidth: '14rem' }} placeholder="A form field" aria-label="Preview form field" />
            </div>
          </div>
        </section>
      )}

      {showPreview && warnings.length > 0 && (
        <Alert variant="warning" className="small">
          <strong>Hard to read for some people</strong> (WCAG AA):
          <ul className="mb-0">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Alert>
      )}
      {(save.error || preview.error) && (
        <Alert variant="danger" className="small">{apiErrorMessage(save.error || preview.error, 'That didn’t work.')}</Alert>
      )}
      {save.isSuccess && <Alert variant="success" className="small">Saved. The site uses the new look now.</Alert>}
      <Button onClick={() => save.mutate(settings)} disabled={save.isPending} className="mb-5">
        {save.isPending ? 'Saving…' : 'Save look and feel'}
      </Button>

      <LogoCard hasLogo={saved.has_logo} />
    </>
  )
}

function LogoCard({ hasLogo }: { hasLogo: boolean }) {
  const upload = useUploadLogo()
  const remove = useRemoveLogo()
  const tenant = useTenant()
  const [fileError, setFileError] = useState<string | null>(null)
  const url = logoUrl(tenant.data)

  const choose = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    setFileError(null)
    if (!file) return
    if (file.size > 200_000) return setFileError('The logo must be 200 KB or smaller.')
    const reader = new FileReader()
    reader.onload = () => {
      const data = String(reader.result).split(',', 2)[1] ?? ''
      upload.mutate({ content_type: file.type, data })
    }
    reader.readAsDataURL(file)
  }

  return (
    <section aria-labelledby="logo-heading">
      <h2 id="logo-heading" className="h5">Logo</h2>
      <p className="small text-body-secondary">Shown in the top bar and on student reading lists. PNG, JPEG or WebP, up to 200 KB.</p>
      {hasLogo && url && <img src={url} alt="Your logo" className="d-block mb-2 border p-2" style={{ maxHeight: '64px' }} />}
      <div className="d-flex gap-2 align-items-center">
        <Form.Control type="file" accept="image/png,image/jpeg,image/webp" onChange={choose} style={{ maxWidth: '22rem' }} aria-label="Upload a logo" />
        {hasLogo && <Button variant="outline-danger" onClick={() => remove.mutate()} disabled={remove.isPending}>Remove logo</Button>}
      </div>
      {(fileError || upload.error) && <Alert variant="danger" className="small mt-2">{fileError ?? apiErrorMessage(upload.error, 'The logo could not be uploaded.')}</Alert>}
    </section>
  )
}
