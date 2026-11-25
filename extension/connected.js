import { parseConnection } from './src/logic.js'

// Stacks' connect page sends the token here in the URL fragment (never sent to a server).
// Only accept it for the address this extension started connecting to.
const heading = document.getElementById('heading')
const message = document.getElementById('message')

const { pendingBase } = await chrome.storage.local.get('pendingBase')
const connection = parseConnection(location.hash, pendingBase)
history.replaceState(null, '', location.pathname) // drop the token from the address bar

if (connection) {
  await chrome.storage.local.set({ base: connection.base, token: connection.token })
  await chrome.storage.local.remove('pendingBase')
  heading.textContent = 'Stacks is connected'
  message.textContent =
    'You can close this tab. To add something to a reading list, click the Stacks button in your browser toolbar.'
} else {
  heading.textContent = "Stacks couldn't connect"
  message.textContent = 'Click the Stacks button in your toolbar and start connecting again.'
}
