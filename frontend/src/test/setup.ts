import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import { useAuthStore } from '@/stores/auth'

// Tests start signed out, as if restoring the session at page load found none
beforeEach(() => useAuthStore.setState({ token: null, status: 'signed_out' }))

afterEach(() => {
  cleanup()
  localStorage.clear()
  sessionStorage.clear()
})
