// Copy the files the extension ships into dist/stacks-extension/ (load it unpacked,
// or zip it for the Chrome Web Store / addons.mozilla.org).
import { cpSync, mkdirSync, rmSync } from 'node:fs'

const out = 'dist/stacks-extension'
rmSync('dist', { recursive: true, force: true })
mkdirSync(out, { recursive: true })
for (const path of ['manifest.json', 'popup.html', 'popup.css', 'popup.js', 'connected.html', 'connected.js', 'src', 'icons']) {
  cpSync(path, `${out}/${path}`, { recursive: true })
}
console.log(`Packaged into ${out}/`)
