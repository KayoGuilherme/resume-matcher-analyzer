# Spec Delta

## Purpose

Tells the candidate which of the job's ATS keywords appear literally in the resume text and which do not, because an applicant tracking system scans for the words themselves, not for their meaning.

## ADDED Requirements

### Requirement: ATS keywords are checked literally against the resume text
The result of an analysis SHALL contain a keyword coverage: for every ATS keyword of the job, in the order of the job's list, whether it appears in the resume's text. The result MUST list the `found` keywords, each with the `matched_text` as written in the resume, and the `missing` keywords. A keyword appears when it, or one of its known aliases (for example `kubernetes` and `k8s`), is found as a whole term in the resume text, ignoring case and accents; the characters before and after it MUST NOT be letters, digits, `+` or `#`. Only the resume counts: the profile and the requirement synonyms of the job are not searched. The coverage MUST NOT be a percentage or a score.

#### Scenario: Found and missing
- **WHEN** the job's ATS keywords are `python`, `kubernetes` and `terraform` and the resume says "Python, K8s, Docker"
- **THEN** `found` holds `python` (matched as `Python`) and `kubernetes` (matched as `K8s`), and `missing` holds `terraform`

#### Scenario: Whole term
- **WHEN** the ATS keyword is `java` and the resume only says "JavaScript"
- **THEN** `java` is missing

#### Scenario: Symbols
- **WHEN** the ATS keyword is `c++` and the resume says "C++ and Rust"
- **THEN** `c++` is found

#### Scenario: Short names are still literal
- **WHEN** the ATS keyword is `go` and the resume says "Services in Go"
- **THEN** `go` is found, because an ATS matches the word itself

#### Scenario: Profile does not count
- **WHEN** a keyword is in the profile but not in the resume text
- **THEN** it is in `missing`

#### Scenario: No ATS keywords
- **WHEN** the job has no ATS keywords
- **THEN** `found` and `missing` are empty

### Requirement: Coverage is part of every ready analysis
Every `ready` analysis MUST contain the keyword coverage, computed without the LLM and without spending tokens, from the resume text and the job's ATS keywords at the time of the analysis.

#### Scenario: Ready analysis
- **WHEN** an analysis is `ready`
- **THEN** its result has the coverage, even when every requirement was settled without the LLM
