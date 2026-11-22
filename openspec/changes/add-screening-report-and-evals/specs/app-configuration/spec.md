# Spec Delta

## ADDED Requirements

### Requirement: Score, screener and report settings
The system SHALL read these settings from the environment: `SCORE_WEIGHT_MUST_HAVE` (number from 0 to 1, default 0.6), `SCORE_WEIGHT_NICE_TO_HAVE` (0 to 1, default 0.15), `SCORE_WEIGHT_KEYWORDS` (0 to 1, default 0.25), `SCORE_PARTIAL_CREDIT` (0 to 1, default 0.5), `SCORE_PENALTY_CRITICAL` (0 to 100, default 40), `SCORE_PENALTY_WARNING` (0 to 100, default 5), `SCORE_PENALTY_INFO` (0 to 100, default 1), `SCORE_PASS_THRESHOLD` (0 to 100, default 70), `SCORE_BORDERLINE_THRESHOLD` (0 to 100, default 50), `SCREENER_RUNS` (whole number from 1 to 10, default 3) and `REPORT_MAX_SUGGESTIONS` (whole number from 0 to 30, default 8). A value outside its range or not of its type MUST make startup fail with a validation error that names the setting. At least one of the three weights MUST be greater than 0, and `SCORE_BORDERLINE_THRESHOLD` MUST be lower than `SCORE_PASS_THRESHOLD`; otherwise startup MUST fail with a validation error that names the setting at fault. All eleven MUST be listed in `.env.example` with a short comment, and the comments MUST say that the weights are relative (they are scaled to add up to one) and that the thresholds are on the score's 0 to 100 scale.

#### Scenario: Defaults
- **WHEN** the application starts without these variables
- **THEN** the weights are 0.6, 0.15 and 0.25, the partial credit 0.5, the penalties 40, 5 and 1, the thresholds 70 and 50, the screener runs 3 and the suggestions cap 8

#### Scenario: Overrides
- **WHEN** `SCORE_PASS_THRESHOLD=80`, `SCREENER_RUNS=5` and `REPORT_MAX_SUGGESTIONS=0` are set
- **THEN** the pass threshold is 80, the screener runs 5 times and no suggestions are asked for

#### Scenario: Out of range
- **WHEN** `SCREENER_RUNS` is `0` or `SCORE_PARTIAL_CREDIT` is `1.5`
- **THEN** startup fails with a validation error that names that setting

#### Scenario: Not a number
- **WHEN** `SCORE_WEIGHT_KEYWORDS` is `heavy`
- **THEN** startup fails with a validation error that names `SCORE_WEIGHT_KEYWORDS`

#### Scenario: All weights zero
- **WHEN** the three `SCORE_WEIGHT_*` settings are all `0`
- **THEN** startup fails with a validation error that names the weights

#### Scenario: Thresholds in the wrong order
- **WHEN** `SCORE_BORDERLINE_THRESHOLD=80` and `SCORE_PASS_THRESHOLD=70`
- **THEN** startup fails with a validation error that names `SCORE_BORDERLINE_THRESHOLD`

#### Scenario: Example file
- **WHEN** `.env.example` is read
- **THEN** it lists the eleven settings with their defaults
