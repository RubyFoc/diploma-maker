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
    R -->|deepseek-v4-flash: parsing/structure| P[Parsing / Structure]
    R -->|deepseek-v4-pro: synthesis/reasoning| G[Generation / Synthesis]
    P --> S[Source Management + RAG]
    G --> S
    S -->|Qdrant similarity search| Q[(Qdrant: draft + literature embeddings)]
    S --> V{Citation verified verbatim?}
    V -->|yes| H[Humanizer Pipeline]
    V -->|no: retry alt. source| S
    V -->|no alt. found: reject citation| H
    H --> PL[Plagiarism / AI-detection Check]
    PL --> F[Formatting Engine]
    F -->|institution config| D[.docx Assembly]
    D --> DV[Diff Viewer]
    DV -->|accept: new version snapshot| C
    DV --> FB[Feedback Loop]
    FB -->|weight update| F
```
See ADR-0001 (citation retry/reject contract), ADR-0002 (Qdrant), ADR-0003 (router policy).

## Data Flow: Institution Config
```mermaid
flowchart LR
    Upload[User-uploaded sample/config] --> Parser[Formatting Parser]
    Dropdown[University dropdown selection] --> Mongo[(MongoDB: institution configs, ADR-0005 schema)]
    Parser --> Mongo
    Mongo --> F[Formatting Engine]
    Mongo -->|accuracy_weight| FB[Feedback Loop]
```

## Data Flow: Document Versioning & Diff Review
```mermaid
flowchart LR
    LLM[LLM-proposed edit] --> Draft[Draft version row]
    Draft -->|diff computed on read vs. current| DV[Diff Viewer]
    DV -->|accept| Accept[New immutable version snapshot]
    DV -->|reject| Discard[Draft discarded]
    Accept --> Mongo[(MongoDB: chapter versions, ADR-0004 model)]
```

_(Baseline updated 2026-08-04 per ADR-0001 through ADR-0005; extend further as epics are
implemented and diverge from these assumptions.)_
