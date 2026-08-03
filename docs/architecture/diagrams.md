# Architecture & Flow Diagrams

## Update Policy
Update this file whenever a pipeline stage, data flow, or critical user workflow changes.
Diagrams here are the canonical reference; keep source files (if any) alongside their rendered
Mermaid block.

## Pipeline Flow (MVP)

```mermaid
flowchart LR
    U[User] -->|chat prompt| C[Chat Interface]
    C --> R[LLM Router]
    R -->|fast tier| P[Parsing / Structure]
    R -->|heavy tier| G[Generation / Synthesis]
    P --> S[Source Management + RAG]
    G --> S
    S --> V[Citation Verification]
    V --> H[Humanizer Pipeline]
    H --> F[Formatting Engine]
    F -->|institution config| D[.docx Assembly]
    D --> DV[Diff Viewer]
    DV -->|accept/reject| C
    DV --> FB[Feedback Loop]
    FB -->|weight update| F
```

## Data Flow: Institution Config
```mermaid
flowchart LR
    Upload[User-uploaded sample/config] --> Parser[Formatting Parser]
    Dropdown[University dropdown selection] --> Mongo[(MongoDB: institution configs)]
    Parser --> Mongo
    Mongo --> F[Formatting Engine]
```

_(No diagrams exist yet beyond this MVP baseline — extend as epics are implemented.)_
