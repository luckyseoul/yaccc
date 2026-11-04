# SPDX-License-Identifier: MIT
"""AST node definitions for the COBOL compiler."""
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .errors import CompileError


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
    float_text: Any = None          # exponent form, when too large for a decimal

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


class PosOf(NumLit):
    """VALUE NEXT / VALUE START OF item: a constant whose value is the place an
    item occupies in its record. The offset is only known once the record has
    been laid out, so the object is filled in then and every expression that
    already holds it sees the value."""
    def __init__(self, kind, ref, loc):
        super().__init__('0', '0', 0, False)
        self.pos_kind = kind          # 'NEXT' or 'START'
        self.pos_ref = ref            # DataRef, or the DataItem for NEXT
        self.loc = loc
        self.resolved = False

    def set_offset(self, off):
        self.text = str(off)
        self.digits = str(off)
        self.scale = 0
        self.neg = False
        self.resolved = True

    def check(self):
        if not self.resolved:
            raise CompileError("the position of this item is not known yet: "
                               "VALUE NEXT / START OF cannot be used to size storage", self.loc)


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
class OmittedCond(Cond):
    ref: Any
    neg: bool = False


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
class EntryStmt(Stmt):
    name: Any = None
    name_ref: Any = None
    using: list = field(default_factory=list)   # ENTRY ... USING items


@dataclass(eq=False)
class Allocate(Stmt):
    target: Any = None
    count: Any = None
    initialized: bool = False
    init_value: Any = None          # ALLOCATE ... INITIALIZED TO value
    returning: Any = None           # ALLOCATE ... RETURNING pointer


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
class JsonParse(Stmt):
    """JSON PARSE text INTO receiver, with WITH DETAIL / NAME OF / SUPPRESS /
    CONVERTING ... FROM JSON BOOLEAN."""
    text: Any = None
    into: Any = None
    detail: bool = False
    names: list = field(default_factory=list)       # (DataRef, str|None); None = IS OMITTED
    suppress: list = field(default_factory=list)
    converting: list = field(default_factory=list)  # (DataRef, ('COND', c) | ('CONDS', t, f) | ('LITS', t, f))
    on_exc: Optional[list] = None
    not_on_exc: Optional[list] = None


@dataclass(eq=False)
class HostVar:
    """A host variable in an EXEC SQL statement, and its indicator variable."""
    ref: Any
    ind: Any = None


@dataclass(eq=False)
class ExecSql(Stmt):
    """An EXEC SQL statement (esql.py): sql is the text the database runs,
    with ? for each input host variable."""
    kind: str = 'EXEC'
    sql: str = ''
    ins: list = field(default_factory=list)          # HostVar
    outs: list = field(default_factory=list)         # HostVar: SELECT INTO, FETCH
    cursor: Optional[str] = None
    stmt: Optional[str] = None                       # a PREPAREd statement's name
    text: Any = None                                 # PREPARE / EXECUTE IMMEDIATE
    args: dict = field(default_factory=dict)         # CONNECT and the like
    release: bool = False
    all: bool = False
    whenever: list = field(default_factory=list)     # (condition, Stmt)


@dataclass(eq=False)
class XmlParse(Stmt):
    """XML PARSE doc PROCESSING PROCEDURE proc [THRU proc2]."""
    doc: Any = None
    proc: Any = None
    thru: Any = None
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
class ScreenPhrases:
    """AT / LINE / COLUMN and the attributes of DISPLAY and ACCEPT on the screen."""
    def __post_init__(self):
        self.screen = False         # an extended DISPLAY / ACCEPT (AT, LINE, UPON CRT ...)
        self.at = None
        self.line = None
        self.col = None
        self.scr_attrs = set()
        self.scr_fg = None
        self.scr_bg = None
        self.scr_prompt = None
        self.scr_size = None
        self.scr_color = None       # COLOR from a data item
        self.timeout = None


class ScrPhrases(ScreenPhrases):
    """The phrases of one operand of a DISPLAY on the screen: as with Micro
    Focus and GnuCOBOL, AT / LINE / COLUMN, SIZE and the attributes apply to
    the operand they follow."""
    def __init__(self):
        self.__post_init__()


@dataclass(eq=False)
class Display(Stmt, ScreenPhrases):
    items: List[Any]
    upon: str = 'SYSOUT'
    no_advancing: bool = False
    on_exc: Optional[list] = None
    not_on_exc: Optional[list] = None
    parts: List[Any] = field(default_factory=list)     # ScrPhrases of each item


@dataclass(eq=False)
class Accept(Stmt, ScreenPhrases):
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
class TraceStmt(Stmt):
    on: bool = True                 # READY TRACE / RESET TRACE


@dataclass(eq=False)
class Continue(Stmt):
    pass


@dataclass(eq=False)
class Unlock(Stmt):
    file: Optional[str]             # UNLOCK file; None: COMMIT / ROLLBACK, every file


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
    kind: str                       # TO UPDOWN TRUE FALSE ADDRESS EXCEPTION
    targets: List[Any]
    value: Any = None
    down: bool = False
    addr_ref: Any = None            # SET ADDRESS OF addr_ref TO value


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
    size: Any = None                # BY VALUE ... SIZE n: bytes passed
    unsigned: bool = False          # BY VALUE ... UNSIGNED


@dataclass(eq=False)
class Call(Stmt):
    prog: Any
    args: List[CallArg]
    returning: Optional[DataRef]
    on_exc: Optional[list]
    not_on_exc: Optional[list]
    returning_omitted: bool = False


@dataclass(eq=False)
class Cancel(Stmt):
    progs: list


@dataclass(eq=False)
class Open(Stmt):
    modes: List[tuple]              # (mode, [file names])
    locked: set = field(default_factory=set)        # OPEN ... file WITH LOCK
    sharing: dict = field(default_factory=dict)     # file -> SHARING of the OPEN


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
    lock: int = 0                   # COB_LOCK_*: WITH LOCK / NO LOCK / KEPT LOCK


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
    alt_keys: List[tuple] = field(default_factory=list)   # (DataRef, dups, sources)
    key_sources: Any = None        # split RECORD KEY: items whose values concatenate
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
    returning_omitted: bool = False   # PROCEDURE DIVISION ... RETURNING OMITTED
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
    screens: list = field(default_factory=list)     # SCREEN SECTION 01 entries
    crt_status: Any = None                          # SPECIAL-NAMES CRT STATUS IS
    cursor: Any = None                              # SPECIAL-NAMES CURSOR IS
    constants: dict = field(default_factory=dict)
    global_constants: dict = field(default_factory=dict)
    typedefs: dict = field(default_factory=dict)     # name -> template item
    proto_progs: dict = field(default_factory=dict)  # REPOSITORY PROGRAM: name -> ext name
    using: List[tuple] = field(default_factory=list)       # (mode, DataRef)
    using_sizes: List[Any] = field(default_factory=list)  # BY VALUE ... SIZE n
    chaining: list = field(default_factory=list)          # PROCEDURE DIVISION CHAINING items
    returning: Any = None
    declaratives: List[Section] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    nested: list = field(default_factory=list)
    parent: Any = None
    debugging: bool = False
    ext_name: str = ''              # name CALL uses (PROGRAM-ID ... AS literal)
    default_rounded: str = 'NEAREST-AWAY-FROM-ZERO'
    # embedded SQL (esql.py): cursors declared, those used WHERE CURRENT OF,
    # whether SQL runs here, whether INCLUDE SQLCA was seen
    sql_cursors: dict = field(default_factory=dict)
    sql_keyed: set = field(default_factory=set)
    sql_used: bool = False
    sql_ca: bool = False


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
