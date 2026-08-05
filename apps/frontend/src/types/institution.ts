// Backend API contract type for the formatting/institution-configs endpoints (TASK-E10-1).
// Deliberately typed with only the fields this app's UI uses (see ADR-0005 for the full shape).

export interface InstitutionSummary {
  institution_id: string
  institution_name: string
}
