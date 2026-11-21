# Spec Delta

## Purpose

Turns the text of a resume into a structured `Resume` in which every bullet and skills line is the resume's own wording, and computes the candidate's total experience from the dates, so later matching can trust what it reads.

## ADDED Requirements

### Requirement: A resume is extracted into a structured model
The system SHALL turn the text of a stored resume into a structured resume with these parts: a summary (text, or none), skills (lines, each with the skill names it lists), experiences (job title, company, start month, end month, whether it is current, and bullets), education (institution, degree, field of study, start and end year), languages (name and the level as written, if any), certifications (name, issuer if any, date if any) and projects (name, bullets, technologies). Months are `YYYY-MM`. A part that the resume does not contain MUST be empty or none, never invented. The model MUST NOT contain contact details (name, e-mail, phone, address, links).

#### Scenario: Complete resume
- **WHEN** a resume with a summary, skills, two jobs, a degree, languages, a certification and a project is extracted
- **THEN** each of those parts is filled with what the resume says

#### Scenario: Resume without experience
- **WHEN** the resume of a student has no jobs
- **THEN** the experiences list is empty and the extraction succeeds

#### Scenario: Contact details are not extracted
- **WHEN** the resume contains an e-mail address, a phone number, a street address and a LinkedIn link
- **THEN** none of them appears anywhere in the extraction

### Requirement: Extracted bullets and skills lines are verbatim
Every experience bullet, project bullet and skills line in the extraction MUST be text that appears in the resume text. The comparison SHALL ignore differences in whitespace (including line breaks from the PDF layout), a leading bullet symbol, and Unicode compatibility variants, and MUST be exact otherwise (words, accents and case). When some items are not found in the resume text, the system MUST ask the model once to correct them. Items that are still not found after that MUST be dropped from the result, and the number dropped MUST be reported in the extraction warnings. Rewritten, translated, summarized or embellished text MUST never be kept.

#### Scenario: Verbatim bullets kept
- **WHEN** the model returns bullets that appear in the resume text, with different line breaks
- **THEN** all of them are kept, with the resume's wording

#### Scenario: Paraphrased bullet corrected
- **WHEN** the model returns one paraphrased bullet and corrects it when asked
- **THEN** the corrected, verbatim bullet is kept and no warning about dropped items is reported

#### Scenario: Paraphrase persists
- **WHEN** a bullet is still not in the resume text after the correction
- **THEN** that bullet is dropped, the other bullets are kept, and the warnings report one dropped item

#### Scenario: Translation is rejected
- **WHEN** the resume is in Portuguese and the model returns an English translation of a bullet
- **THEN** the translated bullet is not kept

### Requirement: Total experience is computed in code
The extraction MUST include the total experience in months and in years (months divided by 12, rounded to one decimal), computed from the experience dates by the application and never read from the model's answer. Each experience counts from its start month through its end month, both included; a current experience ends in the current month. Overlapping or adjacent experiences MUST NOT be counted twice: the total is the number of distinct calendar months covered. An experience without a start month, or without an end month that is not marked current, or whose end is before its start, MUST NOT count, and the warnings MUST say how many experiences were left out.

#### Scenario: Sequential jobs
- **WHEN** one job runs from 2018-01 to 2019-12 and another from 2020-03 to 2021-02
- **THEN** the total is 36 months, which is 3.0 years

#### Scenario: Overlapping jobs
- **WHEN** one job runs from 2020-01 to 2021-12 and a second from 2021-06 to 2022-05
- **THEN** the total is 29 months (2020-01 through 2022-05), not 36

#### Scenario: A job inside another
- **WHEN** a freelance job from 2020-03 to 2020-06 lies fully inside a job from 2020-01 to 2020-12
- **THEN** the total is 12 months

#### Scenario: Current job
- **WHEN** a job started in 2024-01 is marked current and the current month is 2024-06
- **THEN** it counts 6 months

#### Scenario: Incomplete dates
- **WHEN** a job has no start month
- **THEN** it is not counted and the warnings report one experience left out of the total

#### Scenario: The model's own total is ignored
- **WHEN** the model's answer contains a field with a total number of years
- **THEN** that value is not used

### Requirement: Results record how they were produced
Each extraction result SHALL record the name and version of the prompt, the LLM provider and model that produced it, the moment it was made, the warnings, and the total experience. Two results can therefore be compared and re-extracted when the prompt or model changes.

#### Scenario: Provenance recorded
- **WHEN** an extraction finishes with prompt `resume_extraction` version 1 and model `m`
- **THEN** the stored result says prompt `resume_extraction`, version 1, model `m`

### Requirement: Extraction does not depend on the provider
Extraction MUST work through the provider-independent LLM interface only. The validation, correction and dropping rules above MUST be applied by shared code, the same for every provider, and MUST NOT be implemented inside provider adapters. Weaker output from a small local model MUST end as dropped items, a warning or a typed failure, never as unvalidated data.

#### Scenario: Weak model output
- **WHEN** a model returns a mix of verbatim and paraphrased bullets in a way that cannot be fixed
- **THEN** the verbatim items are kept, the others are dropped with a warning, and nothing unvalidated is stored

#### Scenario: Unusable output
- **WHEN** the model's answers cannot be validated even after the repair attempt
- **THEN** the extraction fails with the invalid-output error and no partial result is stored

### Requirement: Resume text is not logged
Extraction MUST NOT write resume text, extracted bullets or prompts to logs; it MAY log identifiers, counts (items kept and dropped) and durations.

#### Scenario: Log content
- **WHEN** a resume is extracted
- **THEN** the log entries contain counts and ids and no text from the resume
