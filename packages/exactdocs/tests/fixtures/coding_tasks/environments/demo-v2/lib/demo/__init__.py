"""A stand-in library, version 2: `@field_validator(name)` replaces `@validator`, which warns."""

import warnings

__version__ = "2.0"


def field_validator(field):
    """Mark a classmethod as the validator of `field`."""

    def mark(function):
        target = function.__func__ if isinstance(function, classmethod) else function
        target.__validates__ = field
        return classmethod(target)

    return mark


def validator(field):
    """Version 1's decorator: deprecated, use `field_validator`."""
    warnings.warn("`validator` is deprecated; use `field_validator`", DeprecationWarning, stacklevel=2)

    def mark(function):
        function.__validates__ = field
        return classmethod(function)

    return mark


class Model:
    """Holds the annotated fields, each run through its validators."""

    def __init__(self, **values):
        for name in type(self).__annotations__:
            if name not in values:
                raise ValueError(f"{name} is required")
            value = values[name]
            for attribute in vars(type(self)).values():
                function = attribute.__func__ if isinstance(attribute, classmethod) else attribute
                if getattr(function, "__validates__", None) == name:
                    value = function(type(self), value)
            setattr(self, name, value)
