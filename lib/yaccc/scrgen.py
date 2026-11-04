# SPDX-License-Identifier: MIT
"""SCREEN SECTION: storage for the screen items, the item tables the runtime
draws and edits from (runtime/cobrt_scr.c), and DISPLAY / ACCEPT of a screen,
or of a data item AT a position."""
from .data import DataItem, layout, resolve_types, T_GROUP
from .errors import CompileError
from .nodes import AllLit, DataRef, NumLit, StrLit, Figurative

ATTR_BITS = {'HIGHLIGHT': 0x1, 'LOWLIGHT': 0x2, 'BLINK': 0x4, 'REVERSE': 0x8,
             'UNDERLINE': 0x10, 'SECURE': 0x20, 'AUTO': 0x40, 'REQUIRED': 0x80, 'FULL': 0x100,
             'BLANK-SCREEN': 0x200, 'BLANK-LINE': 0x400, 'ERASE-EOL': 0x800,
             'ERASE-EOS': 0x1000, 'BELL': 0x2000, 'UPDATE': 0x4000, 'INITIAL': 0x20000,
             'OVERLINE': 0x80000}
INPUT = 0x8000
OUTPUT = 0x10000
REPEAT = 0x40000
# DISPLAY of these figurative constants does something of its own (as with
# Micro Focus): only the position, erase to the end of the screen or line,
# erase the screen, the bell
SPECIAL_FIG = {b'\x00': 'COB_SCR_SP_CURSOR', b' ': 'COB_SCR_SP_EOS'}
SPECIAL_ALL = {b'\x00': 'COB_SCR_SP_CURSOR', b' ': 'COB_SCR_SP_EOS', b'\x01': 'COB_SCR_SP_EOL',
               b'\x02': 'COB_SCR_SP_CLEAR', b'\x07': 'COB_SCR_SP_BELL'}
# what a screen item passes on to the items below it
INHERITED = {'HIGHLIGHT', 'LOWLIGHT', 'BLINK', 'REVERSE', 'UNDERLINE', 'OVERLINE', 'SECURE',
             'AUTO', 'REQUIRED', 'FULL', 'UPDATE'}
POS_MODE = {None: 'COB_SCR_NONE', 'ABS': 'COB_SCR_ABS', 'PLUS': 'COB_SCR_PLUS',
            'MINUS': 'COB_SCR_MINUS'}


class ScreenInfo:
    """One 01 screen: its storage and its flattened item table."""

    def __init__(self, root):
        self.root = root
        self.sym = None             # storage of the fields
        self.size = 0               # bytes of storage
        self.tab = None             # the item table
        self.entries = []           # ScrEntry, in the order they are drawn
        self.span = {}              # id(item) -> (first index, count)


class ScrEntry:
    """One row of a screen's item table: an item, or one occurrence of it."""

    def __init__(self, item, kind, attrs, fg, bg, prompt, subs, color=None):
        self.item, self.kind = item, kind
        self.attrs, self.fg, self.bg, self.prompt = attrs, fg, bg, prompt
        self.color = color          # COLOR IS a data item
        self.static = None          # (attribute bits, fg, bg) in the table
        self.subs = subs            # occurrence numbers, outermost first
        self.field = None           # the cob_field of a FIELD
        self.src = None             # FROM / USING, with those as subscripts
        self.dst = None             # TO / USING


class ScreenGen:
    # ---------------------------------------------------------------- layout
    def scr_layout(self, prog):
        """Give the fields of every screen their storage, and the names their
        place among the program's names."""
        self.ctx.screens = []
        for root in prog.screens:
            si = ScreenInfo(root)
            si.sym = self.sym('scr_')
            off = 0
            for it in root.walk():
                it.section = 'SCREEN'
                it.record = root
                it.screen = si
                if it.pic is not None and not it.children:
                    resolve_types(it, self.opts)
                    layout(it, 0)
                    it.offset = off
                    it.storage = si.sym
                    off += it.size
                elif it.children or it.pic is None:
                    it.type = T_GROUP
                    it.size = 0
                    it.offset = 0
                    it.storage = si.sym
            si.size = off
            self.register_tree(root)
            self.ctx.screens.append(si)

    def scr_flatten(self, si):
        """The items of a screen in the order they are drawn, each with the
        attributes it inherits from the groups above it; an item with OCCURS
        once for each occurrence."""
        def walk(it, inh, fg, bg, prompt, color, subs):
            attrs = set(inh) | set(it.scr_attrs)
            fg = it.scr_fg if it.scr_fg is not None else fg
            bg = it.scr_bg if it.scr_bg is not None else bg
            prompt = it.scr_prompt if it.scr_prompt is not None else prompt
            color = it.scr_color if it.scr_color is not None else color
            start = len(si.entries)
            n = it.occurs.max if getattr(it, 'occurs', None) else 0
            for k in range(n or 1):
                sub = subs + [k + 1] if n else subs
                kind = ('GROUP' if it.children else 'FIELD' if it.pic is not None else
                        'LITERAL' if it.value is not None else
                        'GROUP')        # no PIC and no VALUE: positions and attributes only
                si.entries.append(ScrEntry(it, kind, attrs, fg, bg, prompt, sub, color))
                for c in it.children:
                    walk(c, attrs & INHERITED, fg, bg, prompt, color, sub)
            # an item under an OCCURS: DISPLAY / ACCEPT of it is of the first
            si.span.setdefault(id(it), (start, len(si.entries) - start))
        walk(si.root, set(), None, None, None, None, [])

    def scr_implicit(self, ref, subs):
        """FROM / TO / USING in an item with OCCURS: a table item named
        without subscripts gets the occurrence numbers (the innermost ones,
        as many as it has dimensions)."""
        if not subs or not isinstance(ref, DataRef) or ref.subs:
            return ref
        try:
            target = self.resolve(ref)
        except CompileError:
            return ref
        dims = len(target.occurs_chain()) if isinstance(target, DataItem) else 0
        if dims == 0:
            return ref
        use = subs[-dims:] if dims <= len(subs) else subs
        lits = [NumLit(str(k), str(k), 0, False) for k in use]
        return DataRef(ref.name, ref.quals, lits, ref.refmod, ref.loc)

    def scr_number(self, v, what, loc):
        """A LINE / COLUMN / colour: (constant, field expression or NULL)."""
        if v is None:
            return 0, 'NULL'
        if isinstance(v, int):
            return v, 'NULL'
        if isinstance(v, DataRef):
            return 0, self.static_field(v)
        raise CompileError(f"{what} must be an integer or a data item", loc)

    def scr_tables(self, prog):
        for si in self.ctx.screens:
            self.scr_flatten(si)
            si.tab = self.sym('scrtab_')
            rows = []
            fields = []
            off = si.size
            seen = set()
            for e in si.entries:
                it, kind, attrs = e.item, e.kind, e.attrs
                bits = 0
                for a in attrs:
                    bits |= ATTR_BITS.get(a, 0)
                lmode, lval = it.scr_line or (None, None)
                cmode, cval = it.scr_col or (None, None)
                line, line_f = self.scr_number(lval, 'LINE', it.loc)
                col, col_f = self.scr_number(cval, 'COLUMN', it.loc)
                value, vlen, field = 'NULL', 0, 'NULL'
                if kind == 'LITERAL':
                    v = it.value
                    if isinstance(v, StrLit):
                        b = v.value
                    elif isinstance(v, NumLit):
                        b = v.text.encode('latin-1')
                    elif isinstance(v, Figurative):
                        b = {'SPACE': b' ', 'ZERO': b'0', 'QUOTE': b'"', 'HIGH-VALUE': b'\xff',
                             'LOW-VALUE': b'\x00'}.get(v.kind, b' ')
                    else:
                        b = getattr(v, 'value', b'') or b''
                    from .codegen import c_string
                    value, vlen = f"(const unsigned char *){c_string(b)}", len(b)
                    bits |= OUTPUT
                elif kind == 'FIELD':
                    # the first occurrence is the item's own storage, the
                    # others follow the screen's
                    if id(it) in seen:
                        at = off
                        off += it.size
                    else:
                        seen.add(id(it))
                        at = it.offset
                    fs = self.sym('scrf_')
                    fields.append(f"static cob_field {fs} = {{{it.size}, {si.sym} + {at}, "
                                  f"&{self.item_attr(it)}}};")
                    field = '&' + fs
                    e.field = '&' + fs
                    e.src = self.scr_implicit(it.scr_from, e.subs)
                    e.dst = self.scr_implicit(it.scr_to, e.subs)
                    if it.scr_to is not None:
                        bits |= INPUT
                    if it.scr_from is not None or it.value is not None:
                        bits |= OUTPUT
                fgv = e.fg if isinstance(e.fg, int) else -1
                bgv = e.bg if isinstance(e.bg, int) else -1
                e.static = (bits, fgv, bgv)
                pr = e.prompt[0] if e.prompt else 0
                kc = {'GROUP': 'COB_SCR_GROUP', 'LITERAL': 'COB_SCR_LITERAL', 'FIELD': 'COB_SCR_FIELD'}[kind]
                rows.append(f"\t{{{kc}, {POS_MODE[lmode]}, {POS_MODE[cmode]}, {line}, {col}, "
                            f"{line_f}, {col_f}, {value}, {vlen}, {field}, {bits}, {fgv}, {bgv}, {pr}}},")
            self.glob.append(f"static unsigned char {si.sym}[{max(off, 1)}]; "
                             f"/* SCREEN {si.root.name or 'FILLER'} */")
            self.glob.extend(fields)
            # not const: a colour from a data item is set just before use
            self.glob.append(f"static cob_scr_item {si.tab}[] = {{")
            self.glob.extend(rows)
            self.glob.append("};")

    def scr_init(self, prog, em):
        """Program start: the fields' initial contents, CRT STATUS and CURSOR."""
        for si in getattr(self.ctx, 'screens', []):
            for e in si.entries:
                if e.kind == 'FIELD':
                    it = e.item
                    if it.value is not None:
                        em(self.value_move(it.value, e.field, it))
                    else:
                        em(f"cob_move(&cob_fig_space, {e.field});"
                           if it.category() not in ('NUMERIC', 'NUMERIC-EDITED')
                           else f"cob_move(&cob_fig_zero, {e.field});")
        if getattr(prog, 'crt_status', None) is not None:
            em(f"cob_scr_set_crt_status({self.static_field(prog.crt_status)});")
        if getattr(prog, 'cursor', None) is not None:
            em(f"cob_scr_set_cursor({self.static_field(prog.cursor)});")

    # ---------------------------------------------------------------- statements
    def screen_item(self, ref):
        """The screen item an operand names, or None."""
        if not isinstance(ref, DataRef):
            return None
        try:
            it = self.resolve(ref)
        except CompileError:
            return None
        return it if getattr(it, 'section', None) == 'SCREEN' else None

    def scr_position(self, s, absent='-1'):
        """C expressions for the line and column of an AT / LINE / COLUMN phrase
        (absent: the value for one not given)."""
        em = self.em
        if s.at is not None:
            em("int cob_at_l = 0, cob_at_c = 0;")
            em(f"cob_scr_at({self.field(s.at)}, &cob_at_l, &cob_at_c);")
            return 'cob_at_l', 'cob_at_c'
        line = f"(int)({self.int_expr(s.line)})" if s.line is not None else absent
        col = f"(int)({self.int_expr(s.col)})" if s.col is not None else absent
        return line, col

    def scr_look(self, s):
        """C expressions for the attribute bits, foreground and background of
        a DISPLAY / ACCEPT phrase list (COLOR from a data item at run time)."""
        bits = self.scr_attr_bits(s)
        fg, bg = self.scr_colour(s.scr_fg), self.scr_colour(s.scr_bg)
        if getattr(s, 'scr_color', None) is None:
            return bits, fg, bg
        self.em(f"int cob_ca = {bits}, cob_cf = {fg}, cob_cb = {bg};")
        self.em(f"cob_scr_color((int)({self.int_expr(s.scr_color)}), &cob_ca, &cob_cf, &cob_cb);")
        return 'cob_ca', 'cob_cf', 'cob_cb'

    def scr_attr_bits(self, s):
        bits = 0
        for a in s.scr_attrs:
            bits |= ATTR_BITS.get(a, 0)
        return bits

    def scr_colour(self, v):
        if v is None:
            return '-1'
        if isinstance(v, int):
            return str(v)
        return f"(int)({self.int_expr(v)})"

    def scr_refresh(self, si, first, count, sources):
        """Moves FROM / USING sources into the fields of a span (sources: the
        output side), and sets colours that come from data items."""
        em = self.em
        for k in range(first, first + count):
            e = si.entries[k]
            if e.kind == 'FIELD' and sources and e.src is not None:
                em(f"cob_move({self.field(e.src)}, {e.field});")
            if e.color is not None:
                bits, fgv, bgv = e.static
                em(f"{si.tab}[{k}].attrs = {bits}; {si.tab}[{k}].fg = {fgv}; {si.tab}[{k}].bg = {bgv};")
            for which, v in (('fg', e.fg), ('bg', e.bg)):
                if isinstance(v, DataRef):
                    em(f"{si.tab}[{k}].{which} = (signed char){self.int_expr(v)};")
            if e.color is not None:
                em(f"cob_scr_color_item(&{si.tab}[{k}], (int)({self.int_expr(e.color)}));")

    def g_screen_display(self, s, it):
        em = self.em
        si = it.screen
        first, count = si.span[id(it)]
        em("{")
        em.ind += 1
        self.scr_refresh(si, first, count, True)
        line, col = self.scr_position(s, '0')
        em(f"cob_scr_display({si.tab}, {first}, {count}, {line}, {col});")
        em.ind -= 1
        em("}")

    def g_screen_accept(self, s, it):
        em = self.em
        si = it.screen
        first, count = si.span[id(it)]
        em("{")
        em.ind += 1
        self.scr_refresh(si, first, count, True)
        line, col = self.scr_position(s, '0')
        self.scr_timeout(s)
        em(f"int cob_k = cob_scr_accept({si.tab}, {first}, {count}, {line}, {col});")
        for k in range(first, first + count):
            e = si.entries[k]
            if e.kind == 'FIELD' and e.dst is not None:
                self.check_receiving(e.dst)
                em(f"cob_move({e.field}, {self.field(e.dst)});")
        self.handlers('cob_k != 0', s.on_exc, s.not_on_exc)
        em.ind -= 1
        em("}")

    def scr_timeout(self, s):
        """ACCEPT ... TIMEOUT n: n seconds without a key end the ACCEPT."""
        if getattr(s, 'timeout', None) is not None:
            self.em(f"cob_scr_set_timeout((int)({self.int_expr(s.timeout)}));")

    def scr_size(self, v):
        """SIZE of a DISPLAY operand: -1 when not given (0 is its own size)."""
        if v is None:
            return '-1'
        if isinstance(v, Figurative) and v.kind == 'ZERO':
            return '0'
        return f"(int)({self.int_expr(v)})"

    def g_display_at(self, s):
        """DISPLAY on the screen: each operand where its own AT / LINE /
        COLUMN puts it, or right after the one before, with its own SIZE and
        attributes."""
        em = self.em
        em("{")
        em.ind += 1
        if not s.items:
            # DISPLAY WITH BLANK SCREEN and the like
            line, col = self.scr_position(s)
            em(f"cob_scr_display_field(NULL, {line}, {col}, {self.scr_attr_bits(s)}, "
               f"{self.scr_colour(s.scr_fg)}, {self.scr_colour(s.scr_bg)}, -1);")
        for item, ph in zip(s.items, s.parts):
            if self.screen_item(item) is not None:
                self.g_screen_display(ph, self.screen_item(item))
                continue
            em("{")
            em.ind += 1
            line, col = self.scr_position(ph)
            bits, fg, bg = self.scr_look(ph)
            size = self.scr_size(ph.scr_size)
            special = None
            if isinstance(item, Figurative) and ph.scr_size is None:
                special = SPECIAL_FIG.get({'LOW-VALUE': b'\x00', 'SPACE': b' '}.get(item.kind))
            elif isinstance(item, AllLit) and len(set(item.value)) == 1:
                special = SPECIAL_ALL.get(item.value[:1])
                if item.value[:1] == b' ' and ph.scr_size is not None:
                    special = None          # SIZE n: n spaces
            if special is not None:
                em(f"cob_scr_display_special({special}, {line}, {col}, {fg}, {bg});")
            else:
                if isinstance(item, (Figurative, AllLit)):
                    bits = f"({bits}) | {REPEAT}"
                em(f"cob_scr_display_field({self.field(item)}, {line}, {col}, {bits}, {fg}, {bg}, "
                   f"{size});")
            em.ind -= 1
            em("}")
        em.ind -= 1
        em("}")

    def g_accept_at(self, s):
        em = self.em
        self.check_receiving(s.target)
        em("{")
        em.ind += 1
        line, col = self.scr_position(s)
        bits, fg, bg = self.scr_look(s)
        prompt = s.scr_prompt[0] if s.scr_prompt else 0
        self.scr_timeout(s)
        em(f"int cob_k = cob_scr_accept_field({self.field(s.target)}, {line}, {col}, {bits}, "
           f"{fg}, {bg}, {prompt}, {self.scr_size(s.scr_size)});")
        self.handlers('cob_k != 0', s.on_exc, s.not_on_exc)
        em.ind -= 1
        em("}")
