"""A stand-in library, version 1: a field is checked with `@validator(name)`."""

__version__ = "1.0"


def validator(field):
    """Mark a classmethod-like function as the validator of `field`."""

    def mark(function):
        function.__validates__ = field
        return function

    return mark


class Model:
    """Holds the annotated fields, each run through its validators."""

    def __init__(self, **values):
        for name in type(self).__annotations__:
            if name not in values:
                raise ValueError(f"{name} is required")
            value = values[name]
            for attribute in vars(type(self)).values():
                if getattr(attribute, "__validates__", None) == name:
                    value = attribute(type(self), value)
            setattr(self, name, value)
