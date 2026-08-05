import { describe, expect, it } from 'vitest'
import { diffLines } from './diff'

describe('diffLines', () => {
  it('returns a single unchanged segment when nothing changed', () => {
    const text = 'line one\nline two\nline three'
    expect(diffLines(text, text)).toEqual([
      { type: 'unchanged', lines: ['line one', 'line two', 'line three'] },
    ])
  })

  it('detects a pure addition', () => {
    const before = 'line one\nline two'
    const after = 'line one\nline two\nline three'
    expect(diffLines(before, after)).toEqual([
      { type: 'unchanged', lines: ['line one', 'line two'] },
      { type: 'added', lines: ['line three'] },
    ])
  })

  it('detects a pure removal', () => {
    const before = 'line one\nline two\nline three'
    const after = 'line one\nline two'
    expect(diffLines(before, after)).toEqual([
      { type: 'unchanged', lines: ['line one', 'line two'] },
      { type: 'removed', lines: ['line three'] },
    ])
  })

  it('detects mixed additions and removals', () => {
    const before = 'keep me\nremove me\nalso keep'
    const after = 'keep me\nadded line\nalso keep'
    expect(diffLines(before, after)).toEqual([
      { type: 'unchanged', lines: ['keep me'] },
      { type: 'removed', lines: ['remove me'] },
      { type: 'added', lines: ['added line'] },
      { type: 'unchanged', lines: ['also keep'] },
    ])
  })

  it('treats an empty-to-nonempty change as a pure addition', () => {
    const after = 'brand new paragraph\nsecond line'
    expect(diffLines('', after)).toEqual([
      { type: 'added', lines: ['brand new paragraph', 'second line'] },
    ])
  })

  it('treats a nonempty-to-empty change as a pure removal', () => {
    const before = 'old paragraph\nsecond line'
    expect(diffLines(before, '')).toEqual([
      { type: 'removed', lines: ['old paragraph', 'second line'] },
    ])
  })

  it('returns no segments when both inputs are empty', () => {
    expect(diffLines('', '')).toEqual([])
  })
})
