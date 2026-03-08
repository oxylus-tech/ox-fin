from decimal import Decimal
from asteval import Interpreter


__all__ = ("get_interpreter", "Interpreter")


def get_interpreter(context) -> Interpreter:
    """Return asteval Interpreter with symtable fullfilled with values."""
    ae = Interpreter()
    ae.symtable["Decimal"] = Decimal
    ae.symtable.update(context)
    return ae
