# Product Requirements Document (PRD): AI-Powered Academic Paper Generation Platform

## 1. Product Overview
**Concept:** A web-based SaaS application designed to assist students and researchers in assembling, drafting, and formatting academic papers (theses, dissertations, term papers) utilizing DeepSeek LLMs. The platform automates routine academic workflows: sourcing up-to-date literature, strictly adhering to university formatting standards, successfully bypassing AI detectors and plagiarism checkers, and seamlessly compiling the final `.docx` document.

**Core Value Proposition (USP):**
Users maintain absolute control over the generation process via an interactive chat interface and a GitHub-style "diff" text preview. The system guarantees zero hallucinated citations, learns and adapts to specific university formatting rules, processes user-provided formatting examples, and produces highly academic text that easily passes institutional originality checks.

---

## 2. Key Performance Indicators (KPIs) & Constraints
*   **Originality (Anti-Plagiarism Target):** Minimum **80%** uniqueness on standard institutional checkers.
*   **AI-Detection Score:** Maximum **5%** AI-generated probability.
*   **Tone & Stylistics:** Strict scientific/academic language. The output must undergo "academic humanization" to mimic human scholarly writing.
*   **Cost-Efficiency:** Token consumption must be aggressively optimized via intelligent model routing and context caching.

---

## 3. Functional Requirements

### 3.1 LLM Routing & Context Optimization (Token Efficiency)
*   **Cold Cache & Stateful Sessions:** The system must remember previously uploaded drafts or generated chapters. If a user edits "Chapter 2", the system does not re-read "Chapter 1" and "Chapter 3" token-by-token. Instead, it utilizes compressed summaries and Vector DB (RAG) retrieval of the user's document to maintain context.
*   **Dynamic Model Routing:**
    *   *Fast/Economical Models (e.g., DeepSeek-V3/Flash):* Used for analyzing document structure, parsing tables of contents, information retrieval, and Markdown formatting.
    *   *Heavy/Expensive Models (e.g., DeepSeek-R1/Pro):* Exclusively reserved for complex academic reasoning, synthesizing conclusions, and generating complex mathematical data or tables.
*   **Media Placeholders (MVP Phase):** Image generation is deferred post-MVP. The LLM will analyze the context and insert semantic text placeholders where diagrams/images are logically required (e.g., `[PLACEHOLDER: Insert Database Architecture Diagram Here]`).

### 3.2 Source Management & Fact-Checking
*   **Recency Filter:** The built-in search agent is restricted to retrieving academic articles and books published **within the last 5 years**.
*   **User-Uploaded Literature:** Users can upload custom PDFs or specify exact authors/books. The LLM must prioritize these sources. The 5-year restriction is bypassed for user-uploaded content.
*   **Geo-Fencing & Filtering:** Support for filtering academic databases by region (e.g., exclusively searching databases in specific countries like RU or BY).
*   **Zero-Hallucination Quote Verification (RAG):** Every generated citation must be cross-referenced with the retrieved or uploaded source document to ensure an exact verbatim match.

### 3.3 Anti-Plagiarism & Academic Humanization (Killer Feature)
*   **Proprietary Checker:** An internal module to pre-check text against plagiarism and AI fingerprints before presenting it to the user.
*   **Academic Humanizer Pipeline:** Post-processing of the LLM-generated text. The goal is to break standard LLM patterns (perfectly symmetrical paragraph lengths, repetitive transition words) while maintaining strict academic formatting (passive voice, complex syntax, domain-specific terminology).

### 3.4 Formatting, Configuration & Export
*   **Dynamic Formatting by Example:** Users can upload a **sample formatted document** or **specific bibliography/reference formatting rules**. The system must parse these examples and extract styling rules (margins, fonts, citation styles like APA/GOST).
*   **Markdown to Docx Engine:** The LLM internally outputs structured Markdown. 
*   **Institution Configurations (MongoDB):** JSON configurations containing precise formatting rules for specific universities are stored in the database. 
*   **Final Assembly:** The backend maps the Markdown text against the selected JSON university config (or the user's uploaded example config) and generates a native, fully styled `.docx` file.

### 3.5 System Learning & RLHF (Crowdsourced Standards)
*   **Feedback Loop:** Users rate the accuracy of the formatting and text generation (Approve/Reject/Edit).
*   **Weight Adjustments:** If a user corrects a formatting error for a specific university template (e.g., fixing margin sizes for "University X"), these corrections increase the template's accuracy weight. Over time, the platform crowdsources perfect global formatting templates for major universities.

### 3.6 User Interface (UI) & User Experience (UX)
*   **Interactive Live Chat:** The workspace is split between an AI chat and a document viewer. Users can prompt specific micro-edits ("Expand the second bullet point in Section 1.2").
*   **Smart Content Insertion:** The system understands the Table of Contents. If Chapters 1 and 3 are finalized, it inherently knows to generate and insert Chapter 2 exactly between them.
*   **Git-like Diff Viewer:** Text modifications are presented via a visual diff (red for deletions, green for additions). Users must explicitly accept or reject changes.
*   **Live Preview:** Real-time WYSIWYG preview of the final document with applied formatting prior to downloading.

---

## 4. Architecture & Infrastructure

| Component | Recommended Technology / Stack |
| :--- | :--- |
| **LLM Provider** | DeepSeek API (Dynamic routing between Flash/Pro tiers) |
| **Primary Database** | MongoDB (Document storage for user profiles, JSON formatting configs) |
| **Vector Database (RAG)**| Pinecone / Qdrant / Milvus (For caching drafts and semantic search of academic papers) |
| **Document Processing** | `python-docx` (or similar robust library for advanced `.docx` generation) |
| **Frontend Framework** | React / Vue.js (Required for managing complex states, diff viewers, and live chat) |

---

## 5. Monetization & Billing Architecture (Future-Proofing)
*   **Core Entities:** Database schema must include `User`, `Wallet`, and `Transaction` tables from day one.
*   **Freemium Model:** New accounts receive an initial allocation of `N` tokens (e.g., equivalent to 10,000 DeepSeek tokens).
*   **Usage-Based Accounting:** Token deductions are calculated dynamically based on the specific models invoked (cheap vs. expensive) and the pipeline operations utilized (search, generation, humanization).

---

## 6. Target User Journey (MVP)
1. User registers and selects their University from a dropdown (or uploads a syllabus / formatting example / reference guidelines).
2. User uploads their existing draft, table of contents, and specifies mandatory authors/literature.
3. User prompts the AI via chat to draft a specific missing section.
4. The system executes the pipeline: Searches for recent articles -> Generates text -> Verifies citations -> "Humanizes" the academic tone -> Scans for AI/Plagiarism.
5. The output is displayed in the Git-like Diff viewer.
6. User reviews, makes manual adjustments (which trains the system's formatting rules), and accepts the diff.
7. User downloads the final compiled `.docx` file (containing text placeholders for future images).
