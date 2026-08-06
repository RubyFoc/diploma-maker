import { describe, expect, it } from 'vitest'
import { getHeadingStyle, getPageStyle } from './institutionPageStyle'
import type { InstitutionConfig } from '../types/institution'

const config: InstitutionConfig = {
  institution_id: 'i1',
  institution_name: 'Test University',
  page: {
    size: 'A4',
    orientation: 'portrait',
    margins_mm: { top: 20, bottom: 20, left: 30, right: 15 },
  },
  font: { family: 'Arial', size_pt: 11, line_spacing: 2 },
  headings: {
    h1: { font_size_pt: 18, bold: true },
    h2: {},
    h3: {},
  },
}

describe('getPageStyle', () => {
  it('returns A4/Times-New-Roman defaults when config is null', () => {
    const style = getPageStyle(null)

    expect(style.width).toBe('210mm')
    expect(style.height).toBe('297mm')
    expect(style.fontFamily).toContain('Times New Roman')
    expect(style.fontSize).toBe('12pt')
  })

  it('maps an institution config onto page width/padding/font', () => {
    const style = getPageStyle(config)

    expect(style.width).toBe('210mm')
    expect(style.height).toBe('297mm')
    expect(style.padding).toBe('20mm 15mm 20mm 30mm')
    expect(style.fontFamily).toBe('Arial')
    expect(style.fontSize).toBe('11pt')
    expect(style.lineHeight).toBe(2)
  })

  it('swaps width/height for landscape orientation', () => {
    const landscapeConfig: InstitutionConfig = {
      ...config,
      page: { ...config.page, orientation: 'landscape' },
    }

    const style = getPageStyle(landscapeConfig)

    expect(style.width).toBe('297mm')
    expect(style.height).toBe('210mm')
  })

  it('uses Letter dimensions when size is Letter', () => {
    const letterConfig: InstitutionConfig = {
      ...config,
      page: { ...config.page, size: 'Letter' },
    }

    const style = getPageStyle(letterConfig)

    expect(style.width).toBe('215.9mm')
    expect(style.height).toBe('279.4mm')
  })
})

describe('getHeadingStyle', () => {
  it('returns an empty style when config is null', () => {
    expect(getHeadingStyle(null, 1)).toEqual({})
  })

  it('returns font size/weight for a heading level with configured values', () => {
    expect(getHeadingStyle(config, 1)).toEqual({ fontSize: '18pt', fontWeight: 'bold' })
  })

  it('returns an empty style for a heading level with no configured values', () => {
    expect(getHeadingStyle(config, 2)).toEqual({})
  })
})
