/**
 * Line-based text diff for chapter-level prose comparisons (TASK-E08-2).
 *
 * Computes a diff between two strings by treating each `\n`-separated line as
 * the unit of comparison and finding the longest common subsequence (LCS) of
 * lines shared between them. Lines outside that subsequence are reported as
 * removed (present only in `before`) or added (present only in `after`).
 *
 * Per ADR-0004, this diff is computed on read from two plain content strings
 * (current accepted version vs. a pending draft version) rather than being
 * persisted as its own structure, so this module has no dependency on any
 * version/chapter data model — it operates on raw strings only.
 */

export type DiffSegmentType = 'unchanged' | 'added' | 'removed'

export interface DiffSegment {
  type: DiffSegmentType
  lines: string[]
}

function toLines(text: string): string[] {
  return text === '' ? [] : text.split('\n')
}

/**
 * Builds the LCS length table for two line arrays.
 *
 * `table[i][j]` holds the length of the longest common subsequence of
 * `before[i:]` and `after[j:]`. Using the "subsequence from position i/j to
 * the end" convention (rather than "prefix up to i/j") makes the forward
 * backtrack below read in the same order as the input lines.
 */
function buildLcsTable(before: string[], after: string[]): number[][] {
  const n = before.length
  const m = after.length
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i][j] =
        before[i] === after[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }

  return table
}

/**
 * Computes a line-based diff between `before` and `after`.
 *
 * @param before - the current accepted version's content
 * @param after - the pending draft version's content
 * @returns an ordered list of segments; consecutive lines of the same type
 *   are merged into a single segment so the UI can render them as one block.
 */
export function diffLines(before: string, after: string): DiffSegment[] {
  const beforeLines = toLines(before)
  const afterLines = toLines(after)
  const table = buildLcsTable(beforeLines, afterLines)

  const segments: DiffSegment[] = []
  const push = (type: DiffSegmentType, line: string) => {
    const last = segments[segments.length - 1]
    if (last && last.type === type) {
      last.lines.push(line)
    } else {
      segments.push({ type, lines: [line] })
    }
  }

  let i = 0
  let j = 0
  const n = beforeLines.length
  const m = afterLines.length

  while (i < n && j < m) {
    if (beforeLines[i] === afterLines[j]) {
      push('unchanged', beforeLines[i])
      i += 1
      j += 1
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      push('removed', beforeLines[i])
      i += 1
    } else {
      push('added', afterLines[j])
      j += 1
    }
  }
  while (i < n) {
    push('removed', beforeLines[i])
    i += 1
  }
  while (j < m) {
    push('added', afterLines[j])
    j += 1
  }

  return segments
}
