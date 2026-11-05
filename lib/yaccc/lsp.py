# SPDX-License-Identifier: MIT
"""yaccc --lsp: a Language Server Protocol server, so that an editor shows
what the compiler finds while the program is being written.

It speaks JSON-RPC on standard input and output, as LSP has it. When a
COBOL document is opened, changed or saved, the front end runs on the
editor's text (not on the file, which may be older): the parser and the code
generator, without the C compiler. What they report comes back as
diagnostics, and what they found answers the other requests:

- textDocument/definition: where the data item, condition name, section or
  paragraph under the cursor is defined, in a copybook too;
- textDocument/references: where the compiler saw it used;
- textDocument/hover: an item's level, PICTURE, USAGE, OCCURS and size, or
  what a procedure is;
- textDocument/documentSymbol: the programs with their data, sections and
  paragraphs, as an outline.

The options given with --lsp (-I, -std, -free, -D, ...) apply to every
document. Changes that come in quick succession are compiled once, when the
editor pauses.
"""
import contextlib
import copy
import json
import os
import select
import sys
import urllib.parse

from . import errors, source
from .data import DataItem, item_desc
from .errors import DIAG, CompileError, ErrorsReported
from .nodes import Paragraph, Section

# LSP's SymbolKind and DiagnosticSeverity numbers
_MODULE, _NAMESPACE, _FUNCTION, _VARIABLE, _CONSTANT, _STRUCT = 2, 3, 12, 13, 14, 23
_ERROR, _WARNING = 1, 2
_WORD = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')


def path_of(uri):
    u = urllib.parse.urlparse(uri)
    return os.path.abspath(urllib.parse.unquote(u.path) if u.scheme == 'file' else uri)


def uri_of(path):
    return 'file://' + urllib.parse.quote(os.path.abspath(path))


class Found:
    """What one compile of a document found."""

    def __init__(self, path, programs, gen):
        self.path = path
        self.programs = programs
        self.gen = gen


class Server:
    def __init__(self, opts, fmt, include_dirs, defines, version=''):
        self.opts = opts
        self.fmt = fmt
        self.include_dirs = include_dirs
        self.defines = defines
        self.version = version
        self.fd_in = sys.stdin.fileno()
        self.out = sys.stdout.buffer
        self.buf = bytearray()
        self.docs = {}          # uri -> the editor's text
        self.found = {}         # uri -> Found
        self.dirty = set()      # uris changed since they were compiled
        self.published = {}     # uri -> the files it has diagnostics in
        self.shut = False

    # ------------------------------------------------------------ JSON-RPC
    def _fill(self, timeout=None):
        """More bytes from standard input; False at its end (or, with a
        timeout, when none came in time)."""
        if timeout is not None and not select.select([self.fd_in], [], [], timeout)[0]:
            return False
        data = os.read(self.fd_in, 65536)
        if not data:
            return False
        self.buf += data
        return True

    def pending(self, wait=0.0):
        return bool(self.buf) or self._fill(wait)

    def read(self):
        while True:
            end = self.buf.find(b'\r\n\r\n')
            if end >= 0:
                break
            if not self._fill():
                return None
        length = 0
        for line in bytes(self.buf[:end]).decode('ascii', 'replace').split('\r\n'):
            name, _, value = line.partition(':')
            if name.strip().lower() == 'content-length':
                length = int(value.strip())
        del self.buf[:end + 4]
        while len(self.buf) < length:
            if not self._fill():
                return None
        body = bytes(self.buf[:length])
        del self.buf[:length]
        return json.loads(body.decode('utf-8'))

    def send(self, msg):
        msg['jsonrpc'] = '2.0'
        data = json.dumps(msg).encode('utf-8')
        self.out.write(b'Content-Length: %d\r\n\r\n' % len(data) + data)
        self.out.flush()

    def serve(self):
        while True:
            # compile what changed once the editor pauses
            if self.dirty and not self.pending(0.25):
                for uri in list(self.dirty):
                    self.analyze(uri)
            msg = self.read()
            if msg is None:
                return 0 if self.shut else 1
            method = msg.get('method')
            mid = msg.get('id')
            if method == 'exit':
                return 0 if self.shut else 1
            try:
                result = self.dispatch(method, msg.get('params') or {})
            except Exception as e:      # a request this server could not answer
                if mid is not None:
                    self.send({'id': mid, 'error': {'code': -32603,
                                                    'message': f"{type(e).__name__}: {e}"}})
                continue
            if mid is None:
                continue
            if result is NotImplemented:
                self.send({'id': mid, 'error': {'code': -32601, 'message': f"no method {method}"}})
            else:
                self.send({'id': mid, 'result': result})

    def dispatch(self, method, p):
        if method == 'initialize':
            return {'capabilities': {'textDocumentSync': {'openClose': True, 'change': 1,
                                                          'save': {'includeText': True}},
                                     'definitionProvider': True, 'referencesProvider': True,
                                     'hoverProvider': True, 'documentSymbolProvider': True},
                    'serverInfo': {'name': 'yaccc', 'version': self.version}}
        if method == 'shutdown':
            self.shut = True
            return None
        doc = p.get('textDocument') or {}
        uri = doc.get('uri')
        if method == 'textDocument/didOpen':
            self.docs[uri] = doc.get('text', '')
            self.analyze(uri)
            return None
        if method == 'textDocument/didChange':
            changes = p.get('contentChanges') or []
            if changes:
                self.docs[uri] = changes[-1].get('text', '')
            self.dirty.add(uri)
            return None
        if method == 'textDocument/didSave':
            if 'text' in p:
                self.docs[uri] = p['text']
            self.analyze(uri)
            return None
        if method == 'textDocument/didClose':
            self.docs.pop(uri, None)
            self.found.pop(uri, None)
            self.dirty.discard(uri)
            for f in self.published.pop(uri, set()):
                self.send({'method': 'textDocument/publishDiagnostics',
                           'params': {'uri': uri_of(f), 'diagnostics': []}})
            return None
        if method in ('textDocument/definition', 'textDocument/references',
                      'textDocument/hover', 'textDocument/documentSymbol'):
            if uri in self.dirty or uri not in self.found:
                self.analyze(uri)
            return {'textDocument/definition': self.definition,
                    'textDocument/references': self.references,
                    'textDocument/hover': self.hover,
                    'textDocument/documentSymbol': self.symbols}[method](uri, p)
        if method is None or method.startswith('$/') or method in (
                'initialized', 'workspace/didChangeConfiguration', 'workspace/didChangeWatchedFiles'):
            return None
        return NotImplemented

    # ------------------------------------------------------------ compiling
    def analyze(self, uri):
        """Compile the document as the editor has it, and publish what the
        compiler says about it."""
        from .driver import compile_sources
        self.dirty.discard(uri)
        if uri not in self.docs:
            return
        path = path_of(uri)
        source.OVERLAY.clear()
        for u, text in self.docs.items():
            source.OVERLAY[path_of(u)] = text       # open copybooks too
        errors._SOURCE_CACHE.clear()
        errors._CUT.clear()
        DIAG.items.clear()
        DIAG.nerrors = 0
        opts = copy.copy(self.opts)
        opts.xref = True
        opts.programs = []
        opts.codegen = None
        # a $DISPLAY directive prints: not into the protocol's channel
        with contextlib.redirect_stdout(sys.stderr):
            try:
                compile_sources([path], opts, self.fmt, self.include_dirs, False, self.defines)
            except ErrorsReported:
                pass
            except CompileError as e:
                DIAG.items.append(('error', e))
            except Exception as e:      # a compiler bug: say so where the editor shows it
                DIAG.items.append(('error', CompileError(
                    f"internal compiler error: {type(e).__name__}: {e}", errors.WHERE)))
        items = list(DIAG.items)
        DIAG.items.clear()
        DIAG.nerrors = 0
        self.found[uri] = Found(path, list(getattr(opts, 'programs', None) or []),
                                getattr(opts, 'codegen', None))
        per = {path: []}
        for kind, e in items:
            loc = getattr(e, 'loc', None)
            f = os.path.abspath(loc.file) if loc is not None and loc.file else path
            line = max(0, (loc.line if loc is not None and loc.line else 1) - 1)
            per.setdefault(f, []).append({'range': self.line_range(f, line),
                                          'severity': _ERROR if kind == 'error' else _WARNING,
                                          'source': 'yaccc', 'message': e.msg})
        for f in self.published.get(uri, set()) - set(per):
            per[f] = []
        for f, diags in per.items():
            self.send({'method': 'textDocument/publishDiagnostics',
                       'params': {'uri': uri_of(f), 'diagnostics': diags}})
        self.published[uri] = {f for f, d in per.items() if d} | {path}

    # ------------------------------------------------------------ positions
    def line_text(self, path, line):
        """Line line (from 0) of a file, as the editor has it if it is open."""
        text = source.OVERLAY.get(path)
        if text is None:
            for u, t in self.docs.items():
                if path_of(u) == path:
                    text = t
                    break
        if text is None:
            return errors.source_line(path, line + 1) or ''
        lines = text.split('\n')
        return lines[line].rstrip('\r') if 0 <= line < len(lines) else ''

    def line_count(self, path):
        for u, t in self.docs.items():
            if path_of(u) == path:
                return len(t.split('\n'))
        n = 0
        while errors.source_line(path, n + 1) is not None:
            n += 1
        return n

    def line_range(self, path, line):
        t = self.line_text(path, line)
        start = len(t) - len(t.lstrip())
        return {'start': {'line': line, 'character': start},
                'end': {'line': line, 'character': max(start, len(t.rstrip()))}}

    def location(self, loc):
        f = os.path.abspath(loc.file)
        return {'uri': uri_of(f), 'range': self.line_range(f, max(0, loc.line - 1))}

    def word_at(self, uri, pos):
        t = self.line_text(path_of(uri), pos.get('line', 0))
        c = min(pos.get('character', 0), len(t))
        a = c
        while a > 0 and t[a - 1] in _WORD:
            a -= 1
        b = c
        while b < len(t) and t[b] in _WORD:
            b += 1
        return t[a:b].strip('-').upper()

    # ------------------------------------------------------------ what is where
    @staticmethod
    def programs(found):
        out = []
        todo = list(found.programs)
        while todo:
            p = todo.pop(0)
            out.append(p)
            todo[0:0] = list(getattr(p, 'nested', []) or [])
        return out

    @staticmethod
    def data_roots(prog):
        roots = list(prog.working) + list(prog.local) + list(prog.linkage)
        for fd in getattr(prog, 'file_descs', []) or []:
            roots += list(getattr(fd, 'records', []) or [])
        roots += list(getattr(prog, 'screens', []) or [])
        return roots

    def targets(self, uri, pos):
        """The definitions of the name under the cursor: what the compiler
        resolved it to on that line, or else whatever has that name."""
        found = self.found.get(uri)
        word = self.word_at(uri, pos)
        if found is None or not word:
            return []
        line = pos.get('line', 0) + 1
        hits = []
        gen = found.gen
        if gen is not None:
            for it, loc, ref in getattr(gen, 'xref_refs', []):
                if loc.line == line and os.path.abspath(loc.file) == found.path and \
                        (getattr(ref, 'name', '') or '').upper() == word and \
                        not any(it is h for h in hits):
                    hits.append(it)
            for proc, loc, _how in getattr(gen, 'xref_procs', []):
                if loc.line == line and os.path.abspath(loc.file) == found.path and \
                        (proc.name or '').upper() == word and not any(proc is h for h in hits):
                    hits.append(proc)
        if hits:
            return hits
        for prog in self.programs(found):
            for r in self.data_roots(prog):
                for it in r.walk():
                    if (it.name or '').upper() == word:
                        hits.append(it)
            for sec in list(prog.declaratives) + list(prog.sections):
                if (sec.name or '').upper() == word:
                    hits.append(sec)
                for para in sec.paragraphs:
                    if (para.name or '').upper() == word:
                        hits.append(para)
        return hits

    def definition(self, uri, p):
        return [self.location(h.loc) for h in self.targets(uri, p.get('position', {}))
                if getattr(h, 'loc', None) is not None]

    def references(self, uri, p):
        hits = self.targets(uri, p.get('position', {}))
        found = self.found.get(uri)
        out = []
        if (p.get('context') or {}).get('includeDeclaration'):
            out += [self.location(h.loc) for h in hits if getattr(h, 'loc', None) is not None]
        gen = found.gen if found is not None else None
        if gen is not None:
            for it, loc, _ref in getattr(gen, 'xref_refs', []):
                if any(it is h for h in hits):
                    out.append(self.location(loc))
            for proc, loc, _how in getattr(gen, 'xref_procs', []):
                if any(proc is h for h in hits):
                    out.append(self.location(loc))
        return out

    def hover(self, uri, p):
        parts = []
        for h in self.targets(uri, p.get('position', {})):
            where = f"{os.path.basename(h.loc.file)}:{h.loc.line}" if getattr(h, 'loc', None) else ''
            if isinstance(h, DataItem):
                desc = item_desc(h)
                size = '' if h.level in (66, 88) else f", {h.size} byte{'s' if h.size != 1 else ''}"
                parts.append(f"```cobol\n{h.level:02d} {h.name or 'FILLER'} {desc}\n```\n"
                             f"defined at {where}{size}")
            elif isinstance(h, Section):
                parts.append(f"section **{h.name}**, {len(h.paragraphs)} paragraph"
                             f"{'s' if len(h.paragraphs) != 1 else ''}, at {where}")
            elif isinstance(h, Paragraph):
                sec = getattr(h, 'section', None)
                inside = f" of section {sec.name}" if sec is not None and sec.name else ''
                parts.append(f"paragraph **{h.name}**{inside}, at {where}")
        if not parts:
            return None
        return {'contents': {'kind': 'markdown', 'value': '\n\n---\n\n'.join(parts)}}

    # ------------------------------------------------------------ outline
    def symbols(self, uri, p):
        found = self.found.get(uri)
        if found is None:
            return []
        return [self.prog_symbol(prog, found.path) for prog in found.programs
                if os.path.abspath(prog.loc.file) == found.path]

    def symbol(self, name, kind, path, first, last, children=None, detail=None):
        a = self.line_range(path, first)
        b = self.line_range(path, max(first, last))
        s = {'name': name or 'FILLER', 'kind': kind,
             'range': {'start': {'line': first, 'character': 0}, 'end': b['end']},
             'selectionRange': a}
        if detail:
            s['detail'] = detail
        if children:
            s['children'] = children
        return s

    def item_symbol(self, it, path):
        kids = [self.item_symbol(c, path) for c in it.children
                if c.level != 66 and os.path.abspath(c.loc.file) == path]
        last = max([it.loc.line] + [x.loc.line for x in it.walk()
                                    if os.path.abspath(x.loc.file) == path]) - 1
        kind = _CONSTANT if it.level == 88 else _STRUCT if it.children else _VARIABLE
        return self.symbol(it.name, kind, path, it.loc.line - 1, last, kids, item_desc(it) or None)

    def prog_symbol(self, prog, path):
        kids = []
        for r in self.data_roots(prog):
            if os.path.abspath(r.loc.file) == path:
                kids.append(self.item_symbol(r, path))
        procs = []
        for sec in list(prog.declaratives) + list(prog.sections):
            if os.path.abspath(sec.loc.file) == path:
                procs.append(sec)
        starts = sorted({x.loc.line for s in procs for x in [s] + list(s.paragraphs)})
        nested = [n for n in getattr(prog, 'nested', []) or [] if os.path.abspath(n.loc.file) == path]
        end_of_prog = (min(n.loc.line for n in nested) - 2) if nested else None

        def last_line(line):
            later = [x for x in starts if x > line]
            if later:
                return later[0] - 2
            return end_of_prog if end_of_prog is not None else self.line_count(path) - 1

        for sec in procs:
            paras = [self.symbol(pa.name, _FUNCTION, path, pa.loc.line - 1, last_line(pa.loc.line))
                     for pa in sec.paragraphs if pa.name and os.path.abspath(pa.loc.file) == path]
            if sec.name:
                end = max([last_line(sec.loc.line)] + [s['range']['end']['line'] for s in paras])
                kids.append(self.symbol(sec.name, _NAMESPACE, path, sec.loc.line - 1, end, paras))
            else:
                kids += paras
        for n in nested:
            kids.append(self.prog_symbol(n, path))
        last = max([prog.loc.line - 1] + [k['range']['end']['line'] for k in kids])
        return self.symbol(prog.ext_name or prog.name, _MODULE, path, prog.loc.line - 1, last, kids)


def serve(opts, fmt, include_dirs, defines, version=''):
    return Server(opts, fmt, include_dirs, defines, version).serve()
