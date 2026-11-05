# SPDX-License-Identifier: MIT
"""Dialects: the -std= option and the -f dialect settings it implies.

A dialect here is not a claim of conformance to a vendor's implementation. It
is a record of the choices a compiler has to make where the standards leave
one open or where implementations have traditionally differed, and which way
each named dialect resolves them. Only settings YACCC actually implements
appear here; the README says what each one changes.
"""

# name: binary_size, binary_truncate, missing_period, host_sign, nonnum_zero,
#       space_raw, pretty_display, arithmetic_osvs
# host_sign: a signed PACKED-DECIMAL item whose sign nibble is F (the host's
# "unsigned" sign) passes the NUMERIC class test, as on IBM mainframes
# nonnum_zero: MOVE of a figurative constant other than ZERO, or of an
# alphanumeric literal that isn't all digits, to a numeric item moves zero
# (Micro Focus)
# space_raw: MOVE SPACE to a numeric DISPLAY item stores spaces, as MOVE
# LOW-VALUE / HIGH-VALUE store their bytes (ACUCOBOL)
# pretty_display: DISPLAY of a numeric item writes its decimal point and a
# leading sign.  Without it the stored digits are written as they stand and a
# BINARY item shows the digits its storage holds (IBM, and -fnotrunc)
# arithmetic_osvs: a COMPUTE with more than one operation truncates each
# intermediate result to the largest scale in the statement, as OS/VS COBOL
# does, so a chain of divisions loses precision step by step (IBM)
DIALECTS = {
    'default':   ('2-4-8',   True,  False, False, False, False, True,  False),
    'gnu':       ('2-4-8',   True,  True,  False, False, False, True,  False),
    'cobol85':   ('2-4-8',   True,  False, False, False, False, True,  False),
    'cobol2002': ('2-4-8',   True,  False, False, False, False, True,  False),
    'cobol2014': ('2-4-8',   True,  False, False, False, False, True,  False),
    # measured against cobc 3.1.2: PIC 9(2) COMP holding 1289 displays as 09
    # under mf (one-byte storage, value cut to the PICTURE) and as 01289 under
    # ibm (no truncation, and a scaled item loses its decimal point too), so it
    # is ibm that switches truncation off, not mf
    'mf':        ('1-2-4-8', False, True,  False, True,  False, True,  False),
    'ibm':       ('2-4-8',   False, True,  True,  False, False, False, True),
    'acu':       ('1-2-4-8', True,  True,  False, False, True,  True,  False),
}

# measured against cobc 3.1.2 with its run-time checks on: every named
# dialect but the default makes a reference modification of length zero an
# error (cobc -fno-ref-mod-zero-length)
REFMOD_ZERO_ERROR = {'cobol85', 'cobol2002', 'cobol2014', 'mf', 'ibm', 'acu'}

# a PERFORM returns when control reaches the end of its range even while a
# PERFORM begun after it is still active, as OS/VS COBOL and IBM's compilers
# do (cobc -fperform-osvs, which its ibm and mvs dialects set)
PERFORM_OSVS = {'ibm'}

# an overlapping alphanumeric MOVE copies left to right a byte at a time, as
# IBM's MVC instruction does (cobc -fmove-ibm, set by its ibm dialect)
MOVE_IBM = {'ibm'}

# ASSIGN word names the file itself (an IBM DD name, label parts dropped)
# even when a data item has that name, as cobc's ibm dialect has it
ASSIGN_EXTERNAL = {'ibm'}

# B#101, O#777, X#FF, H#FF are numeric literals (ACUCOBOL)
ACU_LITERALS = {'acu'}

_ALIASES = {
    'default': 'default',
    'gnucobol': 'gnu', 'gnu': 'gnu', 'open-cobol': 'gnu',
    'cobol85': 'cobol85', 'cobol-85': 'cobol85', '85': 'cobol85',
    'cobol2002': 'cobol2002', 'cobol-2002': 'cobol2002', '2002': 'cobol2002',
    'cobol2014': 'cobol2014', 'cobol-2014': 'cobol2014', '2014': 'cobol2014',
    'mf': 'mf', 'microfocus': 'mf', 'micro-focus': 'mf',
    'ibm': 'ibm', 'ibm-cobol': 'ibm',
    'acu': 'acu', 'acucobol': 'acu',
    # cobc's other names for these: MVS is IBM's mainframe COBOL, and a
    # -strict dialect is the same choices with the vendor's own words only
    'mvs': 'ibm',
    'ibm-strict': 'ibm', 'mvs-strict': 'ibm', 'mf-strict': 'mf', 'acu-strict': 'acu',
}

# a -strict dialect: YACCC makes its choices, but still accepts the
# extensions the strict one would reject
STRICT = {'ibm-strict', 'mvs-strict', 'mf-strict', 'acu-strict'}


class Dialect:
    """The settings one dialect selects. None for a setting means "not
    changed", so a -f option can override an individual choice."""

    def __init__(self, name='default'):
        try:
            key = _ALIASES[name.lower().strip()]
        except KeyError:
            raise KeyError(name) from None
        bs, trunc, per, hs, nz, sr, pretty, osvs = DIALECTS[key]
        self.name = key
        self.pretty_display = pretty
        self.arithmetic_osvs = osvs
        self.host_sign = hs
        self.nonnum_zero = nz
        self.space_raw = sr
        self.binary_size = bs
        self.binary_truncate = trunc
        self.missing_period = per
        self.refmod_zero = key in REFMOD_ZERO_ERROR
        self.perform_osvs = key in PERFORM_OSVS
        self.assign_clause = 'ibm' if key in ASSIGN_EXTERNAL else 'dynamic'
        self.move_ibm = key in MOVE_IBM
        self.acu_literals = key in ACU_LITERALS

    def __repr__(self):
        return (f"Dialect({self.name}, binary-size={self.binary_size}, "
                f"binary-truncate={self.binary_truncate}, missing-period={self.missing_period})")


def accepted_names():
    """The values -std= takes, for an error message."""
    return sorted(_ALIASES)
