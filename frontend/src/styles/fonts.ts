/**
 * Self-hosted web fonts (OFL), bundled by Vite so the app makes no requests to
 * Google Fonts. That matters for privacy when the app is embedded in an LMS.
 */
import '@fontsource/playfair-display/600.css'
import '@fontsource/libre-baskerville/400.css'
import '@fontsource/libre-baskerville/400-italic.css'
import '@fontsource/libre-baskerville/700.css'

// For the LMS looks (Brightspace and Canvas use Lato, Moodle Noto Sans). Browsers
// download a font's files only when a page actually uses it.
import '@fontsource/lato/400.css'
import '@fontsource/lato/700.css'
import '@fontsource/noto-sans/400.css'
import '@fontsource/noto-sans/500.css'
import '@fontsource/noto-sans/700.css'
