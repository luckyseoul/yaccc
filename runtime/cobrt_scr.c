/* SPDX-License-Identifier: MIT */
/* cobrt_scr.c - SCREEN SECTION, and DISPLAY / ACCEPT ... AT, on a terminal.
 *
 * Output is ANSI (ECMA-48) escape sequences: cursor addressing, erase in
 * line and display, and SGR for the attributes and the eight colours (and
 * their bright forms). Input is the terminal in non-canonical mode through
 * termios, with the xterm/VT220 sequences for the cursor and function keys.
 * There is no curses: nothing to link, nothing to configure.
 *
 * The screen is not switched to an alternate buffer, so what a program left
 * on it stays there when it ends; the cursor then goes below the last line
 * the program used.
 *
 * The items of a screen are placed by these rules (the same as GnuCOBOL's):
 *   LINE n            line n (plus the AT line - 1), column 1 unless COLUMN says
 *   LINE PLUS n       n lines below the previous item, column 1 unless COLUMN says
 *   COLUMN n          column n (plus the AT column - 1) on the current line
 *   COLUMN PLUS n     n columns after the previous item's last column
 *   neither           right after the previous item
 * A group's LINE and COLUMN are a position the items after it are relative
 * to, as if an item ended there: one with neither comes right after it --
 * except before anything else of the screen, when it comes there. DISPLAY
 * and ACCEPT of data items follow the rules at resolve_pos() below.
 */
#include "cobrt.h"
#include <ctype.h>
#include <poll.h>
#include <signal.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

static int scr_used;            /* anything has been drawn */
static int max_line;            /* the lowest line drawn on, for the exit */
static int rows = 24, cols = 80;
static int cur_attr = -1, cur_fg = -2, cur_bg = -2;   /* the SGR state sent last */
static struct termios saved_tio;
static int raw_on;
static int insert_mode;
static cob_field *crt_status;   /* SPECIAL-NAMES CRT STATUS IS */
static cob_field *cursor_item;  /* SPECIAL-NAMES CURSOR IS */
static int last_key;            /* ACCEPT ... FROM ESCAPE KEY */
static unsigned char crt_status_reg[4] = { '0', '0', '0', '0' };
static const cob_attr crt_attr = { COB_NUM_DISPLAY, 4, 0, 0, NULL, 0 };
cob_field cob_crt_status_reg = { 4, crt_status_reg, &crt_attr };

/* ------------------------------------------------------------ output */

static void out(const char *s)
{
	fputs(s, stdout);
}

static void scr_exit(void)
{
	if (raw_on) {
		tcsetattr(0, TCSANOW, &saved_tio);
		raw_on = 0;
	}
	if (!scr_used)
		return;
	/* leave what was drawn on the screen, and the cursor below it */
	printf("\033[0m");
	if (max_line >= rows)
		printf("\r\n");
	else
		printf("\033[%d;1H", max_line + 1);
	fflush(stdout);
}

static void scr_start(void)
{
	if (scr_used)
		return;
	scr_used = 1;
	struct winsize ws;
	if (ioctl(1, TIOCGWINSZ, &ws) == 0 && ws.ws_row > 0 && ws.ws_col > 0) {
		rows = ws.ws_row;
		cols = ws.ws_col;
	} else {
		const char *l = getenv("LINES"), *c = getenv("COLUMNS");
		if (l && atoi(l) > 0)
			rows = atoi(l);
		if (c && atoi(c) > 0)
			cols = atoi(c);
	}
	fflush(stdout);
	atexit(scr_exit);
}

/* COBOL colour numbers (0 black, 1 blue, 2 green, 3 cyan, 4 red, 5 magenta,
 * 6 brown/yellow, 7 white, 8-15 the bright forms) to ANSI colour numbers */
static int ansi_colour(int c)
{
	static const int map[8] = { 0, 4, 2, 6, 1, 5, 3, 7 };
	return map[c & 7];
}

static void set_attr(int attrs, int fg, int bg)
{
	int a = attrs & (COB_SCR_HIGHLIGHT | COB_SCR_LOWLIGHT | COB_SCR_BLINK | COB_SCR_REVERSE |
			 COB_SCR_UNDERLINE | COB_SCR_OVERLINE);
	if (a == cur_attr && fg == cur_fg && bg == cur_bg)
		return;
	char buf[96];
	int n = snprintf(buf, sizeof buf, "\033[0");
	if (a & COB_SCR_HIGHLIGHT)
		n += snprintf(buf + n, sizeof buf - n, ";1");
	if (a & COB_SCR_LOWLIGHT)
		n += snprintf(buf + n, sizeof buf - n, ";2");
	if (a & COB_SCR_UNDERLINE)
		n += snprintf(buf + n, sizeof buf - n, ";4");
	if (a & COB_SCR_BLINK)
		n += snprintf(buf + n, sizeof buf - n, ";5");
	if (a & COB_SCR_REVERSE)
		n += snprintf(buf + n, sizeof buf - n, ";7");
	if (a & COB_SCR_OVERLINE)
		n += snprintf(buf + n, sizeof buf - n, ";53");   /* where the terminal has it */
	if (fg >= 0)
		n += snprintf(buf + n, sizeof buf - n, ";%d", (fg > 7 ? 90 : 30) + ansi_colour(fg));
	if (bg >= 0)
		n += snprintf(buf + n, sizeof buf - n, ";%d", (bg > 7 ? 100 : 40) + ansi_colour(bg));
	snprintf(buf + n, sizeof buf - n, "m");
	out(buf);
	cur_attr = a;
	cur_fg = fg;
	cur_bg = bg;
}

static void move_to(int line, int col)
{
	if (line < 1)
		line = 1;
	if (col < 1)
		col = 1;
	if (line > max_line)
		max_line = line;
	printf("\033[%d;%dH", line, col);
}

/* bytes at (line, col), clipped at the right margin; with a prompt
 * character, the blanks after the last character that is not one show it
 * (all of an empty field: where to type, and how far) */
static void put_text(int line, int col, const unsigned char *s, size_t n, int attrs, int fg, int bg,
		     int secure, int prompt)
{
	if (line < 1 || line > rows || col > cols)
		return;
	if (col < 1)
		col = 1;
	if ((size_t)(cols - col + 1) < n)
		n = (size_t)(cols - col + 1);
	size_t used = n;
	if (prompt)
		while (used > 0 && s[used - 1] == ' ')
			used--;
	move_to(line, col);
	set_attr(attrs, fg, bg);
	for (size_t i = 0; i < n; i++) {
		unsigned char c = s[i];
		if (secure)
			c = '*';        /* every position, as GnuCOBOL shows a SECURE field */
		else if (i >= used)
			c = (unsigned char)prompt;
		else if (c < 32 || c == 127)
			c = ' ';
		fputc(c, stdout);
	}
}

/* erase in the item's background colour, with no other attribute */
static void erase(int what, int line, int col, int bg)
{
	set_attr(0, -1, bg);
	switch (what) {
	case COB_SCR_BLANK_SCREEN:
		out("\033[H\033[2J");
		break;
	case COB_SCR_BLANK_LINE:
		move_to(line, 1);
		out("\033[2K");
		break;
	case COB_SCR_ERASE_EOL:
		move_to(line, col);
		out("\033[K");
		break;
	case COB_SCR_ERASE_EOS:
		move_to(line, col);
		out("\033[J");
		break;
	}
}

/* ------------------------------------------------------------ positions */

/* where a DISPLAY or ACCEPT without a position goes: right after the last
 * thing displayed or accepted (cur_col may be past the right margin), and
 * the line that ended on */
static int cur_line = 1, cur_col = 1, prev_line = 0;

static void set_cur(int line, int col)
{
	cur_line = prev_line = line;
	cur_col = col;
}

typedef struct {
	int line, last;         /* current line, and the column of the last character drawn */
	int off_line, off_col;  /* AT offset: zero, or the AT position minus one */
	int fresh;              /* no elementary item placed yet */
	int at_group;           /* a group placed the position before anything else */
} pos_state;

static int num_of(const cob_field *f)
{
	return f ? (int)cob_get_int(f) : 0;
}

static void place(const cob_scr_item *it, pos_state *ps, int *line, int *col)
{
	int lv = it->line_f ? num_of(it->line_f) : it->line;
	int cv = it->col_f ? num_of(it->col_f) : it->col;
	int l = ps->line, c;
	switch (it->line_mode) {
	case COB_SCR_ABS:
		l = ps->off_line + lv;
		break;
	case COB_SCR_PLUS:
		l = ps->line + lv;
		break;
	case COB_SCR_MINUS:
		l = ps->line - lv;
		break;
	}
	switch (it->col_mode) {
	case COB_SCR_ABS:
		c = ps->off_col + cv;
		break;
	case COB_SCR_PLUS:
		c = ps->last + cv;
		break;
	case COB_SCR_MINUS:
		c = ps->last - cv;
		break;
	default:
		c = it->line_mode ? ps->off_col + 1 : ps->at_group ? ps->last : ps->last + 1;
		break;
	}
	*line = l;
	*col = c;
}

static int item_width(const cob_scr_item *it)
{
	if (it->kind == COB_SCR_LITERAL)
		return it->vlen;
	if (it->kind == COB_SCR_FIELD && it->field)
		return (int)it->field->size;
	return 0;
}

/* draw one item where the rules put it (mode: 0 DISPLAY, 1 ACCEPT, -1 only
 * place it); returns its position */
static void draw_item(const cob_scr_item *it, pos_state *ps, int mode, int *pl, int *pc)
{
	int line, col;
	place(it, ps, &line, &col);
	if (it->kind == COB_SCR_GROUP) {
		/* a group's LINE / COLUMN are where the next item is relative to (a
		 * COLUMN PLUS n of it is n columns on); one with neither comes
		 * right after, or, before anything else of the screen, there */
		int placed = it->line_mode || it->col_mode;
		if (placed) {
			ps->line = line;
			ps->last = col;
			ps->at_group = ps->fresh;
		}
		if (mode == 0) {
			/* BLANK and ERASE are for DISPLAY: an ACCEPT ignores them */
			if (it->attrs & COB_SCR_BLANK_SCREEN)
				erase(COB_SCR_BLANK_SCREEN, 1, 1, it->bg);
			if (placed && (it->attrs & COB_SCR_BLANK_LINE))
				erase(COB_SCR_BLANK_LINE, line, 1, it->bg);
			if (placed && (it->attrs & COB_SCR_ERASE_EOL))
				erase(COB_SCR_ERASE_EOL, line, col, it->bg);
			if (placed && (it->attrs & COB_SCR_ERASE_EOS))
				erase(COB_SCR_ERASE_EOS, line, col, it->bg);
		}
		if (mode >= 0 && (it->attrs & COB_SCR_BELL))
			out("\a");
		*pl = ps->line;
		*pc = ps->last + 1;
		return;
	}
	int w = item_width(it);
	if (mode >= 0) {
		if (mode == 0 && (it->attrs & COB_SCR_BLANK_SCREEN))
			erase(COB_SCR_BLANK_SCREEN, 1, 1, it->bg);
		if (mode == 0 && (it->attrs & COB_SCR_BLANK_LINE))
			erase(COB_SCR_BLANK_LINE, line, 1, it->bg);
		int input = it->attrs & COB_SCR_INPUT;
		int show = it->kind == COB_SCR_LITERAL || (it->attrs & COB_SCR_OUTPUT) || (input && mode);
		if (show && w) {
			const unsigned char *s = it->kind == COB_SCR_LITERAL ? it->value : it->field->data;
			int prompt = input && mode ? (it->prompt ? it->prompt : '_') : 0;
			put_text(line, col, s, (size_t)w, it->attrs, it->fg, it->bg,
				 (it->attrs & COB_SCR_SECURE) != 0, prompt);
		}
		if (it->attrs & COB_SCR_BELL)
			out("\a");
		if (mode == 0 && (it->attrs & COB_SCR_ERASE_EOL))
			erase(COB_SCR_ERASE_EOL, line, col + w, it->bg);
		if (mode == 0 && (it->attrs & COB_SCR_ERASE_EOS))
			erase(COB_SCR_ERASE_EOS, line, col + w, it->bg);
	}
	ps->line = line;
	ps->last = col + w - 1;
	ps->fresh = ps->at_group = 0;
	*pl = line;
	*pc = col;
}

/* the position state at the start of a screen; a part of a screen (an item
 * under the 01) starts where the items before it in the screen leave it,
 * so its relative LINE and COLUMN mean what they mean in the whole screen */
static void start_pos(pos_state *ps, const cob_scr_item *items, int first, int at_line, int at_col)
{
	ps->off_line = at_line > 0 ? at_line - 1 : 0;
	ps->off_col = at_col > 0 ? at_col - 1 : 0;
	ps->line = ps->off_line + 1;
	ps->last = ps->off_col;
	ps->fresh = 1;
	ps->at_group = 0;
	for (int i = 0; i < first; i++) {
		int l, c;
		draw_item(&items[i], ps, -1, &l, &c);
	}
}

void cob_scr_display(const cob_scr_item *items, int first, int n, int at_line, int at_col)
{
	scr_start();
	pos_state ps;
	start_pos(&ps, items, first, at_line, at_col);
	for (int i = first; i < first + n; i++) {
		int l, c;
		draw_item(&items[i], &ps, 0, &l, &c);
	}
	set_cur(ps.line, ps.last + 1);
	set_attr(0, -1, -1);
	fflush(stdout);
}

/* ------------------------------------------------------------ keyboard */

enum {
	K_NONE = 0, K_ENTER = 1, K_TAB, K_BACKTAB, K_UP, K_DOWN, K_LEFT, K_RIGHT, K_HOME, K_END,
	K_INSERT, K_DELETE, K_BACKSPACE, K_PGUP, K_PGDN, K_ESC, K_EOF,
	K_DELETE_EOF,           /* Alt-Delete: to the end of the field */
	K_TIMEOUT,              /* nothing typed within the TIMEOUT */
	K_FN = 100              /* K_FN + n: Fn */
};

/* a signal that ends the program while the terminal is in raw mode puts the
 * terminal back first: Ctrl-C in an ACCEPT must not leave the shell without echo */
static const int raw_signals[] = { SIGINT, SIGTERM, SIGQUIT, SIGHUP };
static struct sigaction old_actions[4];

static void raw_signal(int sig)
{
	tcsetattr(0, TCSANOW, &saved_tio);
	fputs("\033[0m\r\n", stdout);
	fflush(stdout);
	signal(sig, SIG_DFL);
	raise(sig);
}

static void raw_mode(int on)
{
	if (!isatty(0))
		return;
	if (on && !raw_on) {
		struct termios t;
		if (tcgetattr(0, &saved_tio) != 0)
			return;
		struct sigaction sa;
		memset(&sa, 0, sizeof sa);
		sa.sa_handler = raw_signal;
		sigemptyset(&sa.sa_mask);
		for (int i = 0; i < 4; i++)
			sigaction(raw_signals[i], &sa, &old_actions[i]);
		t = saved_tio;
		/* no line editing and no echo; signals (Ctrl-C) still work */
		t.c_lflag &= (tcflag_t) ~(ICANON | ECHO);
		t.c_iflag &= (tcflag_t) ~(ICRNL | IXON);
		t.c_cc[VMIN] = 1;
		t.c_cc[VTIME] = 0;
		tcsetattr(0, TCSANOW, &t);
		raw_on = 1;
	} else if (!on && raw_on) {
		tcsetattr(0, TCSANOW, &saved_tio);
		raw_on = 0;
		for (int i = 0; i < 4; i++)
			sigaction(raw_signals[i], &old_actions[i], NULL);
	}
}

static int get_byte(int wait_ms)
{
	if (wait_ms >= 0) {
		struct pollfd p = { 0, POLLIN, 0 };
		if (poll(&p, 1, wait_ms) <= 0)
			return -1;
	}
	unsigned char c;
	ssize_t r = read(0, &c, 1);
	return r == 1 ? c : -2;
}

static long timeout_ms = -1;     /* the TIMEOUT of the ACCEPT under way, or -1 */

static int read_key(int *ch)
{
	*ch = 0;
	int c = get_byte(timeout_ms >= 0 ? (int)timeout_ms : -1);
	if (c == -1)
		return K_TIMEOUT;
	if (c == -2)
		return K_EOF;
	if (c == 27) {
		char seq[16];
		int n = 0;
		int d = get_byte(60);
		if (d < 0)
			return K_ESC;
		seq[n++] = (char)d;
		if (d == '[' || d == 'O') {
			while (n < 15) {
				int e = get_byte(60);
				if (e < 0)
					break;
				seq[n++] = (char)e;
				if (isalpha(e) || e == '~')
					break;
			}
		}
		seq[n] = 0;
		static const struct { const char *s; int k; } keys[] = {
			{ "[A", K_UP }, { "OA", K_UP }, { "[B", K_DOWN }, { "OB", K_DOWN },
			{ "[C", K_RIGHT }, { "OC", K_RIGHT }, { "[D", K_LEFT }, { "OD", K_LEFT },
			{ "[H", K_HOME }, { "OH", K_HOME }, { "[1~", K_HOME }, { "[7~", K_HOME },
			{ "[F", K_END }, { "OF", K_END }, { "[4~", K_END }, { "[8~", K_END },
			{ "[2~", K_INSERT }, { "[3~", K_DELETE }, { "[5~", K_PGUP }, { "[6~", K_PGDN },
			{ "[Z", K_BACKTAB },
			{ "OP", K_FN + 1 }, { "OQ", K_FN + 2 }, { "OR", K_FN + 3 }, { "OS", K_FN + 4 },
			{ "[11~", K_FN + 1 }, { "[12~", K_FN + 2 }, { "[13~", K_FN + 3 }, { "[14~", K_FN + 4 },
			{ "[15~", K_FN + 5 }, { "[17~", K_FN + 6 }, { "[18~", K_FN + 7 }, { "[19~", K_FN + 8 },
			{ "[20~", K_FN + 9 }, { "[21~", K_FN + 10 }, { "[23~", K_FN + 11 }, { "[24~", K_FN + 12 },
			/* the Linux console's F1-F5 */
			{ "[[A", K_FN + 1 }, { "[[B", K_FN + 2 }, { "[[C", K_FN + 3 }, { "[[D", K_FN + 4 },
			{ "[[E", K_FN + 5 },
			/* Shift-F1 to Shift-F12 are F13 to F24: xterm, then VT220 / rxvt */
			{ "[1;2P", K_FN + 13 }, { "[1;2Q", K_FN + 14 }, { "[1;2R", K_FN + 15 },
			{ "[1;2S", K_FN + 16 }, { "[15;2~", K_FN + 17 }, { "[17;2~", K_FN + 18 },
			{ "[18;2~", K_FN + 19 }, { "[19;2~", K_FN + 20 }, { "[20;2~", K_FN + 21 },
			{ "[21;2~", K_FN + 22 }, { "[23;2~", K_FN + 23 }, { "[24;2~", K_FN + 24 },
			{ "[25~", K_FN + 13 }, { "[26~", K_FN + 14 }, { "[28~", K_FN + 15 },
			{ "[29~", K_FN + 16 }, { "[31~", K_FN + 17 }, { "[32~", K_FN + 18 },
			{ "[33~", K_FN + 19 }, { "[34~", K_FN + 20 },
			{ "[3;3~", K_DELETE_EOF },
		};
		for (size_t i = 0; i < sizeof keys / sizeof keys[0]; i++)
			if (strcmp(seq, keys[i].s) == 0)
				return keys[i].k;
		return K_NONE;          /* an unknown sequence is ignored */
	}
	switch (c) {
	case '\r':
	case '\n':
		return K_ENTER;
	case '\t':
		return K_TAB;
	case 127:
	case 8:
		return K_BACKSPACE;
	}
	if (c >= 32) {
		*ch = c;
		return K_NONE;
	}
	return K_NONE;
}

/* a runtime switch: Y, YES, TRUE, ON or 1 */
static int env_yes(const char *name)
{
	const char *v = getenv(name);
	if (!v || !v[0])
		return 0;
	return strchr("YyTt1", v[0]) != NULL || strcasecmp(v, "on") == 0;
}

/* CRT STATUS for a key that ends an ACCEPT, or -1 for one that doesn't */
static int key_status(int k, int at_first, int at_last)
{
	if (k == K_ENTER)
		return 0;
	if (k >= K_FN)
		return 1000 + (k - K_FN);
	if (k == K_EOF)
		return 8000;
	if (k == K_TIMEOUT)
		return 8001;
	if (k == K_ESC && env_yes("COB_SCREEN_ESC"))
		return 2005;
	if (env_yes("COB_SCREEN_EXCEPTIONS")) {
		if (k == K_PGUP)
			return 2001;
		if (k == K_PGDN)
			return 2002;
		if (k == K_UP && at_first)
			return 2003;
		if (k == K_DOWN && at_last)
			return 2004;
		if (k == K_ESC)
			return 2005;
	}
	return -1;
}

static void set_status(int st)
{
	last_key = st;
	cob_set_int(&cob_crt_status_reg, st);
	if (crt_status)
		cob_set_int(crt_status, st);
}

/* ------------------------------------------------------------ editing */

typedef struct {
	const cob_scr_item *it;
	cob_field *f;           /* what is edited: the field, or a display copy */
	int line, col, width;
	int numeric;            /* numeric DISPLAY: the digits are edited in place */
	int edited;             /* numeric edited: de-edited when the field is left */
	int numtext;            /* the text of a number (another USAGE): digits, sign, point */
} in_field;

static int is_numeric_display(const cob_field *f)
{
	return f->attr->type == COB_NUM_DISPLAY;
}

static void redraw(const in_field *fl)
{
	const cob_scr_item *it = fl->it;
	put_text(fl->line, fl->col, fl->f->data, (size_t)fl->width, it->attrs, it->fg, it->bg,
		 (it->attrs & COB_SCR_SECURE) != 0, it->prompt ? it->prompt : '_');
}

/* after the ACCEPT: the field as it now stands, without prompt characters */
static void redraw_plain(const in_field *fl)
{
	const cob_scr_item *it = fl->it;
	put_text(fl->line, fl->col, fl->f->data, (size_t)fl->width, it->attrs, it->fg, it->bg,
		 (it->attrs & COB_SCR_SECURE) != 0, 0);
}

/* the field is left: a numeric one gets zeros for its blanks, an edited one
 * is read back as a number and edited again */
static void settle(in_field *fl)
{
	cob_field *f = fl->f;
	if (fl->numeric) {
		/* digits typed into a numeric field keep their places; blanks are zeros */
		int sep = (f->attr->flags & COB_F_SIGN_SEP) != 0;
		for (size_t i = 0; i < f->size; i++)
			if (f->data[i] == ' ' && !(sep && ((f->attr->flags & COB_F_SIGN_LEAD) ? i == 0 : i == f->size - 1)))
				f->data[i] = '0';
		if (sep) {
			size_t sp = (f->attr->flags & COB_F_SIGN_LEAD) ? 0 : f->size - 1;
			if (f->data[sp] != '-')
				f->data[sp] = '+';
		}
	} else if (fl->edited) {
		unsigned char tmp[256];
		size_t n = f->size < sizeof tmp ? f->size : sizeof tmp;
		memcpy(tmp, f->data, n);
		cob_move(CF(tmp, n, &cob_attr_alnum), f);
	}
}

static int field_empty(const in_field *fl)
{
	for (int i = 0; i < fl->width; i++)
		if (fl->f->data[i] != ' ' && !(fl->numeric && fl->f->data[i] == '0'))
			return 0;
	return 1;
}

static int field_full(const in_field *fl)
{
	return fl->f->data[fl->width - 1] != ' ';
}

/* REQUIRED and FULL: whether the field may be left */
static int may_leave(const in_field *fl)
{
	int a = fl->it->attrs;
	if ((a & COB_SCR_REQUIRED) && field_empty(fl))
		return 0;
	if ((a & COB_SCR_FULL) && !field_empty(fl) && !field_full(fl))
		return 0;
	return 1;
}

static int accept_fields(in_field *fl, int nf, int start, int start_pos)
{
	int cur = start < 0 || start >= nf ? 0 : start;
	int pos = start_pos > 0 && start_pos < fl[cur].width ? start_pos : 0;
	/* typing replaces characters, unless COB_INSERT_MODE says to insert;
	 * the Insert key switches between the two until the ACCEPT ends */
	insert_mode = env_yes("COB_INSERT_MODE");
	raw_mode(1);
	for (int i = 0; i < nf; i++)
		redraw(&fl[i]);
	int status = -1;
	while (status < 0) {
		in_field *f = &fl[cur];
		if (pos >= f->width)
			pos = f->width - 1;
		move_to(f->line, f->col + pos);
		fflush(stdout);
		int ch;
		int k = read_key(&ch);
		int numeric = f->numeric || f->edited || f->numtext;
		int next = -2;          /* field to move to: -2 none */
		if (k == K_NONE && ch) {
			if (numeric && !(isdigit(ch) || ch == '-' || ch == '+' || ch == '.' || ch == ',' || ch == ' ')) {
				out("\a");
				continue;
			}
			unsigned char *d = f->f->data;
			if (insert_mode && pos < f->width - 1)
				memmove(d + pos + 1, d + pos, (size_t)(f->width - pos - 1));
			d[pos] = (unsigned char)ch;
			redraw(f);
			if (pos < f->width - 1)
				pos++;
			else if (f->it->attrs & COB_SCR_AUTO)
				next = cur + 1 < nf ? cur + 1 : -1;
			else
				pos = f->width;     /* at the end: the cursor waits past the last character */
		} else {
			switch (k) {
			case K_BACKSPACE:
				if (pos > 0) {
					pos--;
					memmove(f->f->data + pos, f->f->data + pos + 1, (size_t)(f->width - pos - 1));
					f->f->data[f->width - 1] = ' ';
					redraw(f);
				}
				break;
			case K_DELETE:
				if (pos < f->width) {
					memmove(f->f->data + pos, f->f->data + pos + 1, (size_t)(f->width - pos - 1));
					f->f->data[f->width - 1] = ' ';
					redraw(f);
				}
				break;
			case K_DELETE_EOF:
				if (pos < f->width) {
					memset(f->f->data + pos, ' ', (size_t)(f->width - pos));
					redraw(f);
				}
				break;
			case K_LEFT:
				if (pos > 0)
					pos--;
				else if (cur > 0)
					next = cur - 1;
				break;
			case K_RIGHT:
				if (pos < f->width - 1)
					pos++;
				else if (cur + 1 < nf)
					next = cur + 1;
				break;
			case K_HOME: {
				/* the first character typed, then the start of the field */
				int b = 0;
				while (b < f->width - 1 && f->f->data[b] == ' ')
					b++;
				if (b == f->width - 1 && f->f->data[b] == ' ')
					b = 0;
				pos = pos == b ? 0 : b;
				break;
			}
			case K_END: {
				/* just after the last character typed, then the end of the field */
				int e = f->width;
				while (e > 0 && f->f->data[e - 1] == ' ')
					e--;
				if (e > f->width - 1)
					e = f->width - 1;
				pos = pos == e ? f->width - 1 : e;
				break;
			}
			case K_INSERT:
				insert_mode = !insert_mode;
				break;
			case K_TAB:
				next = cur + 1 < nf ? cur + 1 : 0;
				break;
			case K_BACKTAB:
				next = cur > 0 ? cur - 1 : nf - 1;
				break;
			case K_UP:
			case K_DOWN: {
				int st = key_status(k, cur == 0, cur == nf - 1);
				if (st >= 0) {
					status = st;
					break;
				}
				if (k == K_UP)
					next = cur > 0 ? cur - 1 : nf - 1;
				else
					next = cur + 1 < nf ? cur + 1 : 0;
				break;
			}
			default: {
				int st = key_status(k, cur == 0, cur == nf - 1);
				if (st == 0 && !may_leave(f)) {
					out("\a");
					break;
				}
				if (st >= 0)
					status = st;
				break;
			}
			}
		}
		if (next != -2 && status < 0) {
			if (!may_leave(f)) {
				out("\a");
				continue;
			}
			settle(f);
			redraw(f);
			if (next == -1)
				status = 0;     /* AUTO in the last field ends the ACCEPT */
			else {
				cur = next;
				pos = 0;
			}
		}
	}
	for (int i = 0; i < nf; i++) {
		settle(&fl[i]);
		redraw_plain(&fl[i]);
	}
	if (cursor_item) {
		int l = fl[cur].line, c = fl[cur].col + (pos < fl[cur].width ? pos : fl[cur].width - 1);
		cob_set_int(cursor_item, cursor_item->size >= 6 ? l * 1000 + c : l * 100 + c);
	}
	set_attr(0, -1, -1);
	fflush(stdout);
	raw_mode(0);
	timeout_ms = -1;
	set_status(status);
	return status;
}

/* the field an ACCEPT starts in, and the place in it: where the CURSOR IS
 * item points, else the first field with INITIAL, else the first */
static int start_field(const in_field *fl, int nf, int *at)
{
	*at = 0;
	if (cursor_item) {
		int v = num_of(cursor_item);
		int l, c;
		if (cursor_item->size >= 6) {
			l = v / 1000;
			c = v % 1000;
		} else {
			l = v / 100;
			c = v % 100;
		}
		for (int i = 0; i < nf; i++)
			if (fl[i].line == l && c >= fl[i].col && c < fl[i].col + fl[i].width) {
				*at = c - fl[i].col;
				return i;
			}
	}
	for (int i = 0; i < nf; i++)
		if (fl[i].it->attrs & COB_SCR_INITIAL)
			return i;
	return 0;
}

int cob_scr_accept(const cob_scr_item *items, int first, int n, int at_line, int at_col)
{
	scr_start();
	pos_state ps;
	start_pos(&ps, items, first, at_line, at_col);
	in_field fl[256];
	int nf = 0;
	for (int i = first; i < first + n; i++) {
		int l, c;
		draw_item(&items[i], &ps, 1, &l, &c);
		const cob_scr_item *it = &items[i];
		if (it->kind == COB_SCR_FIELD && (it->attrs & COB_SCR_INPUT) && it->field && nf < 256) {
			in_field *f = &fl[nf++];
			f->it = it;
			f->f = it->field;
			f->line = l;
			f->col = c;
			f->width = (int)it->field->size;
			f->numeric = is_numeric_display(it->field);
			f->edited = it->field->attr->type == COB_NUM_EDITED;
			f->numtext = 0;
		}
	}
	set_cur(ps.line, ps.last + 1);
	if (nf == 0) {
		set_attr(0, -1, -1);
		fflush(stdout);
		timeout_ms = -1;
		set_status(0);
		return 0;
	}
	int at;
	int sf = start_field(fl, nf, &at);
	return accept_fields(fl, nf, sf, at);
}

/* ------------------------------------------------------------ DISPLAY / ACCEPT ... AT */

/* LINE / COLUMN of an AT phrase: AT llcc (4 digits) or lllccc (6) */
void cob_scr_at(const cob_field *at, int *line, int *col)
{
	int v = num_of(at);
	if (at->size >= 6 || (at->attr->digits >= 6)) {
		*line = v / 1000;
		*col = v % 1000;
	} else {
		*line = v / 100;
		*col = v % 100;
	}
}

/* LINE and COLUMN of a DISPLAY or ACCEPT: -1 not given, 0 relative to the
 * last one (the rules of Micro Focus and GnuCOBOL):
 *   neither given, or both 0   where the last one ended
 *   LINE 0, COLUMN c           column c of the line after the last one's
 *   LINE l, COLUMN 0           line l, the column after the last one's end
 *   LINE l alone               column 1 of line l
 *   COLUMN c alone             column c of line 1
 * A column past the right margin goes on to the next line. */
static void resolve_pos(int *line, int *col)
{
	int l = *line, c = *col;
	if (l < 0 && c < 0)
		l = c = 0;
	else if (l < 0)
		l = 1;
	else if (c < 0)
		c = 1;
	if (l == 0 && c == 0) {
		l = cur_line;
		c = cur_col;
	} else if (l == 0) {
		l = prev_line + 1;
	} else if (c == 0) {
		c = cur_col;
	}
	if (c < 1)
		c = 1;
	while (c > cols) {
		c -= cols;
		l++;
	}
	if (l < 1)
		l = 1;
	if (l > rows)
		l = rows;
	*line = l;
	*col = c;
}

/* the characters a data item shows on the screen */
static size_t screen_text(const cob_field *f, unsigned char *buf, size_t sz)
{
	int t = f->attr->type;
	if (t == COB_ALNUM || t == COB_ALPHA || t == COB_ALNUM_EDITED || t == COB_NUM_DISPLAY ||
	    t == COB_NUM_EDITED || t == COB_GROUP || t == COB_ALL) {
		size_t n = f->size < sz ? f->size : sz;
		memcpy(buf, f->data, n);
		return n;
	}
	/* another USAGE: the value as DISPLAY shows it */
	char tmp[128];
	size_t n = cob_display_text(f, tmp, sizeof tmp);
	if (n > sz)
		n = sz;
	memcpy(buf, tmp, n);
	return n;
}

/* text from (*line, *col) on, going on at the start of the next line at the
 * right margin (clipped at the bottom); the position after it comes back */
static void put_wrapped(int *line, int *col, const unsigned char *s, size_t n, int attrs, int fg,
			int bg)
{
	int l = *line, c = *col;
	while (n > 0 && l <= rows) {
		size_t room = (size_t)(cols - c + 1);
		size_t k = n < room ? n : room;
		put_text(l, c, s, k, attrs, fg, bg, (attrs & COB_SCR_SECURE) != 0, 0);
		s += k;
		n -= k;
		c += (int)k;
		if (n > 0) {
			if (l == rows)
				break;
			l++;
			c = 1;
		}
	}
	*line = l;
	*col = c;
}

/* erase after a DISPLAY: from the position after it */
static void erase_after(int what, int line, int col, int bg)
{
	if (col > cols) {
		if (what == COB_SCR_ERASE_EOL || line >= rows)
			return;
		line++;
		col = 1;
	}
	erase(what, line, col, bg);
}

void cob_scr_display_field(const cob_field *f, int line, int col, int attrs, int fg, int bg, int size)
{
	scr_start();
	if (attrs & COB_SCR_BLANK_SCREEN) {
		erase(COB_SCR_BLANK_SCREEN, 1, 1, bg);
		cur_line = cur_col = 1;
		prev_line = 0;
	}
	resolve_pos(&line, &col);
	if (attrs & COB_SCR_BLANK_LINE)
		erase(COB_SCR_BLANK_LINE, line, 1, bg);
	unsigned char buf[4096];
	size_t n = f ? screen_text(f, buf, sizeof buf) : 0;
	if (size > 0) {
		/* SIZE: the item cut or padded with spaces; a figurative constant
		 * or ALL literal repeated */
		if ((size_t)size > sizeof buf)
			size = (int)sizeof buf;
		for (size_t i = n; i < (size_t)size; i++)
			buf[i] = (attrs & COB_SCR_REPEAT) && n ? buf[i % n] : ' ';
		n = (size_t)size;
	}
	int l = line, c = col;
	put_wrapped(&l, &c, buf, n, attrs, fg, bg);
	if (attrs & COB_SCR_BELL)
		out("\a");
	if (attrs & COB_SCR_ERASE_EOL)
		erase_after(COB_SCR_ERASE_EOL, l, c, bg);
	if (attrs & COB_SCR_ERASE_EOS)
		erase_after(COB_SCR_ERASE_EOS, l, c, bg);
	set_cur(l, c);
	set_attr(0, -1, -1);
	move_to(l, c <= cols ? c : cols);
	fflush(stdout);
}

/* DISPLAY LOW-VALUE, SPACE, ALL X'01', X'02', X'07' at a position */
void cob_scr_display_special(int what, int line, int col, int fg, int bg)
{
	(void)fg;
	scr_start();
	resolve_pos(&line, &col);
	switch (what) {
	case COB_SCR_SP_EOS:
		erase(COB_SCR_ERASE_EOS, line, col, bg);
		break;
	case COB_SCR_SP_EOL:
		erase(COB_SCR_ERASE_EOL, line, col, bg);
		break;
	case COB_SCR_SP_CLEAR:
		erase(COB_SCR_BLANK_SCREEN, 1, 1, bg);
		break;
	case COB_SCR_SP_BELL:
		out("\a");
		break;
	}
	/* the cursor stays where the DISPLAY was: what follows starts there */
	set_cur(line, col);
	set_attr(0, -1, -1);
	move_to(line, col);
	fflush(stdout);
}

/* ACCEPT TIMEOUT n: the next ACCEPT ends with CRT STATUS 8001 when no key
 * comes for n seconds */
void cob_scr_set_timeout(int seconds)
{
	timeout_ms = seconds < 0 ? -1 : (long)seconds * 1000;
}

int cob_scr_accept_field(cob_field *f, int line, int col, int attrs, int fg, int bg, int prompt,
			 int size)
{
	scr_start();
	if (attrs & COB_SCR_BLANK_SCREEN) {
		erase(COB_SCR_BLANK_SCREEN, 1, 1, bg);
		cur_line = cur_col = 1;
		prev_line = 0;
	}
	resolve_pos(&line, &col);
	cob_scr_item it;
	memset(&it, 0, sizeof it);
	it.kind = COB_SCR_FIELD;
	it.attrs = attrs | COB_SCR_INPUT;
	it.fg = (signed char)fg;
	it.bg = (signed char)bg;
	it.prompt = (unsigned char)prompt;
	int t = f->attr->type;
	int update = (attrs & COB_SCR_UPDATE) != 0;
	/* alphanumeric and DISPLAY items are edited in their own bytes; a number
	 * of any other USAGE as text, read back as NUMVAL would read it */
	int direct = t == COB_ALNUM || t == COB_ALPHA || t == COB_NUM_DISPLAY || t == COB_ALNUM_EDITED ||
		     t == COB_NUM_EDITED || t == COB_GROUP;
	unsigned char text[64];
	cob_field tf = { 0, text, &cob_attr_alnum };
	cob_field *ed = f;
	if (!direct) {
		int digits = f->attr->digits ? f->attr->digits : 18;
		if (digits > 38)
			digits = 38;
		tf.size = (size_t)digits + 1 + (f->attr->scale > 0 ? 1 : 0);
		memset(text, ' ', tf.size);
		if (update) {
			char v[128];
			size_t n = cob_display_text(f, v, sizeof v);
			memcpy(text, v, n < tf.size ? n : tf.size);
		}
		ed = &tf;
	} else if (!update) {
		memset(f->data, ' ', f->size);   /* without UPDATE the field starts empty */
	}
	it.field = ed;
	in_field fl;
	fl.it = &it;
	fl.f = ed;
	fl.line = line;
	fl.col = col;
	fl.width = (int)ed->size;
	if (direct && size > 0 && size < fl.width)
		fl.width = size;        /* SIZE: the first characters only */
	fl.numeric = direct && is_numeric_display(ed);
	fl.edited = direct && ed->attr->type == COB_NUM_EDITED;
	fl.numtext = !direct;
	int st = accept_fields(&fl, 1, 0, 0);
	if (!direct)
		cob_move(&tf, f);
	set_cur(line, col + fl.width);
	return st;
}

/* ACUCOBOL's COLOR value: foreground 1-8 (black, blue, green, cyan, red,
 * magenta, brown, white; 9-16 the same in high intensity), background 32 to
 * 256 in steps of 32, 1024 reverse video, 2048 low and 4096 high intensity,
 * 8192 underline, 16384 blink */
void cob_scr_color(int v, int *attrs, int *fg, int *bg)
{
	int f = v & 0x1F, b = (v >> 5) & 0xF;
	if (f >= 1 && f <= 16) {
		*fg = (f - 1) & 7;
		if (f > 8)
			*attrs |= COB_SCR_HIGHLIGHT;
	}
	if (b >= 1 && b <= 8)
		*bg = b - 1;
	if (v & 1024)
		*attrs |= COB_SCR_REVERSE;
	if (v & 2048)
		*attrs |= COB_SCR_LOWLIGHT;
	if (v & 4096)
		*attrs |= COB_SCR_HIGHLIGHT;
	if (v & 8192)
		*attrs |= COB_SCR_UNDERLINE;
	if (v & 16384)
		*attrs |= COB_SCR_BLINK;
}

/* COLOR IS a data item, on an item of a screen */
void cob_scr_color_item(cob_scr_item *it, int v)
{
	int a = it->attrs, f = it->fg, b = it->bg;
	cob_scr_color(v, &a, &f, &b);
	it->attrs = a;
	it->fg = (signed char)f;
	it->bg = (signed char)b;
}

/* ------------------------------------------------------------ registers */

void cob_scr_set_crt_status(cob_field *f)
{
	crt_status = f;
}

void cob_scr_set_cursor(cob_field *f)
{
	cursor_item = f;
}

/* ACCEPT ... FROM ESCAPE KEY: the key that ended the last ACCEPT */
int cob_scr_escape_key(void)
{
	return last_key;
}

/* ------------------------------------------------------------ library routines
 *
 * The screen and keyboard routines programs call by name, on the same
 * terminal state as SCREEN SECTION I/O: CBL_GET_SCR_SIZE, CBL_GET_CSR_POS
 * and CBL_SET_CSR_POS (a row and a column byte, from 0), CBL_READ_KBD_CHAR
 * (a key, without echo), CBL_GET_KBD_STATUS (1 when a key is waiting), X"E4"
 * (clear the screen) and X"E5" (the bell).
 */
static void term_size(int *r, int *c)
{
	struct winsize ws;
	*r = 24;
	*c = 80;
	if (ioctl(1, TIOCGWINSZ, &ws) == 0 && ws.ws_row > 0 && ws.ws_col > 0) {
		*r = ws.ws_row;
		*c = ws.ws_col;
	} else {
		const char *l = getenv("LINES"), *co = getenv("COLUMNS");
		if (l && atoi(l) > 0)
			*r = atoi(l);
		if (co && atoi(co) > 0)
			*c = atoi(co);
	}
}

int cob_sys_cbl_get_scr_size(int n, cob_field **a)
{
	int r, c;
	term_size(&r, &c);
	if (n > 0)
		cob_set_int(a[0], r > 255 ? 255 : r);
	if (n > 1)
		cob_set_int(a[1], c > 255 ? 255 : c);
	return 0;
}

int cob_sys_cbl_get_csr_pos(int n, cob_field **a)
{
	if (n < 1 || a[0]->size < 2)
		return -1;
	int r = cur_line - 1, c = cur_col - 1;
	a[0]->data[0] = (unsigned char)(r < 0 ? 0 : r > 255 ? 255 : r);
	a[0]->data[1] = (unsigned char)(c < 0 ? 0 : c > 255 ? 255 : c);
	return 0;
}

int cob_sys_cbl_set_csr_pos(int n, cob_field **a)
{
	if (n < 1 || a[0]->size < 2)
		return -1;
	scr_start();
	int r = a[0]->data[0] + 1, c = a[0]->data[1] + 1;
	printf("\033[%d;%dH", r, c);
	set_cur(r, c);
	if (r > max_line)
		max_line = r;           /* the program's end leaves the cursor below it */
	fflush(stdout);
	return 0;
}

int cob_sys_cbl_read_kbd_char(int n, cob_field **a)
{
	fflush(stdout);
	raw_mode(1);
	int c = get_byte(-1);
	raw_mode(0);
	if (c < 0)
		return 1;               /* end of input */
	if (n > 0 && a[0]->size)
		a[0]->data[0] = (unsigned char)c;
	return 0;
}

int cob_sys_cbl_get_kbd_status(int n, cob_field **a)
{
	fflush(stdout);
	raw_mode(1);                /* a key typed is there to see before Enter */
	struct pollfd p = { 0, POLLIN, 0 };
	int ready = poll(&p, 1, 0) > 0;
	raw_mode(0);
	if (n > 0)
		cob_set_int(a[0], ready);
	return 0;
}

int cob_sys_x_e4(int n, cob_field **a)
{
	(void)n;
	(void)a;
	scr_start();
	out("\033[0m\033[H\033[2J");
	set_cur(1, 1);
	fflush(stdout);
	return 0;
}

int cob_sys_x_e5(int n, cob_field **a)
{
	(void)n;
	(void)a;
	fputc('\a', stdout);
	fflush(stdout);
	return 0;
}
