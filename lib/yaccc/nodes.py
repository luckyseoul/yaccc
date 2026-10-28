# SPDX-License-Identifier: MIT
"""AST node definitions for the COBOL compiler."""
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass(frozen=True)
class Loc:
    file: str
    line: int

    def __str__(self):
        return f"{self.file}:{self.line}"


# ---------------------------------------------------------------- expressions

class Expr:
    pass


@dataclass(eq=False)
class DataRef(Expr):
    name: str
    quals: List[str]
    subs: List[Any]                 # Expr or the string 'ALL'
    refmod: Optional[tuple]         # (start Expr, length Expr|None)
    loc: Loc
    item: Any = None                # resolved DataItem / IndexName / CondName


@dataclass(eq=False)
class NumLit(Expr):
    text: str                       # canonical text, e.g. "-12.50"
    digits: str                     # digits only, e.g. "1250"
    scale: int
    neg: bool

    @property
    def is_integer(self):
        return self.scale == 0


@dataclass(eq=False)
class StrLit(Expr):
    value: bytes


@dataclass(eq=False)
class Figurative(Expr):
    kind: str                       # SPACE ZERO HIGH-VALUE LOW-VALUE QUOTE NULL


@dataclass(eq=False)
class AllLit(Expr):
    value: bytes                    # repeating pattern
    is_zero: bool = False


@dataclass(eq=False)
class FuncCall(Expr):
    name: str
    args: List[Any]
    refmod: Optional[tuple]
    loc: Loc


@dataclass(eq=False)
class BinOp(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(eq=False)
class Neg(Expr):
    e: Expr


@dataclass(eq=False)
class LengthOf(Expr):
    ref: Any


@dataclass(eq=False)
class AddressOf(Expr):
    ref: Any = None


# ---------------------------------------------------------------- conditions

class Cond:
    pass


@dataclass(eq=False)
class Rel(Cond):
    left: Any
    op: str                         # EQ NE LT LE GT GE
    right: Any


@dataclass(eq=False)
class ClassTest(Cond):
    expr: Any
    cls: str                        # NUMERIC ALPHABETIC ALPHABETIC-LOWER ALPHABETIC-UPPER or user class
    neg: bool


@dataclass(eq=False)
class SignTest(Cond):
    expr: Any
    sign: str                       # POSITIVE NEGATIVE ZERO
    neg: bool


@dataclass(eq=False)
class CondRef(Cond):
    ref: DataRef


@dataclass(eq=False)
class MaybeCond(Cond):
    """Operand standing alone in a condition: either a condition-name or the
    object of an abbreviated combined relation (subject/op from context)."""
    operand: Any
    subject: Any
    op: Optional[str]


@dataclass(eq=False)
class And(Cond):
    a: Cond
    b: Cond


@dataclass(eq=False)
class Or(Cond):
    a: Cond
    b: Cond


@dataclass(eq=False)
class Not(Cond):
    a: Cond


@dataclass(eq=False)
class ConstCond(Cond):
    value: bool


# ---------------------------------------------------------------- statements

@dataclass(eq=False)
class Stmt:
    loc: Loc


@dataclass(eq=False)
class Target:
    ref: DataRef
    rounded: bool = False


@dataclass(eq=False)
class Move(Stmt):
    src: Any
    dsts: List[DataRef]
    corr: bool = False


@dataclass(eq=False)
class Arith(Stmt):
    verb: str                       # ADD SUBTRACT MULTIPLY DIVIDE
    operands: List[Any]             # sending operands
    to: List[Target]                # TO / FROM / BY / INTO targets (in-place)
    giving: List[Target]
    by_or_into: Any = None          # MULTIPLY a BY b GIVING / DIVIDE a BY|INTO b GIVING
    form: str = ''                  # for DIVIDE: 'INTO' or 'BY'
    remainder: Optional[DataRef] = None
    corr: bool = False
    on_error: Optional[list] = None
    not_on_error: Optional[list] = None


@dataclass(eq=False)
class Compute(Stmt):
    targets: List[Target]
    expr: Any
    on_error: Optional[list] = None
    not_on_error: Optional[list] = None


@dataclass(eq=False)
class Exhibit(Stmt):
    items: list = field(default_factory=list)
    named: bool = False
    changed: bool = False


@dataclass(eq=False)
class Allocate(Stmt):
    target: Any = None
    count: Any = None
    initialized: bool = False


@dataclass(eq=False)
class FreeStmt(Stmt):
    target: Any = None


@dataclass(eq=False)
class XmlGenerate(Stmt):
    out: Any = None
    src: Any = None
    declaration: bool = False
    all_attributes: bool = False
    names: list = field(default_factory=list)     # (DataRef, str)
    types: list = field(default_factory=list)     # (DataRef, 'ATTRIBUTE'|'CONTENT')
    suppress: list = field(default_factory=list)  # (DataRef|None, set of figurative, every)
    namespace: Any = None
    namespace_prefix: Any = None
    count_in: Any = None
    on_exc: Optional[list] = None
    not_on_exc: Optional[list] = None


@dataclass(eq=False)
class JsonGenerate(Stmt):
    """JSON GENERATE out FROM src, with NAME OF / SUPPRESS / COUNT IN."""
    out: Any = None
    src: Any = None
    names: list = field(default_factory=list)      # (DataRef, str|None); None = IS OMITTED
    suppress: list = field(default_factory=list)
    count_in: Any = None
    on_exc: Optional[list] = None
    not_on_exc: Optional[list] = None


@dataclass(eq=False)
class Display(Stmt):
    items: List[Any]
    upon: str = 'SYSOUT'
    no_advancing: bool = False
    on_exc: Optional[list] = None
    not_on_exc: Optional[list] = None


@dataclass(eq=False)
class Accept(Stmt):
    target: DataRef
    source: str = 'CONSOLE'
    arg: Any = None
    on_exc: Optional[list] = None
    not_on_exc: Optional[list] = None


@dataclass(eq=False)
class If(Stmt):
    cond: Cond
    then: list
    els: Optional[list]


@dataclass(eq=False)
class WhenObj:
    kind: str                       # ANY TRUE FALSE VALUE RANGE COND
    a: Any = None
    b: Any = None
    neg: bool = False


@dataclass(eq=False)
class Evaluate(Stmt):
    subjects: List[Any]             # Expr / Cond / ('TRUE'|'FALSE')
    whens: List[tuple]              # (list of objlists, stmts)
    other: Optional[list]


@dataclass(eq=False)
class ProcRef:
    name: str
    qual: Optional[str]
    loc: Loc
    target: Any = None              # resolved Paragraph or Section


@dataclass(eq=False)
class Varying:
    var: Any
    frm: Any
    by: Any
    until: Cond


@dataclass(eq=False)
class Perform(Stmt):
    first: Optional[ProcRef]
    last: Optional[ProcRef]
    times: Any = None
    until: Optional[Cond] = None
    test_after: bool = False
    varying: Optional[List[Varying]] = None
    body: Optional[list] = None      # inline statements


@dataclass(eq=False)
class GoTo(Stmt):
    targets: List[ProcRef]
    depending: Any = None


@dataclass(eq=False)
class StopRun(Stmt):
    returning: Any = None


@dataclass(eq=False)
class GoBack(Stmt):
    returning: Any = None


@dataclass(eq=False)
class Exit(Stmt):
    kind: str                       # '' PROGRAM PERFORM CYCLE PARAGRAPH SECTION


@dataclass(eq=False)
class Continue(Stmt):
    pass


@dataclass(eq=False)
class NextSentence(Stmt):
    pass


@dataclass(eq=False)
class StringStmt(Stmt):
    sources: List[tuple]            # (operand, delimiter|'SIZE')
    into: DataRef
    pointer: Optional[DataRef]
    on_overflow: Optional[list]
    not_on_overflow: Optional[list]


@dataclass(eq=False)
class UnstringInto:
    target: DataRef
    delim_in: Optional[DataRef]
    count_in: Optional[DataRef]


@dataclass(eq=False)
class Unstring(Stmt):
    src: DataRef
    delims: List[tuple]             # (all: bool, operand)
    intos: List[UnstringInto]
    pointer: Optional[DataRef]
    tallying: Optional[DataRef]
    on_overflow: Optional[list]
    not_on_overflow: Optional[list]


@dataclass(eq=False)
class InspectRegion:
    before: Any = None
    after: Any = None


@dataclass(eq=False)
class InspectOp:
    mode: str                       # CHARACTERS ALL LEADING FIRST
    pattern: Any                    # operand or None for CHARACTERS
    by: Any                         # replacement operand (REPLACING)
    counter: Any                    # counter DataRef (TALLYING)
    region: InspectRegion


@dataclass(eq=False)
class Inspect(Stmt):
    target: DataRef
    tallying: List[InspectOp]
    replacing: List[InspectOp]
    converting: Optional[tuple]     # (from, to, region)


@dataclass(eq=False)
class Initialize(Stmt):
    targets: List[DataRef]
    replacing: List[tuple]          # (category, operand)
    with_filler: bool = False
    to_value: bool = False
    to_default: bool = False


@dataclass(eq=False)
class SetStmt(Stmt):
    kind: str                       # TO UPDOWN TRUE FALSE
    targets: List[Any]
    value: Any = None
    down: bool = False


@dataclass(eq=False)
class SearchWhen:
    cond: Cond
    stmts: list


@dataclass(eq=False)
class Search(Stmt):
    table: DataRef
    all: bool
    varying: Optional[DataRef]
    at_end: Optional[list]
    whens: List[SearchWhen]


@dataclass(eq=False)
class CallArg:
    mode: str                       # REFERENCE CONTENT VALUE
    value: Any                      # DataRef / literal / 'OMITTED'


@dataclass(eq=False)
class Call(Stmt):
    prog: Any
    args: List[CallArg]
    returning: Optional[DataRef]
    on_exc: Optional[list]
    not_on_exc: Optional[list]


@dataclass(eq=False)
class Cancel(Stmt):
    progs: list


@dataclass(eq=False)
class Open(Stmt):
    modes: List[tuple]              # (mode, [file names])


@dataclass(eq=False)
class Close(Stmt):
    files: List[str]
    opts: list = field(default_factory=list)   # 0 normal, 1 REEL/UNIT, 2 NO REWIND, 3 LOCK


@dataclass(eq=False)
class Read(Stmt):
    file: str
    direction: str                  # '' NEXT PREVIOUS
    into: Optional[DataRef]
    key: Optional[DataRef]
    at_end: Optional[list]
    not_at_end: Optional[list]
    invalid: Optional[list]
    not_invalid: Optional[list]


@dataclass(eq=False)
class Write(Stmt):
    record: DataRef
    frm: Any
    adv_when: str                   # '' BEFORE AFTER
    adv_lines: Any                  # operand or 'PAGE'
    invalid: Optional[list]
    not_invalid: Optional[list]
    eop: Optional[list] = None
    not_eop: Optional[list] = None


@dataclass(eq=False)
class Rewrite(Stmt):
    record: DataRef
    frm: Any
    invalid: Optional[list]
    not_invalid: Optional[list]


@dataclass(eq=False)
class Delete(Stmt):
    file: str
    invalid: Optional[list]
    not_invalid: Optional[list]


@dataclass(eq=False)
class DeleteFile(Stmt):
    files: List[str]


@dataclass(eq=False)
class Start(Stmt):
    file: str
    op: str                         # EQ GT GE LT LE (or '' for default EQ)
    key: Optional[DataRef]
    invalid: Optional[list]
    not_invalid: Optional[list]


@dataclass(eq=False)
class SortKey:
    descending: bool
    ref: DataRef


@dataclass(eq=False)
class Sort(Stmt):
    file: str                       # SD name, or table DataRef for table sort
    keys: List[SortKey]
    duplicates: bool
    using: List[str]
    giving: List[str]
    input_proc: Optional[tuple]     # (ProcRef, ProcRef|None)
    output_proc: Optional[tuple]
    merge: bool = False
    table: Optional[DataRef] = None


@dataclass(eq=False)
class Release(Stmt):
    record: DataRef
    frm: Any


@dataclass(eq=False)
class Return(Stmt):
    file: str
    into: Optional[DataRef]
    at_end: Optional[list]
    not_at_end: Optional[list]


@dataclass(eq=False)
class Alter(Stmt):
    pairs: list = field(default_factory=list)     # [(ProcRef altered, ProcRef new target)]


@dataclass(eq=False)
class StmtBlock(Stmt):
    stmts: list


# ---------------------------------------------------------------- program structure

@dataclass(eq=False)
class Sentence:
    stmts: list
    loc: Loc


@dataclass(eq=False)
class Paragraph:
    name: Optional[str]
    sentences: List[Sentence]
    loc: Loc
    section: Any = None
    id: int = 0


@dataclass(eq=False)
class Section:
    name: Optional[str]
    paragraphs: List[Paragraph]
    loc: Loc
    use_files: Optional[list] = None   # declaratives USE AFTER ERROR ON ...
    use_mode: Optional[str] = None
    use_global: bool = False
    use_reporting: Optional[str] = None    # USE BEFORE REPORTING group-name
    use_debug: Optional[list] = None       # USE FOR DEBUGGING: [DebugTarget]
    segment: int = 0
    id: int = 0


@dataclass(eq=False)
class DebugTarget:
    """Subject of USE FOR DEBUGGING: ALL PROCEDURES (ref is None) or a name
    that turns out to be a procedure, a file or a data item."""
    ref: Optional[DataRef]
    all_refs: bool                  # ALL REFERENCES OF identifier
    loc: Loc


@dataclass(eq=False)
class FileControl:
    name: str
    assign: Any                     # StrLit / DataRef / str (external name) / None
    assign_kind: str = ''           # '' KEYBOARD DISPLAY
    organization: str = 'SEQUENTIAL'
    access: str = 'SEQUENTIAL'
    record_key: Any = None
    alt_keys: List[tuple] = field(default_factory=list)   # (DataRef, dups)
    relative_key: Any = None
    status: Any = None
    optional: bool = False
    loc: Loc = None


@dataclass(eq=False)
class FileDesc:
    name: str
    kind: str                       # FD or SD
    records: list                   # DataItems (01 levels)
    rec_min: int = 0
    rec_max: int = 0
    depending: Any = None
    loc: Loc = None
    control: Any = None
    linage: Any = None
    footing: Any = None
    top: Any = None
    bottom: Any = None
    external: bool = False
    is_global: bool = False
    reports: list = field(default_factory=list)


@dataclass(eq=False)
class Program:
    name: str
    loc: Loc
    is_initial: bool = False
    is_recursive: bool = False
    is_common: bool = False
    is_function: bool = False
    decimal_comma: bool = False
    currency: str = '$'
    mnemonics: dict = field(default_factory=dict)
    switches: dict = field(default_factory=dict)
    switch_conds: dict = field(default_factory=dict)
    alphabets: dict = field(default_factory=dict)
    same_record: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    collating: Any = None
    classes: dict = field(default_factory=dict)
    symbolic: dict = field(default_factory=dict)
    file_controls: List[FileControl] = field(default_factory=list)
    file_descs: List[FileDesc] = field(default_factory=list)
    working: list = field(default_factory=list)
    local: list = field(default_factory=list)
    linkage: list = field(default_factory=list)
    constants: dict = field(default_factory=dict)
    using: List[tuple] = field(default_factory=list)       # (mode, DataRef)
    chaining: list = field(default_factory=list)          # PROCEDURE DIVISION CHAINING items
    returning: Any = None
    declaratives: List[Section] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    nested: list = field(default_factory=list)
    parent: Any = None
    debugging: bool = False
    ext_name: str = ''              # name CALL uses (PROGRAM-ID ... AS literal)
    default_rounded: str = 'NEAREST-AWAY-FROM-ZERO'


@dataclass(eq=False)
class ReportDesc:
    name: str
    loc: Loc
    is_global: bool = False
    code: Any = None                # bytes
    controls: list = field(default_factory=list)   # DataRefs, major to minor
    has_final: bool = False
    page_limit: int = 0             # 0: no PAGE clause
    heading: int = 0
    first_detail: int = 0
    last_detail: int = 0
    footing: int = 0
    line_limit: int = 0             # LINE LIMIT / PAGE ... n COLUMNS (0: none)
    groups: list = field(default_factory=list)     # 01-level report groups


@dataclass(eq=False)
class Initiate(Stmt):
    reports: list


@dataclass(eq=False)
class Generate(Stmt):
    name: Any                       # DataRef: detail group or report


@dataclass(eq=False)
class Terminate(Stmt):
    reports: list


@dataclass(eq=False)
class Suppress(Stmt):
    pass
