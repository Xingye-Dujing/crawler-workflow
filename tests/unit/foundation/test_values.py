"""The numeric readers every layer shares: what a typed value MEANS.

Each rule here is one that shipped a bug before: unparseable text and ``inf``/``nan`` are not
numbers (they answered 500 or poisoned a pandas frame), a blank box is "not configured" rather than
0, and a typed 0 is a real answer for a threshold. A mutation sweep over ``core/values.py`` is what
found this file missing: the guards were green because no test ever called them.
"""

from __future__ import annotations

import math

import pytest
from core.values import (
    float_with_default,
    optional_float,
    optional_int,
    safe_float,
    safe_int,
)

pytestmark = pytest.mark.unit


class TestSafeInt:
    def test_a_number_typed_into_a_box(self):
        assert safe_int('5') == 5
        assert safe_int(5) == 5
        assert safe_int(' 7 ') == 7
        assert safe_int('5.9') == 5

    def test_a_typed_zero_is_zero(self):
        assert safe_int('0') == 0
        assert safe_int(0, default=99) == 0

    @pytest.mark.parametrize('value', ['abc', '', None, 'nan', 'inf', '-inf', float('nan'), math.inf])
    def test_not_a_finite_number_falls_back_to_the_default(self, value):
        assert safe_int(value, default=42) == 42

    def test_the_default_is_zero_when_not_given(self):
        assert safe_int('nope') == 0

    def test_the_bounds_clamp_and_a_bound_of_zero_still_applies(self):
        assert safe_int('5', minimum=10) == 10
        assert safe_int('50', maximum=10) == 10
        assert safe_int('-3', minimum=0) == 0
        assert safe_int('3', minimum=0, maximum=10) == 3


class TestSafeFloat:
    def test_a_number_typed_into_a_box(self):
        assert safe_float('1.5') == 1.5
        assert safe_float(2) == 2.0

    def test_a_typed_zero_is_zero(self):
        assert safe_float('0', default=9.5) == 0.0

    @pytest.mark.parametrize('value', ['abc', None, 'nan', 'inf', float('inf')])
    def test_not_a_finite_number_falls_back_to_the_default(self, value):
        assert safe_float(value, default=1.25) == 1.25


class TestOptionalInt:
    def test_absent_means_not_configured(self):
        assert optional_int('') is None
        assert optional_int('   ') is None
        assert optional_int(None) is None

    def test_a_typed_zero_is_configured(self):
        assert optional_int('0') == 0

    def test_unparseable_or_infinite_is_not_configured(self):
        assert optional_int('abc') is None
        assert optional_int('inf') is None

    def test_a_fraction_truncates_like_int(self):
        assert optional_int('2.9') == 2


class TestOptionalFloat:
    def test_absent_means_not_configured(self):
        assert optional_float('') is None
        assert optional_float(None) is None

    def test_a_typed_zero_is_configured(self):
        assert optional_float('0') == 0.0

    def test_the_fraction_is_kept(self):
        assert optional_float('0.25') == 0.25

    def test_unparseable_or_infinite_is_not_configured(self):
        assert optional_float('abc') is None
        assert optional_float('nan') is None


class TestFloatWithDefault:
    def test_a_threshold_zero_is_a_real_answer(self):
        assert float_with_default('0', 0.5) == 0.0

    def test_an_absent_box_answers_the_default(self):
        assert float_with_default('', 0.5) == 0.5

    def test_unparseable_text_answers_the_default(self):
        assert float_with_default('abc', 0.5) == 0.5
