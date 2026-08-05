"""TOC (table of contents) upload/parsing package (TASK-E10-2).

Parses an uploaded `.docx` file into an ordered list of chapter titles. Does not persist
anything or touch MongoDB/FastAPI — `projects.router` wires `toc.parser.parse_toc` into the
HTTP layer and calls `projects.service.create_chapter` once per parsed title. The later,
separate TASK-E10-3 is responsible for inserting a newly generated chapter between existing
ones; this package only extracts the chapter list from the upload.
"""
