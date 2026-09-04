# Strict Image Relevance Filter Design

## Goal

Prevent unrelated page images, advertisements, navigation graphics, and weakly related results from being saved by the Naver image collector. Precision is more important than reaching the requested image count.

## Current Problem

The collector currently executes `document.querySelectorAll('img')` across the entire page. It accepts any non-data image rendered at least 80 by 80 pixels, then downloads candidates in DOM order. The collected title and surrounding source text are stored as metadata but are not used to decide relevance. The search URL also requests latest-date sorting.

This means page chrome and unrelated cards can enter the candidate list, while no later stage removes them based on the search keyword.

## Selected Approach

Use a two-layer strict filter:

1. Extract only images that belong to Naver image-viewer result cards, identified through the result grid's `data-image-viewer-list` metadata and each thumbnail's `data-image-viewer-img-id` rather than every image on the page.
2. Require normalized keyword evidence in the candidate's title, surrounding result-card text, or meaningful link text before accepting it.

No AI model, embedding service, image classifier, or new dependency is introduced.

## Relevance Rules

- Normalize the keyword and evidence text with Unicode case folding.
- Remove whitespace and punctuation so values such as `이준석국회의원` and `이준석 국회의원` compare consistently.
- Accept a candidate only when the complete normalized keyword occurs in normalized title/source evidence.
- Do not use the image URL itself as relevance evidence because CDN URLs often contain opaque identifiers.
- Reject candidates with empty textual evidence.
- Preserve first-occurrence order and thumbnail-URL deduplication.
- Never relax the relevance rule merely to reach the requested count.

## Search and Candidate Collection

- Use Naver's default image-search ordering rather than forcing `sort=date`; this aligns the request with relevance-focused collection.
- The browser extraction script must query image-viewer result grids and thumbnail IDs, not the entire document image set.
- Parse each result grid's metadata to obtain the matching title, source, and original link for each thumbnail ID.
- Return title, source text, thumbnail URL, and source link for each result card.
- If no result-card candidates can be extracted, raise a clear selector/result-structure error. Do not fall back to all page images.
- Continue scrolling while new candidates appear, up to the existing bounded number of rounds.
- Fix scroll progress detection so it compares candidate counts after the next extraction pass rather than immediately after scrolling.

## Logging and Output

- Log how many extracted candidates were excluded by the strict relevance rule.
- If fewer relevant images than requested are saved, keep the existing warning and explicitly state that strict filtering may produce fewer files.
- Save accepted files and metadata in the existing keyword folder format.
- Rejected candidates are not downloaded and do not appear as saved/failed metadata records.

## Error Handling

- Empty keywords and invalid limits retain existing errors.
- Missing result-card extraction produces an error explaining that the Naver page structure may have changed.
- A batch keyword that fails does not stop later keywords.
- Individual image download errors remain recorded and collection continues.

## Compatibility and Scope

- Keep CSV/XLSX upload, CP949/UTF-8 support, single-keyword mode, CLI arguments, output folders, image-size validation, and metadata formats compatible.
- Do not add a permissive fallback mode in this change.
- Do not perform computer-vision or face-recognition checks.
- Do not guarantee the requested image count when strict evidence is unavailable.

## Testing

Network-free automated tests cover:

- Text normalization across whitespace, punctuation, and case differences.
- Acceptance when normalized keyword occurs in title or source text.
- Rejection when evidence is empty or unrelated.
- Candidate filtering preserves order and removes unrelated results.
- Search URLs no longer force latest-date sorting.
- Page extraction uses result-card scope and does not query every page image.
- No-result-card behavior raises a clear error.
- Strict filtering may return fewer candidates than requested without adding unrelated fallbacks.
- Existing CSV, batch, image-size, CLI, and metadata tests continue to pass.

Live manual verification uses representative Korean keywords and checks downloaded folders plus metadata for relevance. Automated tests remain independent of Naver network access.

## Acceptance Criteria

- Page-wide advertisements, banners, navigation graphics, and unrelated large images are not accepted merely because they are visible.
- A candidate must be both part of an image result card and textually relevant to the complete normalized keyword.
- The collector saves fewer images instead of filling the folder with unrelated candidates.
- The log reports the number of relevance-filtered candidates and warns when strict filtering reduces the saved count.
- Existing input and output workflows remain operational.
