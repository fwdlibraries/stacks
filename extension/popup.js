import { api, NotConnected } from './src/api.js'
import { extractPageMetadata } from './src/extract.js'
import {
  SOURCE_LABELS,
  browserName,
  defaultChoice,
  describeCandidate,
  pageCitationBody,
  toOrigin,
} from './src/logic.js'

const app = document.getElementById('app')
const footer = document.getElementById('footer')

/** Build DOM without innerHTML: page metadata is untrusted. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value)
    else if (key === 'class') el.className = value
    else el.setAttribute(key, value === true ? '' : value)
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false) {
      el.append(child instanceof Node ? child : document.createTextNode(String(child)))
    }
  }
  return el
}

function show(...nodes) {
  app.replaceChildren(...nodes)
}

// ── Not connected ────────────────────────────────────────────────────────────

function renderSetup(note) {
  const input = h('input', { type: 'url', id: 'base', placeholder: 'https://stacks.yourlibrary.edu', autocomplete: 'url' })
  const error = h('p', { class: 'error', role: 'alert' })
  const connect = async () => {
    const origin = toOrigin(input.value)
    if (!origin) {
      error.textContent = 'Enter your Stacks web address (https://…).'
      return
    }
    // Only ever ask for access to this one site
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] })
    if (!granted) {
      error.textContent = 'The extension needs permission to talk to your Stacks site.'
      return
    }
    await chrome.storage.local.set({ pendingBase: origin })
    const params = new URLSearchParams({
      return: chrome.runtime.getURL('connected.html'),
      browser: browserName(navigator.userAgent),
    })
    await chrome.tabs.create({ url: `${origin}/extension/connect?${params}` })
    window.close()
  }
  show(
    note ? h('p', { class: 'error' }, note) : null,
    h('p', {}, 'Connect this browser to your Stacks account to add pages to reading lists.'),
    h('label', { for: 'base' }, 'Your Stacks address'),
    input,
    error,
    h('div', { class: 'actions' }, h('button', { onclick: connect }, 'Connect')),
  )
  footer.replaceChildren()
}

// ── Connected ────────────────────────────────────────────────────────────────

async function currentPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  try {
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractPageMetadata })
    if (result) return result
  } catch {
    // Browser pages, the extension store and some PDF viewers can't be read: use the address
  }
  return { url: tab.url, title: tab.title || null, meta: {}, jsonld: [] }
}

function renderFooter(config, me) {
  const disconnect = async () => {
    await chrome.storage.local.remove(['base', 'token'])
    renderSetup('Disconnected. To revoke access completely, also disconnect it in Stacks.')
  }
  footer.replaceChildren(
    h('span', {}, `${me.display_name} · ${me.organization} · `),
    h('button', { class: 'link', onclick: disconnect }, 'Disconnect'),
  )
}

function optionFor(value, checked, title, details, badges) {
  return h(
    'label',
    { class: 'option' },
    h('input', { type: 'radio', name: 'choice', value, checked }),
    h('span', {}, h('span', {}, ...badges), h('span', { class: 'title' }, title), details ? h('div', { class: 'meta' }, details) : null),
  )
}

async function renderMain(config) {
  show(h('p', { class: 'muted' }, 'Looking for this page in your library…'))
  const page = await currentPage()
  const [result, targets, me] = await Promise.all([
    api(config, '/ingest/page', { method: 'POST', body: page }),
    api(config, '/extension/targets'),
    api(config, '/extension/me'),
  ])
  renderFooter(config, me)

  if (targets.length === 0 || targets.every((t) => t.sections.length === 0)) {
    show(h('p', {}, 'You have no reading lists with sections yet. Create one in Stacks first.'))
    return
  }

  const preselect = defaultChoice(result)
  const options = result.candidates.slice(0, 3).map((candidate, i) =>
    optionFor(
      `match:${i}`,
      preselect === `match:${i}`,
      candidate.citation.title || 'Untitled',
      describeCandidate(candidate),
      [
        h('span', { class: `badge${candidate.authoritative ? ' library' : ''}` },
          SOURCE_LABELS[candidate.source_system] || candidate.source_system),
        h('span', { class: `badge${candidate.confidence >= result.good_match ? ' good' : ''}` },
          `${Math.round(candidate.confidence * 100)}% match`),
      ],
    ),
  )
  options.push(
    optionFor('page', preselect === 'page', result.page.title || page.title || page.url, 'This page, as it describes itself', [
      h('span', { class: 'badge' }, 'This page'),
    ]),
  )

  const { lastListId, lastSectionId } = await chrome.storage.local.get(['lastListId', 'lastSectionId'])
  const withSections = targets.filter((t) => t.sections.length > 0)
  const listSelect = h('select', { id: 'list' },
    withSections.map((t) => h('option', { value: t.id, selected: t.id === lastListId },
      t.course_code ? `${t.course_code} — ${t.title}` : t.title)))
  const sectionSelect = h('select', { id: 'section' })
  const fillSections = () => {
    const list = withSections.find((t) => t.id === listSelect.value) || withSections[0]
    sectionSelect.replaceChildren(
      ...list.sections.map((s) => h('option', { value: s.id, selected: s.id === lastSectionId }, s.title)),
    )
  }
  listSelect.addEventListener('change', fillSections)
  fillSections()

  const required = h('input', { type: 'checkbox', id: 'required', checked: true })
  const note = h('textarea', { id: 'note', placeholder: 'e.g. Read pages 1–20' })
  const error = h('p', { class: 'error', role: 'alert' })
  const addButton = h('button', {}, 'Add to list')

  addButton.addEventListener('click', async () => {
    const choice = app.querySelector('input[name="choice"]:checked')?.value ?? 'page'
    const sectionId = sectionSelect.value
    const extras = { is_required: required.checked, student_note: note.value.trim() || null }
    addButton.disabled = true
    error.textContent = ''
    try {
      if (choice.startsWith('match:')) {
        const candidate = result.candidates[Number(choice.slice(6))]
        await api(config, `/sections/${sectionId}/citations/from-source`, {
          method: 'POST',
          body: { source_system: candidate.source_system, source_identifier: candidate.source_identifier, ...extras },
        })
      } else {
        await api(config, `/sections/${sectionId}/citations`, {
          method: 'POST',
          body: pageCitationBody(result.page, page.title, extras),
        })
      }
      await chrome.storage.local.set({ lastListId: listSelect.value, lastSectionId: sectionId })
      const list = withSections.find((t) => t.id === listSelect.value)
      const section = list.sections.find((s) => s.id === sectionId)
      show(
        h('div', { class: 'success' }, `Added to ${list.title} › ${section.title}.`),
        h('div', { class: 'actions' },
          h('button', { class: 'secondary', onclick: () => chrome.tabs.create({ url: `${config.base}/lists/${list.id}` }) },
            'Open the list')),
      )
    } catch (err) {
      if (err instanceof NotConnected) return renderSetup(err.message)
      error.textContent = err.message
      addButton.disabled = false
    }
  })

  show(
    h('h2', {}, result.candidates.length ? 'Add as' : 'Add this page'),
    h('div', { class: 'options' }, options),
    result.warnings.length ? h('p', { class: 'muted' }, `Some sources didn't answer: ${result.warnings.join('; ')}`) : null,
    h('label', { for: 'list' }, 'Reading list'),
    listSelect,
    h('label', { for: 'section' }, 'Section'),
    sectionSelect,
    h('label', { class: 'check' }, required, 'Required reading'),
    h('label', { for: 'note' }, 'Note for students'),
    note,
    error,
    h('div', { class: 'actions' }, addButton),
  )
}

async function main() {
  const config = await chrome.storage.local.get(['base', 'token'])
  if (!config.base || !config.token) return renderSetup()
  // Permission can be withdrawn in the browser's settings
  if (!(await chrome.permissions.contains({ origins: [`${config.base}/*`] }))) {
    return renderSetup('The extension no longer has access to your Stacks site. Connect again.')
  }
  try {
    await renderMain(config)
  } catch (err) {
    if (err instanceof NotConnected) return renderSetup(err.message)
    show(h('p', { class: 'error' }, err.message))
  }
}

main()
