import { isAxiosError } from 'axios'

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

/**
 * Turn an API error into a message for the user. Uses the server's `detail`
 * (a string for most errors, a list of field issues for 422s) when present.
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return fallback
  if (!error.response) return 'The Stacks API could not be reached. Check your connection and try again.'

  const detail = (error.response.data as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = (detail as ValidationIssue[])
      .map((issue) => {
        const field = issue.loc?.filter((part) => part !== 'body').join('.')
        const msg = (issue.msg ?? '').replace(/^Value error, /, '')
        return field ? `${field.replace(/_/g, ' ')}: ${msg}` : msg
      })
      .filter(Boolean)
    if (messages.length) return messages.join(' · ')
  }
  return fallback
}
