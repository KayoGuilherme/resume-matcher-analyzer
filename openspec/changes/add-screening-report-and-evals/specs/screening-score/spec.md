# Spec Delta

## Purpose

Gives the candidate a single, explainable number and an outcome that estimate how a first-step screener would rate the resume for a job, computed by fixed rules from the gap analysis and the resume's parsing issues, with no LLM involved.

## ADDED Requirements

### Requirement: The score is a weighted coverage minus parsing penalties
The system SHALL compute a score from 0 to 100 from three coverages and the resume's parsing issues. The coverages are: the must-have coverage (the requirements whose priority is `must_have`), the nice-to-have coverage (the requirements whose priority is `nice_to_have`) and the keyword coverage (the job's ATS keywords found in the resume divided by all of them). A requirement's credit MUST be 1 for `met`, `SCORE_PARTIAL_CREDIT` for `partial`, and 0 for `missing` and for `in_profile_not_in_resume` (a screener reads only the resume, so what is only in the profile earns nothing); a requirement's priority is the one the analysis reports, also when `priority_unclear` is true. A coverage MUST be the mean credit of its requirements. The weighted coverage MUST be the sum of each coverage times its weight (`SCORE_WEIGHT_MUST_HAVE`, `SCORE_WEIGHT_NICE_TO_HAVE`, `SCORE_WEIGHT_KEYWORDS`) divided by the sum of the weights of the coverages that exist, times 100. A coverage that has nothing to measure (no requirement of that priority, or no ATS keyword) MUST be left out, and the remaining weights used as if they were the only ones. The penalties MUST be, for each parsing issue of the resume, `SCORE_PENALTY_CRITICAL`, `SCORE_PENALTY_WARNING` or `SCORE_PENALTY_INFO` points according to its severity. The score MUST be the weighted coverage minus the penalties, limited to the range 0 to 100 and rounded to one decimal. The computation MUST be deterministic and MUST NOT call an LLM or a database.

#### Scenario: Weighted coverage with a penalty
- **WHEN** with the default settings 3 of 4 must-haves are `met` and 1 is `missing`, 1 of 2 nice-to-haves is `met` and 1 is `missing`, 8 of 10 ATS keywords are found, and the resume has one `warning` issue
- **THEN** the weighted coverage is 72.5, the penalty is 5 and the score is 67.5

#### Scenario: Partial credit
- **WHEN** one must-have is `partial` and `SCORE_PARTIAL_CREDIT` is 0.5
- **THEN** it contributes a credit of 0.5 to the must-have coverage

#### Scenario: What only the profile proves earns nothing
- **WHEN** a must-have is `in_profile_not_in_resume`
- **THEN** it contributes a credit of 0, exactly like a `missing` one

#### Scenario: A coverage with nothing to measure is left out
- **WHEN** the job has no nice-to-have requirement, with 3 of 4 must-haves `met` and 8 of 10 keywords found, and the default weights
- **THEN** the weighted coverage is computed from the must-have and keyword coverages only, with their weights 0.6 and 0.25, and is 76.5

#### Scenario: Limits
- **WHEN** the penalties are larger than the weighted coverage
- **THEN** the score is 0, never negative; and it never exceeds 100

#### Scenario: Nothing to measure at all
- **WHEN** the job has no requirement and no ATS keyword
- **THEN** the score and the outcome are absent (null) and the breakdown says that nothing could be measured

#### Scenario: Same input, same score
- **WHEN** the score is computed twice from the same analysis, the same issues and the same settings
- **THEN** both results are identical

### Requirement: The outcome comes from two configured thresholds
The system SHALL give an outcome: `likely_pass` when the score is at least `SCORE_PASS_THRESHOLD`, `borderline` when it is at least `SCORE_BORDERLINE_THRESHOLD` but below the pass threshold, and `likely_reject` otherwise. A score exactly equal to a threshold MUST get the better outcome.

#### Scenario: Pass
- **WHEN** the score is 85 and the pass threshold is 70
- **THEN** the outcome is `likely_pass`

#### Scenario: Borderline
- **WHEN** the score is 67.5, the pass threshold is 70 and the borderline threshold is 50
- **THEN** the outcome is `borderline`

#### Scenario: Reject
- **WHEN** the score is 49.9 and the borderline threshold is 50
- **THEN** the outcome is `likely_reject`

#### Scenario: Exactly on a threshold
- **WHEN** the score is exactly 70 with a pass threshold of 70, or exactly 50 with a borderline threshold of 50
- **THEN** the outcome is `likely_pass`, respectively `borderline`

### Requirement: The score explains itself
The result MUST include the breakdown it was computed from: for each coverage its name, its value from 0 to 1 (null when left out), its configured weight and whether it was included; each penalty with the issue code, the severity and the points; the total penalty; and the two thresholds used. A reader MUST be able to recompute the score from the breakdown alone.

#### Scenario: Breakdown present
- **WHEN** a score is returned
- **THEN** it lists the three coverages with their weights, every penalty with its points, the total penalty and both thresholds

#### Scenario: Left-out coverage
- **WHEN** the job has no nice-to-have requirement
- **THEN** the nice-to-have coverage is listed as not included, with a null value
