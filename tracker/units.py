"""Canonical units are European: mmol/L, kg, mmHg.

Blood pressure is displayed in mmHg for everyone (imperial BP is not a
thing); only glucose and weight convert per user preference.
"""

from decimal import Decimal, ROUND_HALF_UP

MMOL_TO_MGDL = Decimal("18.0182")
KG_TO_LB = Decimal("2.20462")

GLUCOSE_BAND_MMOL = (Decimal("3.9"), Decimal("7.8"))  # non-fasting target band
BP_BAND_SYS = (Decimal("90"), Decimal("120"))


def _q(value, places):
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def user_units(user):
    from .models import Profile

    profile, _ = Profile.objects.get_or_create(user=user)
    return profile.units


def is_imperial(units):
    return units == "imperial"


# --- glucose ---------------------------------------------------------------

def glucose_display(value_mmol, units):
    """-> (Decimal, unit label) in the user's display units."""
    if is_imperial(units):
        return _q(Decimal(value_mmol) * MMOL_TO_MGDL, "1"), "mg/dL"
    return _q(value_mmol, "0.1"), "mmol/L"


def glucose_from_display(value, units):
    """User-entered value -> canonical mmol/L."""
    if is_imperial(units):
        return _q(Decimal(value) / MMOL_TO_MGDL, "0.01")
    return _q(value, "0.01")


def fmt_glucose(value_mmol, units):
    val, label = glucose_display(value_mmol, units)
    return f"{val}"


def glucose_unit_label(units):
    return "mg/dL" if is_imperial(units) else "mmol/L"


# --- weight ----------------------------------------------------------------

def weight_display(value_kg, units):
    if is_imperial(units):
        return _q(Decimal(value_kg) * KG_TO_LB, "0.1"), "lb"
    return _q(value_kg, "0.1"), "kg"


def weight_from_display(value, units):
    if is_imperial(units):
        return _q(Decimal(value) / KG_TO_LB, "0.01")
    return _q(value, "0.01")


def weight_unit_label(units):
    return "lb" if is_imperial(units) else "kg"


# --- blood pressure (always mmHg) -------------------------------------------

def fmt_bp(systolic, diastolic):
    return f"{systolic}/{diastolic}"
