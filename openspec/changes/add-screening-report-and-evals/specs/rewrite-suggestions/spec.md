# Spec Delta

## Purpose

Proposes concrete rewordings and additions for the resume's bullets that make true things visible to a screener, each traceable to a bullet or profile fact, and guarantees by a deterministic check that no suggestion adds a technology, a number or a year that the resume and the profile do not already contain.

## ADDED Requirements

### Requirement: Suggestions are asked only for things the candidate can truthfully show
The system SHALL ask for suggestions for these targets, in this order: requirements whose verdict is `in_profile_not_in_resume`, then requirements whose verdict is `partial`, then ATS keywords that are missing from the resume but are the name of a stack in the candidate profile (compared by normalized name) and do not belong to a requirement that is already a target. Within each group the `must_have` requirements MUST come before the `nice_to_have` ones, and the job's order MUST be kept. At most `REPORT_MAX_SUGGESTIONS` targets MUST be asked for, in one LLM call. Requirements with verdict `missing` or `met` MUST NOT be targets. When there is no target, or `REPORT_MAX_SUGGESTIONS` is 0, no LLM call MUST be made and the suggestions MUST be empty.

#### Scenario: Targets and their order
- **WHEN** the analysis has a nice-to-have `in_profile_not_in_resume`, a must-have `in_profile_not_in_resume`, a `partial` must-have and a `missing` must-have
- **THEN** the targets are the must-have `in_profile_not_in_resume`, the nice-to-have `in_profile_not_in_resume` and the `partial` one, in that order, and the `missing` one is not a target

#### Scenario: Keyword proven by the profile
- **WHEN** the ATS keyword `docker` is missing from the resume and the profile has the stack `Docker`
- **THEN** `docker` is a target

#### Scenario: Keyword already covered by a target
- **WHEN** the missing ATS keyword `kubernetes` is a keyword of a requirement that is already a target
- **THEN** it is not a separate target

#### Scenario: Cap
- **WHEN** there are 12 targets and `REPORT_MAX_SUGGESTIONS` is 8
- **THEN** only the first 8 are asked for, in one LLM call

#### Scenario: Nothing to suggest
- **WHEN** there is no target, or `REPORT_MAX_SUGGESTIONS` is 0
- **THEN** the LLM is not called and the list of suggestions is empty

### Requirement: Every suggestion points to its source
Each suggestion MUST have a target (the requirement or the keyword it addresses), the suggested text, and a `based_on` that is either a resume bullet or a profile fact. The model MUST name its source by the number of an item in a numbered list given in the prompt (the resume's experience and project bullets, or the profile's stacks, languages and notable facts), and the system MUST resolve that number itself: the pointer of a resume source MUST be the bullet's text exactly as in the resume, and the pointer of a profile source MUST be the notable fact as written, or, for a stack or a language, a statement made only of its own values. A suggestion based on a resume bullet is a rewording of that bullet (the bullet is returned as `original`); one based on a profile fact is a new bullet (`original` is null). A suggestion whose number does not exist MUST be rejected.

#### Scenario: Rewording of a bullet
- **WHEN** the model answers with source "resume bullet 4" and a new text
- **THEN** the suggestion's `original` and `based_on` are the exact text of resume bullet 4

#### Scenario: New bullet from the profile
- **WHEN** the model answers with source "profile stack 2" (Kubernetes, 2 years, working)
- **THEN** the suggestion is a new bullet, its `original` is null and its `based_on` is a statement made of those profile values

#### Scenario: Unknown source
- **WHEN** the model answers with "resume bullet 99" and the resume has 30 bullets
- **THEN** the suggestion is rejected with the reason code `unknown_source`

### Requirement: Suggestions that add facts are rejected by a deterministic check
Every suggested text MUST be checked in code, whatever the model was told, and rejected when it contains: a technology (a tool, language, framework, platform or product name) that is found neither in the resume text nor in the profile; a number (including percentages, amounts, counts, years and durations, and numbers written as words in English or Portuguese up to twenty) that is found neither in the resume text nor in the profile; or when it is empty, identical to its `original`, or longer than 400 characters. The profile's numbers are those written in it and the values of its stacks' years and of its total years coding. A technology MUST be recognised when its name or an alias is in the job's requirement keywords, the job's ATS keywords, the candidate's stacks, the resume's skills and project technologies, or the system's list of common technologies, and also when a word has the shape of a technology name (a symbol such as `+`, `#` or an inner `.`, an all-capital acronym of three letters or more, or a capitalized word that is not at the start of a sentence) and is found neither in the resume text nor in the profile. A technology that the resume or the profile contains MAY be used. Rejected suggestions MUST NOT be returned or stored as text; they MUST only be counted, by reason code (`unsupported_technology`, `unsupported_number`, `unknown_source`, `empty_or_unchanged`, `too_long`), in the report's warnings.

#### Scenario: Invented technology
- **WHEN** a suggestion says "Deployed services on Kubernetes" and neither the resume nor the profile mentions Kubernetes (or `k8s`)
- **THEN** it is rejected with `unsupported_technology`

#### Scenario: Technology from the profile
- **WHEN** a suggestion says "Deployed services on Kubernetes" and the profile has the stack Kubernetes
- **THEN** the check does not reject it for that technology

#### Scenario: Technology from an alias
- **WHEN** a suggestion says "Kubernetes" and the resume text says "K8s"
- **THEN** the check does not reject it for that technology

#### Scenario: Invented number
- **WHEN** a suggestion says "reduced response time by 40%" and 40 is neither in the resume nor in the profile
- **THEN** it is rejected with `unsupported_number`

#### Scenario: Number from the resume
- **WHEN** a suggestion says "reduced query time by 60%" and the resume bullet it is based on says "cut query time by 60%"
- **THEN** the check does not reject it for that number

#### Scenario: Invented years
- **WHEN** a suggestion says "7 years of Python" and the profile gives Python 3 years and the resume has no 7
- **THEN** it is rejected with `unsupported_number`

#### Scenario: Years from the profile
- **WHEN** a suggestion says "3 years of Python" and the profile gives Python 3 years
- **THEN** the check does not reject it for that number

#### Scenario: Number written as a word
- **WHEN** a suggestion says "five years" or "cinco anos" and neither the resume nor the profile has a 5
- **THEN** it is rejected with `unsupported_number`

#### Scenario: Unknown technology by shape
- **WHEN** a suggestion mentions "Zorbify.js" which is in no list, the resume or the profile
- **THEN** it is rejected with `unsupported_technology`

#### Scenario: Empty or unchanged
- **WHEN** the suggested text is empty or equal to the original bullet
- **THEN** it is rejected with `empty_or_unchanged`

#### Scenario: Rejected text is not exposed
- **WHEN** a suggestion is rejected
- **THEN** its text appears nowhere in the report or in the stored data; the warnings only hold the reason code and a count

### Requirement: Suggestions are written in the language of the resume
The prompt MUST ask for the suggested text in the language of the bullet it rewrites, or, for a new bullet, in the language of the resume's other bullets, and to write nothing that is not stated in the source, the resume or the profile. The text MUST NOT claim a level, a title or a result that the sources do not state.

#### Scenario: Portuguese resume
- **WHEN** the resume's bullets are in Portuguese
- **THEN** the prompt asks for Portuguese suggestions

### Requirement: Suggestion content stays out of logs
The system MUST NOT log suggestions, their sources or the prompts. It MAY log the number of targets, accepted suggestions and rejections by reason code.

#### Scenario: Logs after suggestions
- **WHEN** suggestions were produced
- **THEN** no log record contains a suggested text, a bullet or a profile fact
