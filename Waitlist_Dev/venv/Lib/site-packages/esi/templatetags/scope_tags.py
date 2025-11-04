from django.template.defaulttags import register

from ..models import Scope


@register.filter()
def scope_friendly_name(name):
    return Scope._friendly_name(name)
