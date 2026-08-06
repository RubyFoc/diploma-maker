/**
 * Maps an `InstitutionConfig` onto CSS for a "paper sheet" page element.
 *
 * Uses `mm`/`pt` CSS units directly instead of converting to pixels: browsers already
 * do that math per the current DPI, so hand-rolling it here would just be a second,
 * possibly-diverging source of truth.
 */
import type { CSSProperties } from 'react'
import type { InstitutionConfig } from '../types/institution'

const A4_MM = { width: 210, height: 297 }
const LETTER_MM = { width: 215.9, height: 279.4 }

const DEFAULT_MARGIN_MM = 25
const DEFAULT_FONT_FAMILY = "'Times New Roman', Georgia, serif"
const DEFAULT_FONT_SIZE_PT = 12
const DEFAULT_LINE_SPACING = 1.5

export function getPageStyle(config: InstitutionConfig | null): CSSProperties {
  if (!config) {
    return {
      width: `${A4_MM.width}mm`,
      height: `${A4_MM.height}mm`,
      padding: `${DEFAULT_MARGIN_MM}mm`,
      fontFamily: DEFAULT_FONT_FAMILY,
      fontSize: `${DEFAULT_FONT_SIZE_PT}pt`,
      lineHeight: DEFAULT_LINE_SPACING,
    }
  }

  const dimensions = config.page.size === 'Letter' ? LETTER_MM : A4_MM
  const { width, height } =
    config.page.orientation === 'landscape'
      ? { width: dimensions.height, height: dimensions.width }
      : dimensions
  const { top, right, bottom, left } = config.page.margins_mm

  return {
    width: `${width}mm`,
    height: `${height}mm`,
    padding: `${top}mm ${right}mm ${bottom}mm ${left}mm`,
    fontFamily: config.font.family,
    fontSize: `${config.font.size_pt}pt`,
    lineHeight: config.font.line_spacing,
  }
}

export function getHeadingStyle(config: InstitutionConfig | null, level: 1 | 2 | 3): CSSProperties {
  const heading = config?.headings[`h${level}` as 'h1' | 'h2' | 'h3']
  if (!heading) {
    return {}
  }

  const style: CSSProperties = {}
  if (heading.font_size_pt !== undefined) {
    style.fontSize = `${heading.font_size_pt}pt`
  }
  if (heading.bold !== undefined) {
    style.fontWeight = heading.bold ? 'bold' : 'normal'
  }
  return style
}
