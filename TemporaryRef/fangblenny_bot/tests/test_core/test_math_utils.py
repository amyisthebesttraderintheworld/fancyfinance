"""Tests for math_utils module."""

import pytest
from colorama import Fore
from fangblenny_bot.core.math_utils import pct_change, fmt_vol, grade


class TestPctChange:
    def test_positive_change(self):
        assert pct_change(110, 100) == 10.0

    def test_negative_change(self):
        assert pct_change(90, 100) == -10.0

    def test_zero_base(self):
        assert pct_change(10, 0) == 0.0

    def test_none_base(self):
        assert pct_change(10, None) == 0.0

    def test_invalid_inputs(self):
        assert pct_change("a", 100) == 0.0


class TestFmtVol:
    def test_large_volume(self):
        assert fmt_vol(1_500_000_000) == "1.5B"

    def test_medium_volume(self):
        assert fmt_vol(1_500_000) == "1.5M"

    def test_small_volume(self):
        assert fmt_vol(1_500) == "1.5K"

    def test_tiny_volume(self):
        assert fmt_vol(100) == "100.00"

    def test_invalid_input(self):
        assert fmt_vol("invalid") == "invalid"


class TestGrade:
    def test_a_grade(self):
        grade_str, color = grade(80)
        assert grade_str == "A"
        assert color == Fore.GREEN or "GREEN" in str(color)

    def test_b_grade(self):
        grade_str, color = grade(65)
        assert grade_str == "B"

    def test_c_grade(self):
        grade_str, color = grade(50)
        assert grade_str == "C"

    def test_d_grade(self):
        grade_str, color = grade(40)
        assert grade_str == "D"
        assert color == Fore.RED or "RED" in str(color)
