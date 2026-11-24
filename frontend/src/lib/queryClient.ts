import { QueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Don't retry client errors (404 list not found, 403, etc.)
        retry: (failureCount, error) => {
          if (isAxiosError(error) && error.response && error.response.status < 500) {
            return false
          }
          return failureCount < 2
        },
      },
    },
  })
}
