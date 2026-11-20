# candidate-profile Specification

## Purpose

Stores the single candidate's profile (target role, seniority, years coding, stacks, languages and notable facts) as the source of truth about the candidate, in a normalized form that later analysis can compare with resumes and jobs.

## Requirements

### Requirement: Profile can be created or replaced
The system SHALL expose `PUT /profile`, which stores the candidate profile from the request body. There is exactly one profile: when none exists it is created, and when one exists it is replaced entirely by the request body (nothing from the previous profile is kept). The response MUST be HTTP 200 with the stored profile in its normalized form.

#### Scenario: First save
- **WHEN** a client sends a valid `PUT /profile` and no profile exists
- **THEN** the response is 200 and contains the profile in normalized form

#### Scenario: Replace
- **WHEN** a client sends a valid `PUT /profile` while a profile with other stacks already exists
- **THEN** the response is 200 and the stored profile contains only the stacks of the new request

### Requirement: Profile can be read
The system SHALL expose `GET /profile`, which returns the stored profile in the same normalized form as the `PUT /profile` response. When no profile has been stored, it MUST respond with HTTP 404 and a JSON error body.

#### Scenario: Round trip
- **WHEN** a client sends a valid `PUT /profile` and then `GET /profile`
- **THEN** the `GET` response is 200 and its body equals the body returned by the `PUT`

#### Scenario: No profile yet
- **WHEN** a client sends `GET /profile` and no profile has ever been stored
- **THEN** the response is 404 with a JSON error body

#### Scenario: Profile survives a restart
- **WHEN** a profile is stored and the application is restarted
- **THEN** `GET /profile` still returns that profile

### Requirement: Profile fields and allowed values
A profile SHALL have: `target_role` (non-empty text, at most 100 characters), `seniority` (one of `junior`, `mid`, `senior`), `total_years_coding` (number from 0 to 60), `stacks`, `languages` and `notable_facts` (all three required, each may be an empty list). A stack MUST have a `name` (non-empty, at most 100 characters), `years` (number from 0 to 60), a `level` (one of `learning`, `working`, `proficient`, `expert`) and MAY have `last_year_used` (a whole year from 1970 up to the current year). A language MUST have a `name` (non-empty, at most 100 characters) and a `level` (one of `A1`, `A2`, `B1`, `B2`, `C1`, `C2`, `native`). `notable_facts` is a list of up to 100 non-empty free-text entries of at most 1000 characters each. A profile MAY have at most 100 stacks and 20 languages. Leading and trailing whitespace of text values MUST be ignored. Fields that are not part of the profile MUST be rejected.

#### Scenario: Complete valid profile
- **WHEN** a client sends a profile with every field inside the allowed values
- **THEN** the profile is accepted

#### Scenario: Unknown seniority
- **WHEN** a client sends `seniority` set to `principal`
- **THEN** the response is 422 and the message names the `seniority` field and the allowed values

#### Scenario: Missing required field
- **WHEN** a client sends a profile without `target_role`
- **THEN** the response is 422 and the message names the `target_role` field

#### Scenario: Unknown field
- **WHEN** a client sends a profile with a field that is not defined (for example `senority`)
- **THEN** the response is 422 and the message names that field

#### Scenario: Optional last year used
- **WHEN** a stack has no `last_year_used`
- **THEN** the profile is accepted and the stack is returned without a last year used

#### Scenario: Last year used in the future
- **WHEN** a stack has a `last_year_used` later than the current year
- **THEN** the response is 422 and the message names that field

### Requirement: Years are not negative and stack years fit the career
Years MUST NOT be negative. The `years` of a stack MUST NOT exceed `total_years_coding`.

#### Scenario: Negative years
- **WHEN** a client sends a stack with `years` of -1
- **THEN** the response is 422 and the message names that stack's `years` field

#### Scenario: Stack longer than career
- **WHEN** a client sends `total_years_coding` of 3 and a stack with `years` of 5
- **THEN** the response is 422 and the message identifies the stack by its position (for example `stacks[0]`) and states that its years exceed the total years coding

#### Scenario: Stack equal to career
- **WHEN** a client sends `total_years_coding` of 3 and a stack with `years` of 3
- **THEN** the profile is accepted

### Requirement: Stack and language names are normalized and the original is kept
The system SHALL normalize each stack name and each language name (see the `name-normalization` capability) and return, for each item, the normalized `name` together with the text as typed in `original_name` (surrounding whitespace trimmed).

#### Scenario: Alias normalized
- **WHEN** a client sends a stack named `Springboot` and a language named `Português`
- **THEN** the response contains the stack with `name` `spring boot` and `original_name` `Springboot`, and the language with `name` `portuguese` and `original_name` `Português`

#### Scenario: Unknown name
- **WHEN** a client sends a stack named `  Rust ` that has no alias
- **THEN** the response contains `name` `rust` and `original_name` `Rust`

### Requirement: No duplicate stacks or languages after normalization
The system MUST reject a profile in which two stacks, or two languages, have the same normalized name. The error MUST identify the colliding items by their position in the list (for example `stacks[0]` and `stacks[2]`).

#### Scenario: Duplicate through alias
- **WHEN** a client sends stacks `Postgres` and `PostgreSQL`
- **THEN** the response is 422 and the message states that `stacks[0]` and `stacks[1]` have the same name after normalization

#### Scenario: Same name in stacks and languages
- **WHEN** a client sends a stack and a language that normalize to the same text
- **THEN** the profile is accepted, because duplicates are checked within stacks and within languages separately

### Requirement: Invalid input is rejected with clear messages
Any input that violates the requirements of this capability SHALL be rejected with HTTP 422, no profile data MUST be stored or changed by a rejected request, and the error message SHALL identify every violation found (field and reason) so that they can be fixed together: all violations of individual field values are reported in one response, and the rules that compare fields (stack years against total years, duplicate names) are reported together once every field value is valid. Error messages MUST NOT repeat the submitted values.

#### Scenario: Several violations
- **WHEN** a client sends `seniority` `principal` and a stack with negative years
- **THEN** one 422 response reports both violations

#### Scenario: Several comparison violations
- **WHEN** a client sends two stacks longer than the total years coding and a duplicated language, with every field value valid
- **THEN** one 422 response reports all three violations

#### Scenario: Rejected request keeps the old profile
- **WHEN** a profile exists and a client sends an invalid `PUT /profile`
- **THEN** the response is 422 and `GET /profile` still returns the previous profile

### Requirement: Profile content is private
The system MUST NOT write profile content (target role, stack or language names, notable facts) to logs.

#### Scenario: Save and read
- **WHEN** a profile is saved and read
- **THEN** no log entry contains any text from the profile
