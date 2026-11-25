export class NotConnected extends Error {}

/** Call the Stacks API with the extension's token. */
export async function api(config, path, { method = 'GET', body } = {}) {
  let resp
  try {
    resp = await fetch(`${config.base}/api/v1${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${config.token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error(`Stacks (${config.base}) can't be reached.`)
  }
  if (resp.status === 401) throw new NotConnected('This browser is no longer connected to Stacks.')
  if (!resp.ok) {
    let detail = null
    try {
      detail = (await resp.json()).detail
    } catch {
      // not JSON
    }
    throw new Error(typeof detail === 'string' ? detail : `Stacks returned an error (${resp.status}).`)
  }
  return resp.status === 204 ? null : resp.json()
}
