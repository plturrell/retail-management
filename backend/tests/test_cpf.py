from decimal import Decimal

import pytest

from app.services.cpf import CPFResult, calculate_cpf, get_cpf_rates


class TestGetCPFRates:
    def test_cpf_age_55_and_below(self):
        ee, er = get_cpf_rates(25)
        assert ee == Decimal("0.20")
        assert er == Decimal("0.17")

        ee, er = get_cpf_rates(55)
        assert ee == Decimal("0.20")
        assert er == Decimal("0.17")

    def test_cpf_age_56_to_60(self):
        ee, er = get_cpf_rates(56)
        assert ee == Decimal("0.15")
        assert er == Decimal("0.145")

        ee, er = get_cpf_rates(60)
        assert ee == Decimal("0.15")
        assert er == Decimal("0.145")

    def test_cpf_age_61_to_65(self):
        ee, er = get_cpf_rates(61)
        assert ee == Decimal("0.095")
        assert er == Decimal("0.11")

        ee, er = get_cpf_rates(65)
        assert ee == Decimal("0.095")
        assert er == Decimal("0.11")

    def test_cpf_age_66_to_70(self):
        ee, er = get_cpf_rates(66)
        assert ee == Decimal("0.07")
        assert er == Decimal("0.085")

    def test_cpf_age_above_70(self):
        ee, er = get_cpf_rates(71)
        assert ee == Decimal("0.05")
        assert er == Decimal("0.075")


class TestCalculateCPF:
    def test_basic_calculation_age_30(self):
        result = calculate_cpf(age=30, ordinary_wages=Decimal("5000"))
        assert result.employee_contribution == Decimal("1000")  # 5000 * 0.20
        assert result.employer_contribution == Decimal("850")   # 5000 * 0.17
        assert result.total_contribution == Decimal("1850")
        assert result.ow_used == Decimal("5000")
        assert result.aw_used == Decimal("0")

    def test_cpf_ow_ceiling(self):
        """OW should be capped at $7,400."""
        result = calculate_cpf(age=30, ordinary_wages=Decimal("10000"))
        # Should use 7400 not 10000
        assert result.ow_used == Decimal("7400")
        assert result.employee_contribution == Decimal("1480")  # 7400 * 0.20
        assert result.employer_contribution == Decimal("1258")  # 7400 * 0.17

    def test_cpf_rounding(self):
        """Contributions should be rounded to the nearest dollar."""
        # 3333 * 0.17 = 566.61 -> rounds to 567
        result = calculate_cpf(age=30, ordinary_wages=Decimal("3333"))
        assert result.employer_contribution == Decimal("567")
        # 3333 * 0.20 = 666.6 -> rounds to 667
        assert result.employee_contribution == Decimal("667")

    def test_cpf_age_58(self):
        result = calculate_cpf(age=58, ordinary_wages=Decimal("5000"))
        assert result.employee_contribution == Decimal("750")   # 5000 * 0.15
        assert result.employer_contribution == Decimal("725")   # 5000 * 0.145

    def test_cpf_additional_wages(self):
        result = calculate_cpf(
            age=30,
            ordinary_wages=Decimal("5000"),
            additional_wages=Decimal("2000"),
        )
        # Total wages = 5000 + 2000 = 7000
        assert result.ow_used == Decimal("5000")
        assert result.aw_used == Decimal("2000")
        assert result.employee_contribution == Decimal("1400")  # 7000 * 0.20
        assert result.employer_contribution == Decimal("1190")  # 7000 * 0.17

    def test_cpf_aw_ceiling(self):
        """AW ceiling = 102000 - total OW for year."""
        # If YTD OW = 96000, this month OW = 5000, total OW = 101000
        # AW ceiling = 102000 - 101000 = 1000
        result = calculate_cpf(
            age=30,
            ordinary_wages=Decimal("5000"),
            additional_wages=Decimal("5000"),
            ytd_ordinary_wages=Decimal("96000"),
        )
        assert result.aw_used == Decimal("1000")

    def test_cpf_zero_wages(self):
        result = calculate_cpf(age=30, ordinary_wages=Decimal("0"))
        assert result.employee_contribution == Decimal("0")
        assert result.employer_contribution == Decimal("0")
        assert result.total_contribution == Decimal("0")
