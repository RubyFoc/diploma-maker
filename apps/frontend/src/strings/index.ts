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
  chatInputPlaceholder: 'Describe what you want this chapter to say...',
  chatSendButton: 'Send',
  chatDraftReadyMessage: 'Draft ready — review it in the document panel.',
  chatGenerationErrorMessage: 'Generation failed. Please try again.',
  defaultChapterTitle: 'Chapter 1',
  chapterContentEmpty: 'No accepted content yet.',
} as const
