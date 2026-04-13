"""
Singapore CPF 2026 contribution calculator.

Pure calculation module — no database access.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


# CPF 2026 contribution rates by age bracket
# (max_age_inclusive, employee_rate, employer_rate)
_CPF_RATES: list[tuple[int, Decimal, Decimal]] = [
    (55, Decimal("0.20"), Decimal("0.17")),
    (60, Decimal("0.15"), Decimal("0.145")),
    (65, Decimal("0.095"), Decimal("0.11")),
    (70, Decimal("0.07"), Decimal("0.085")),
    (999, Decimal("0.05"), Decimal("0.075")),  # >70
]

# Ordinary Wage ceiling per month (2026)
OW_CEILING = Decimal("7400")

# Annual cap used for Additional Wage ceiling calculation
ANNUAL_OW_CAP = Decimal("102000")


@dataclass
class CPFResult:
    employee_contribution: Decimal
    employer_contribution: Decimal
    total_contribution: Decimal
    ow_used: Decimal
    aw_used: Decimal


def get_cpf_rates(age: int) -> tuple[Decimal, Decimal]:
    """Return (employee_rate, employer_rate) for the given age."""
    for max_age, ee_rate, er_rate in _CPF_RATES:
        if age <= max_age:
            return ee_rate, er_rate
    # Fallback (should not reach here)
    return _CPF_RATES[-1][1], _CPF_RATES[-1][2]


def _round_cpf(amount: Decimal) -> Decimal:
    """Round to the nearest dollar (standard CPF rounding)."""
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calculate_cpf(
    age: int,
    ordinary_wages: Decimal,
    additional_wages: Decimal = Decimal("0"),
    ytd_ordinary_wages: Decimal = Decimal("0"),
) -> CPFResult:
    """
    Calculate CPF contributions for an employee.

    Args:
        age: Employee's age.
        ordinary_wages: Monthly ordinary wages (basic salary).
        additional_wages: Additional wages for the month (bonus, etc.).
        ytd_ordinary_wages: Year-to-date ordinary wages already subject to CPF
                            (excluding this month), used for AW ceiling calc.

    Returns:
        CPFResult with employee/employer contributions and wage amounts used.
    """
    ee_rate, er_rate = get_cpf_rates(age)

    # Cap OW at the monthly ceiling
    ow_used = min(ordinary_wages, OW_CEILING)

    # AW ceiling = $102,000 - total OW subject to CPF for the year
    total_ow_for_year = ytd_ordinary_wages + ow_used
    aw_ceiling = max(ANNUAL_OW_CAP - total_ow_for_year, Decimal("0"))
    aw_used = min(additional_wages, aw_ceiling)

    total_wages = ow_used + aw_used

    employee_contribution = _round_cpf(total_wages * ee_rate)
    employer_contribution = _round_cpf(total_wages * er_rate)
    total_contribution = employee_contribution + employer_contribution

    return CPFResult(
        employee_contribution=employee_contribution,
        employer_contribution=employer_contribution,
        total_contribution=total_contribution,
        ow_used=ow_used,
        aw_used=aw_used,
    )
