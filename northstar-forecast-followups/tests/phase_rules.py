"""Public scenario interpretation shared by the grader and its independent reference."""

METHODS = {
    1: "legacy_monthly_growth",
    2: "customer_cohort_calendar", 3: "customer_cohort_calendar", 4: "customer_cohort_calendar",
    5: "customer_cohort_renewal", 6: "customer_cohort_renewal",
}


def scenario_overrides(phase):
    if phase < 3:
        return {}
    rows = {16: 50, 17: 18, 22: 7200, 23: 45000, 24: .14}
    if phase >= 6:
        rows = {17: 18, 23: 45000, 24: .14}
    edits = {f"{chr(69 + month)}{row}": value for month in range(12) for row, value in rows.items()}
    if phase >= 6:
        edits.update({f"{chr(69 + month)}22": 12000 for month in range(6, 12)})
    return edits


def sensitivity_cases(phase):
    cases = {
        "legacy_growth": {f"{chr(69 + m)}6": .70 for m in range(12)},
        "financial": {"F16": 47, "I17": 21, "M22": 11000},
        "funding": {
            f"{chr(69 + m)}{row}": value for m in range(12)
            for row, value in [(23, 45000), (24, .14)]
        },
    }
    if phase >= 2:
        cases["cohorts_and_events"] = {
            "G9": 67, "J11": .025, "K15": .06, "N15": .02,
            "E12": 940, "E13": 125, "L14": 149,
        }
        # Non-quarter events queue, combine, expire out-of-year, and never leak to later launches.
        cases["renewal_boundaries"] = {"F15": .03, "G15": .02, "P15": .05}
    return cases
