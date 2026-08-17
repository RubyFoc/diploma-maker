const URL_PATTERN = /https?:\/\/[^\s]+[^\s.,;:!?)\]]/g

/**
 * Renders `text` with any `http(s)://` URLs turned into clickable links (user request: required
 * sources often carry a source URL, e.g. a GOST-style citation's `URL: ...` segment, and pasting
 * one in as plain text left it unclickable).
 */
export function Linkify({ text }: { text: string }) {
  const parts = text.split(URL_PATTERN)
  const urls = text.match(URL_PATTERN) ?? []
  return (
    <>
      {parts.map((part, index) => (
        <span key={index}>
          {part}
          {index < urls.length && (
            <a href={urls[index]} target="_blank" rel="noopener noreferrer">
              {urls[index]}
            </a>
          )}
        </span>
      ))}
    </>
  )
}
