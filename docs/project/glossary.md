# Glossary

| Term | Definition |
| --- | --- |
| Institution config | JSON document in MongoDB describing a university's formatting rules (margins, fonts, citation style). |
| Humanization | Post-processing pass that breaks statistically regular LLM text patterns while preserving academic register. |
| Zero-hallucination citation | A citation whose quoted text is verified verbatim against the retrieved/uploaded source document. |
| Cold cache | Compressed summary + RAG retrieval of prior chapters, avoiding full re-read on each edit. |
| Fast/heavy tier | DeepSeek model routing: cheap model for structure/parsing, expensive model for reasoning/synthesis. |
| Diff viewer | Git-style red/green change preview requiring explicit accept/reject before text is applied. |
