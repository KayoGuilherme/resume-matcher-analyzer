# Spec Delta

## Purpose

Extracts plain text and document facts from PDF and DOCX resumes and reports, as a list of issues, the formatting that makes a resume hard for an ATS to read.

## ADDED Requirements

### Requirement: Text is extracted from PDF and DOCX
The system SHALL extract the plain text of a PDF (all pages, in the order a simple left-to-right, top-to-bottom reader sees it, pages separated by a line break) and of a DOCX (body paragraphs and table cells in document order; header and footer content is not part of the text). Extraction MUST NOT interpret or rewrite the content: the text is what an ATS would get. The system SHALL also determine the document facts: the page count (exact for PDF; for DOCX the value stored in the document properties when present, otherwise unknown), the character count and the word count of the text.

#### Scenario: One-column PDF
- **WHEN** a one-column PDF with known content is parsed
- **THEN** the extracted text contains that content in reading order and the page count equals the number of pages

#### Scenario: DOCX with a table
- **WHEN** a DOCX with a paragraph, a table and another paragraph is parsed
- **THEN** the text contains the three parts in that order

#### Scenario: DOCX page count unknown
- **WHEN** a DOCX has no page count in its properties
- **THEN** the page count is unknown (null) and the page-based checks are skipped

#### Scenario: Two-column PDF reads as an ATS would
- **WHEN** a two-column PDF is parsed
- **THEN** the text is in the order produced by reading line by line across the page, not column by column

### Requirement: Parsing problems are reported as typed errors
The system SHALL report a document that cannot be opened (corrupted, truncated or password-protected) as a typed error that carries no document content, not as an unhandled failure.

#### Scenario: Truncated PDF
- **WHEN** a truncated PDF is parsed
- **THEN** the parser reports that the document is unreadable and the message contains no text from the file

### Requirement: The quality report lists issues with code, severity and message
Each parsed document SHALL get a quality report: a list of issues, each with a stable `code`, a `severity` (`critical`, `warning` or `info`) and a plain-language `message` that says what the ATS problem is and how to fix it. A resume with no problems has an empty list. Issues are ordered by severity (critical first, then warning, then info) and then by code. A message MUST NOT contain text from the resume.

#### Scenario: Clean resume
- **WHEN** a clean one-column PDF with experience, education and skills sections and two pages is checked
- **THEN** the report is an empty list

#### Scenario: Several problems
- **WHEN** a document has a table and no skills section
- **THEN** the report lists both issues, each with code, severity and message, ordered as specified

### Requirement: Image-only documents are detected
The system SHALL report the issue `image_only_pdf` with severity `critical` when a PDF contains images but no extractable text.

#### Scenario: Scanned PDF
- **WHEN** a PDF whose pages are only images is checked
- **THEN** the report contains `image_only_pdf` with severity `critical`

### Requirement: Multi-column layout is detected
The system SHALL report the issue `multi_column` with severity `warning` when the text of a PDF page is arranged in two or more side-by-side columns (substantial text on both sides of a vertical band that holds no text), or when a DOCX section is set to more than one column.

#### Scenario: Two-column PDF
- **WHEN** a PDF with a left column and a right column of text is checked
- **THEN** the report contains `multi_column`

#### Scenario: One column
- **WHEN** a one-column PDF is checked
- **THEN** the report does not contain `multi_column`

#### Scenario: Two-column DOCX
- **WHEN** a DOCX whose section is set to two columns is checked
- **THEN** the report contains `multi_column`

### Requirement: Tables are detected
The system SHALL report the issue `tables` with severity `warning` when the document contains a table (a ruled table on a PDF page, or a table in the DOCX body).

#### Scenario: DOCX with a table
- **WHEN** a DOCX with a table is checked
- **THEN** the report contains `tables`

#### Scenario: No tables
- **WHEN** a document without tables is checked
- **THEN** the report does not contain `tables`

### Requirement: Content in header or footer is detected
The system SHALL report the issue `header_footer_content` with severity `warning` when text sits in the header or footer of the document: for a DOCX, a non-empty header or footer; for a PDF, text within the top or bottom 7% of the page height.

#### Scenario: DOCX with contact details in the header
- **WHEN** a DOCX whose header contains text is checked
- **THEN** the report contains `header_footer_content`

#### Scenario: PDF with text in the bottom margin band
- **WHEN** a PDF page has text within the bottom 7% of its height
- **THEN** the report contains `header_footer_content`

### Requirement: Very low text density is detected
The system SHALL report the issue `low_text_ratio` with severity `warning` when the page count is known and the document has fewer than 500 characters of text per page on average, but has some text. A document with no text is handled by the rejection rules of `resume-management`.

#### Scenario: Mostly graphics
- **WHEN** a 2-page PDF with only 300 characters of text in total is checked
- **THEN** the report contains `low_text_ratio`

#### Scenario: Normal density
- **WHEN** a 1-page PDF with 2,000 characters of text is checked
- **THEN** the report does not contain `low_text_ratio`

### Requirement: Icon and special glyph bullets are detected
The system SHALL report the issue `special_glyph_bullets` with severity `warning` when lines of the text begin with an icon or special symbol (a private-use character or a symbol-other character such as ➢, ✔ or ■) instead of a standard bullet (`•`, `-`, `–` or `*`).

#### Scenario: Arrow bullets
- **WHEN** a document whose list items begin with `➢` is checked
- **THEN** the report contains `special_glyph_bullets`

#### Scenario: Standard bullets
- **WHEN** a document whose list items begin with `•` or `-` is checked
- **THEN** the report does not contain `special_glyph_bullets`

### Requirement: Missing standard sections are detected
The system SHALL report `missing_experience_section`, `missing_education_section` and `missing_skills_section`, each with severity `warning`, when the text has no line that is a heading of that section. A heading is a line that consists only of one of the recognized words, ignoring case, accents, and a trailing colon. English and Portuguese headings MUST be recognized, at least: experience (`experience`, `work experience`, `professional experience`, `experiência`, `experiência profissional`), education (`education`, `academic background`, `educação`, `formação`, `formação acadêmica`) and skills (`skills`, `technical skills`, `habilidades`, `competências`, `tecnologias`).

#### Scenario: Portuguese headings
- **WHEN** a document has the headings `Experiência Profissional`, `Formação Acadêmica` and `Competências`
- **THEN** no missing-section issue is reported

#### Scenario: No skills heading
- **WHEN** a document has experience and education headings but no skills heading
- **THEN** the report contains `missing_skills_section` and neither of the other two

### Requirement: Long resumes are flagged
The system SHALL report the issue `too_many_pages` with severity `info` when the page count is known and greater than 3.

#### Scenario: Four pages
- **WHEN** a 4-page PDF is checked
- **THEN** the report contains `too_many_pages`

#### Scenario: Three pages
- **WHEN** a 3-page PDF is checked
- **THEN** the report does not contain `too_many_pages`
