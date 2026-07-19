# CSV Upload Image Search Design

## Goal

Make CSV batch image search explicit and dependable in the desktop GUI. A user selects a one-column CSV file, verifies that its search terms were recognized, and starts image collection for every valid term in file order.

## Input Contract

- The input file is a CSV file.
- The first column header must be `keyword`, ignoring surrounding whitespace and letter case.
- Search terms begin on row 2.
- Empty keyword cells are skipped.
- Valid terms retain their original file order.
- A repeated term is processed only once because repeated collection would target and overwrite the same keyword folder.
- A file without a `keyword` header or without any valid terms is rejected with a clear message.

## GUI Behavior

The existing batch section remains the primary workflow and is relabeled to make the sequence clear:

1. The user selects a CSV file with an upload/select button.
2. The application immediately parses and validates the file.
3. The log reports the number of valid unique search terms and previews the first term.
4. The user starts collection with an explicit image-search button.
5. While collection runs, run buttons remain disabled and progress is written to the log.
6. At completion, the log reports success and failure counts.

Selecting a file does not automatically start network or browser activity. This prevents accidental searches when the wrong file is chosen.

## Data Flow

1. Read the selected CSV using UTF-8 with optional BOM support.
2. Resolve the `keyword` header from the first row.
3. Normalize each keyword by trimming surrounding whitespace.
4. Skip empty values and later duplicates while retaining first-occurrence order.
5. Cache the validated terms in the GUI so the displayed preview and executed batch use the same input.
6. For each term, invoke the existing Naver image collection flow.
7. Save images and metadata under `downloaded_images/<safe_keyword>/`, or the selected output root.
8. Continue after individual keyword failures and summarize the batch.

## Error Handling

- Reject a missing or unreadable file before starting a background collection thread.
- Reject a CSV whose first row does not contain the `keyword` header.
- Reject a CSV with no valid keyword rows.
- Display validation errors in a dialog and also retain a useful log message.
- If one keyword fails during collection, record that failure and continue with later terms.
- Preserve the existing output files and behavior for successful keyword searches.

## Compatibility and Scope

- Keep single-keyword GUI and CLI workflows unchanged.
- Keep the existing image limit, minimum thumbnail size, browser visibility, output directory, and metadata behavior.
- CSV is the required upload format for this change. Existing XLSX support may remain available but is not expanded.
- Do not add drag-and-drop, automatic search on file selection, or a new dependency.

## Testing

Automated, network-free tests cover:

- A `keyword` CSV whose second and later rows are returned in order.
- Empty rows are skipped.
- Duplicate terms are processed once.
- UTF-8 BOM and harmless header whitespace/case are accepted.
- Missing headers and files without valid terms raise clear validation errors.
- GUI file selection stores validated terms and emits a preview without starting collection.
- GUI batch start uses the validated terms and existing batch runner.

Fresh full-suite verification is required after implementation. Live Naver access remains a manual integration check because automated tests should not depend on the external site.

## Acceptance Criteria

- A CSV whose first row is `keyword` and whose second row is `이준석국회의원` is accepted.
- Every non-empty unique keyword from row 2 onward is searched in input order.
- Each keyword writes images and metadata into its own output folder.
- File selection visibly confirms the parsed term count and first term.
- Search begins only when the user presses the batch image-search button.
- A failed term does not prevent later terms from being processed.
- Existing single-search and CLI behavior remains compatible.
