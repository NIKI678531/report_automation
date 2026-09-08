# ADR-0025: Month in Review exports use content-driven vertical flow

- Status: Accepted
- Date: 2026-09-08

## Context

The `3033-v2` editor stores Month in Review blocks as non-overlapping rectangles on a 12-column
grid. The HTML renderer previously converted every saved `h` unit into an 8 mm minimum row and
added a 3 mm gap for every grid track. Sparse blocks therefore reserved large empty areas, and a
long block in the left column could push a short right-column successor far below its content.

The editor still needs free drag and resize behaviour, but delivered HTML and PDF need to follow
the actual content closely. The approved product rule is that adjacent exported blocks leave no
more than two body-text lines of whitespace.

## Decision

For `3033-v2` Review blocks, canonical HTML compiles the saved rectangles into nested content-flow
containers. Horizontal position and width (`x`/`w`) and the ordering relationships inferred from
`y`/`h` are retained, while `y`/`h` no longer impose physical minimum height in the export.

The compiler separates independent columns before stacking vertical bands, so successors in one
column are not displaced by longer content in another. Adjacent flow containers use the existing
3 mm Review gap, which is below the two-line ceiling. Layouts that cannot be separated into nested
rows and columns fall back to deterministic `y`, `x`, `block_id` row flow so they remain compact
and non-overlapping.

Paged preview, PDF and continuous HTML share this canonical structure. The editor persistence
model and DOCX renderer are unchanged. PDF and HTML renderer versions are advanced so an existing
finalized document can produce a corrected artifact without mutating prior artifacts.

## Consequences

- Resizing a Review block still changes the editing canvas and helps define layout relationships,
  but unused vertical height is not reproduced in HTML or PDF.
- Side-by-side columns retain their widths and flow independently; content following the Review
  starts after the tallest resulting column.
- No API, document schema or database migration is required.
