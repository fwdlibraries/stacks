# Stacks browser extension

Add the article, book or web page you're viewing to a Stacks reading list. Works in
Chrome, Edge and Firefox (Manifest V3); there's no build step.

## How it works

1. **Connect once.** Click the toolbar button, enter your Stacks address and choose
   **Connect**. The browser asks permission for that one site, then Stacks asks you
   to confirm. Stacks creates a token for the extension only: it can list your
   organization's reading lists and add citations, nothing else. Disconnect it any
   time from Stacks (`/extension/connect`) or the popup.
2. **Add a page.** On any page, click the button. The extension reads the citation
   metadata the page publishes (`citation_*`, Dublin Core, PRISM, Open Graph and
   schema.org JSON-LD tags, nothing else) and Stacks looks for it in your library.
   Pick a match (or the page as it is), a list and section, and add it.

### Privacy

- The extension can read a page only when you click its button (`activeTab`).
- It talks only to the Stacks site you connect (requested as an optional host
  permission at connect time).
- What it sends when you click: the page's address, title and citation metadata.

## Development

Load it unpacked:

- **Chrome / Edge:** `chrome://extensions` → Developer mode → *Load unpacked* → this folder.
- **Firefox:** `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on* → `manifest.json`.

To use a local dev stack, connect to `http://localhost:5173` (plain http is allowed
for localhost only) or a tunnel's https address.

```sh
npm ci
npm test          # extractor and popup logic (vitest + jsdom)
npm run check     # syntax check
npm run package   # → dist/stacks-extension/ (zip it for the stores)
npx web-ext lint --source-dir dist/stacks-extension
```

Store listings (Chrome Web Store, addons.mozilla.org) are published from
`dist/stacks-extension/`.
