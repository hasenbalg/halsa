from datetime import timedelta

from django import template
from django.utils import timezone

from .. import units as U

register = template.Library()


@register.filter
def glucose(value, units):
    return U.glucose_display(value, units)[0]


@register.filter
def glucose_unit(units):
    return U.glucose_unit_label(units)


@register.filter
def weight(value, units):
    return U.weight_display(value, units)[0]


@register.filter
def weight_unit(units):
    return U.weight_unit_label(units)


@register.filter
def when(dt):
    local = timezone.localtime(dt)
    today = timezone.localdate()
    if local.date() == today:
        return f"today {local:%H:%M}"
    if local.date() == today - timedelta(days=1):
        return f"yesterday {local:%H:%M}"
    return f"{local:%d.%m.%y %H:%M}"


@register.filter
def day(d):
    return f"{d:%d.%m.%y}"
