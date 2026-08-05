const DEFAULT_EXPORT_FILENAME = 'thesis.docx'

function filenameFromContentDisposition(header: string | null): string {
  if (header === null) {
    return DEFAULT_EXPORT_FILENAME
  }
  const match = /filename="?([^"]+)"?/.exec(header)
  return match?.[1] ?? DEFAULT_EXPORT_FILENAME
}

/**
 * Downloads the project's export as a `.docx` file via the browser, per the backend's
 * `GET /projects/{id}/export` contract. Unlike this codebase's other services this is a
 * DOM side effect (object URL + temporary anchor click), not a pure JSON fetch, so it is
 * kept separate from `projectService`'s shared `request<T>` helper rather than forcing a
 * binary response through a JSON-parsing abstraction.
 */
export async function exportProject(projectId: string, institutionId: string | null): Promise<void> {
  const path = `/projects/${projectId}/export`
  const query = institutionId === null ? '' : `?institution_id=${encodeURIComponent(institutionId)}`
  const url = `${import.meta.env.VITE_API_BASE_URL}${path}${query}`

  const response = await fetch(url)

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Request to ${path} failed with status ${response.status}: ${body}`)
  }

  const blob = await response.blob()
  const filename = filenameFromContentDisposition(response.headers.get('Content-Disposition'))

  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}
