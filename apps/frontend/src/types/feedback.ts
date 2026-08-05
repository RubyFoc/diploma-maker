// Backend API contract types for feedback signals (TASK-E09-1).
// Kept separate from feedbackService.ts so other modules can import the shapes
// without pulling in fetch logic, mirroring types/project.ts's split.

export type SignalType = 'approve' | 'reject' | 'edit'

export interface FeedbackSignal {
  id: string
  institution_id: string
  chapter_id: string
  version_id: string
  signal_type: SignalType
  created_at: string
}
