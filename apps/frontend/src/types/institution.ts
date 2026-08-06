// Backend API contract type for the formatting/institution-configs endpoints (TASK-E10-1).
// Deliberately typed with only the fields this app's UI uses (see ADR-0005 for the full shape).

export interface InstitutionSummary {
  institution_id: string
  institution_name: string
}

export interface MarginsMm {
  top: number
  bottom: number
  left: number
  right: number
}

export interface PageConfig {
  size: 'A4' | 'Letter'
  orientation: 'portrait' | 'landscape'
  margins_mm: MarginsMm
}

export interface FontConfig {
  family: string
  size_pt: number
  line_spacing: number
}

// Backend model is `extra: "allow"` (an open dict) — only the fields the preview
// styling uses are named here; anything else the backend sends is ignored.
export interface HeadingStyle {
  font_size_pt?: number
  bold?: boolean
  [key: string]: unknown
}

export interface Headings {
  h1: HeadingStyle
  h2: HeadingStyle
  h3: HeadingStyle
}

export interface InstitutionConfig {
  institution_id: string
  institution_name: string
  page: PageConfig
  font: FontConfig
  headings: Headings
}
