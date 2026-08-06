import { useEffect, useState } from 'react'
import { getInstitutionConfig } from '../services/institutionService'
import type { InstitutionConfig } from '../types/institution'

export interface UseInstitutionConfigResult {
  config: InstitutionConfig | null
  isLoading: boolean
}

/**
 * Fetches the formatting config for the project's selected institution, so the live
 * preview/diff view can render page dimensions/fonts/heading styles that match the
 * target university. Failures (404 for an unknown/not-yet-configured institution,
 * network errors, ...) are swallowed to a `null` config rather than thrown: this is a
 * visual enhancement, not a hard dependency for the preview to function.
 */
export function useInstitutionConfig(institutionId: string | null): UseInstitutionConfigResult {
  const [config, setConfig] = useState<InstitutionConfig | null>(null)
  const [isLoading, setIsLoading] = useState(institutionId !== null)

  useEffect(() => {
    if (institutionId === null) {
      setConfig(null)
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    getInstitutionConfig(institutionId)
      .then((result) => {
        if (!cancelled) {
          setConfig(result)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setConfig(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [institutionId])

  return { config, isLoading }
}
