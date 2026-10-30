# SPDX-License-Identifier: MIT
"""Dialects: the -std= option and the -f dialect settings it implies.

A dialect here is not a claim of conformance to a vendor's implementation. It
is a record of the choices a compiler has to make where the standards leave
one open or where implementations have traditionally differed, and which way
each named dialect resolves them. Only settings YACCC actually implements
appear here; the README says what each one changes.
"""

# name: binary_size, binary_truncate, missing_period, host_sign, nonnum_zero,
#       space_raw
# host_sign: a signed PACKED-DECIMAL item whose sign nibble is F (the host's
# "unsigned" sign) passes the NUMERIC class test, as on IBM mainframes
# nonnum_zero: MOVE of a figurative constant other than ZERO, or of an
# alphanumeric literal that isn't all digits, to a numeric item moves zero
# (Micro Focus)
# space_raw: MOVE SPACE to a numeric DISPLAY item stores spaces, as MOVE
# LOW-VALUE / HIGH-VALUE store their bytes (ACUCOBOL)
DIALECTS = {
    'default':   ('2-4-8',   True,  False, False, False, False),
    'gnu':       ('2-4-8',   True,  True,  False, False, False),
    'cobol85':   ('2-4-8',   True,  False, False, False, False),
    'cobol2002': ('2-4-8',   True,  False, False, False, False),
    'cobol2014': ('2-4-8',   True,  False, False, False, False),
    # measured against cobc 3.1.2: PIC 9(2) COMP holding 1289 displays as 09
    # under mf (one-byte storage, value cut to the PICTURE) and as 01289 under
    # ibm (no truncation, and a scaled item loses its decimal point too), so it
    # is ibm that switches truncation off, not mf
    'mf':        ('1-2-4-8', True,  True,  False, True,  False),
    'ibm':       ('2-4-8',   False, True,  True,  False, False),
    'acu':       ('1-2-4-8', True,  True,  False, False, True),
}

_ALIASES = {
    'default': 'default',
    'gnucobol': 'gnu', 'gnu': 'gnu', 'open-cobol': 'gnu',
    'cobol85': 'cobol85', 'cobol-85': 'cobol85', '85': 'cobol85',
    'cobol2002': 'cobol2002', 'cobol-2002': 'cobol2002', '2002': 'cobol2002',
    'cobol2014': 'cobol2014', 'cobol-2014': 'cobol2014', '2014': 'cobol2014',
    'mf': 'mf', 'microfocus': 'mf', 'micro-focus': 'mf',
    'ibm': 'ibm', 'ibm-cobol': 'ibm',
    'acu': 'acu', 'acucobol': 'acu',
}


class Dialect:
    """The settings one dialect selects. None for a setting means "not
    changed", so a -f option can override an individual choice."""

    def __init__(self, name='default'):
        try:
            key = _ALIASES[name.lower().strip()]
        except KeyError:
            raise KeyError(name) from None
        bs, trunc, per, hs, nz, sr = DIALECTS[key]
        self.name = key
        self.host_sign = hs
        self.nonnum_zero = nz
        self.space_raw = sr
        self.binary_size = bs
        self.binary_truncate = trunc
        self.missing_period = per

    def __repr__(self):
        return (f"Dialect({self.name}, binary-size={self.binary_size}, "
                f"binary-truncate={self.binary_truncate}, missing-period={self.missing_period})")


def accepted_names():
    """The values -std= takes, for an error message."""
    return sorted(_ALIASES)
