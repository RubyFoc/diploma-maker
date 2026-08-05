// Flat UI-copy map. Placeholder for full RU/EN i18n (see frontend-requirements.md);
// keeps literal copy out of JSX so swapping in a real i18n library later is a small change.
export const strings = {
  appTitle: 'diploma-maker',
  chatPanelTitle: 'AI Chat',
  chatEmpty: 'No messages yet.',
  documentPanelTitle: 'Document',
  documentEmpty: 'No chapters yet. Start a new project to begin.',
  newProjectButton: 'New Project',
  diffViewerTitle: 'Pending Edit',
  diffAcceptButton: 'Accept',
  diffRejectButton: 'Reject',
  diffEmpty: 'No changes.',
  simulatePendingDraftButton: 'Simulate pending draft',
} as const
