"""The edit list of one short (no windows): pieces of the movie played one after another, like clips on a
CapCut timeline. Split, delete, trim / extend (bring back what was cut), move, bring back a cut part, undo / redo.
Times: 'out' = time in the short, 'src' = time in the movie."""

MIN_PIECE = 0.15


class ShortModel:
    def __init__(self, pieces, duration, auto=None):
        """pieces: [(src_start, length), ...] in play order. duration: length of the movie."""
        self.dur = float(duration)
        self.p = [[float(a), float(a) + float(d)] for a, d in pieces if float(d) > 0.01]
        self.auto = [list(x) for x in (auto or pieces)]
        self.undo_stack, self.redo_stack = [], []

    # ---------------------------------------------------------------- facts
    @property
    def total(self):
        return sum(e - s for s, e in self.p)

    def as_pieces(self):
        return [(round(s, 3), round(e - s, 3)) for s, e in self.p]

    def starts(self):
        out, acc = [], 0.0
        for s, e in self.p:
            out.append(acc)
            acc += e - s
        return out

    def locate(self, t):
        """Short time -> (piece index, movie time)."""
        acc = 0.0
        for i, (s, e) in enumerate(self.p):
            if t < acc + (e - s) or i == len(self.p) - 1:
                return i, min(e, s + max(0.0, t - acc))
            acc += e - s
        return 0, 0.0

    def out_of(self, src):
        """Movie time -> short time (None when that moment is cut out)."""
        acc = 0.0
        for s, e in self.p:
            if s <= src <= e:
                return acc + src - s
            acc += e - s
        return None

    def gaps(self, lo, hi):
        """The cut-out stretches of the movie between lo and hi (in movie time)."""
        kept = sorted((s, e) for s, e in self.p)
        out, t = [], lo
        for s, e in kept:
            if s > t + 0.05:
                out.append((t, min(s, hi)))
            t = max(t, e)
        if hi > t + 0.05:
            out.append((t, hi))
        return [(a, b) for a, b in out if b - a > 0.05 and a < hi and b > lo]

    # ---------------------------------------------------------------- history
    def snap(self):
        self.undo_stack.append([list(x) for x in self.p])
        self.undo_stack = self.undo_stack[-200:]
        self.redo_stack = []

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append([list(x) for x in self.p])
            self.p = self.undo_stack.pop()
            return True
        return False

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append([list(x) for x in self.p])
            self.p = self.redo_stack.pop()
            return True
        return False

    def reset(self):
        self.snap()
        self.p = [[float(a), float(a) + float(d)] for a, d in self.auto]

    # ---------------------------------------------------------------- edits
    def split(self, t):
        """Cut the piece under short time t in two. Returns the index of the new right piece (or None)."""
        i, src = self.locate(t)
        s, e = self.p[i]
        if src - s < MIN_PIECE or e - src < MIN_PIECE:
            return None
        self.snap()
        self.p[i:i + 1] = [[s, src], [src, e]]
        return i + 1

    def delete(self, i):
        if len(self.p) <= 1 or not (0 <= i < len(self.p)):
            return False
        self.snap()
        del self.p[i]
        return True

    def set_edge(self, i, side, src, snap=True):
        """Move the start (side 'l') or end ('r') of piece i to movie time src. Moving it outward brings back what
        was cut there. Pieces that meet again in the movie are joined."""
        if snap:
            self.snap()
        s, e = self.p[i]
        if side == "l":
            self.p[i][0] = min(max(0.0, src), e - MIN_PIECE)
        else:
            self.p[i][1] = max(min(self.dur, src), s + MIN_PIECE)
        self.join()

    def move(self, i, j):
        """Move piece i so that it plays at position j."""
        if i == j or not (0 <= i < len(self.p)):
            return i
        self.snap()
        x = self.p.pop(i)
        j = max(0, min(len(self.p), j))
        self.p.insert(j, x)
        return j

    def bring_back(self, a, b):
        """Put the movie stretch a..b back into the short, at its place in time (next to the piece before it)."""
        a, b = max(0.0, a), min(self.dur, b)
        if b - a < MIN_PIECE:
            return None
        self.snap()
        before = [k for k, (s, e) in enumerate(self.p) if e <= a + 0.05]
        k = max(before, key=lambda k: self.p[k][1]) + 1 if before else 0
        self.p.insert(k, [a, b])
        self.join()
        return k

    def join(self):
        """Pieces next to each other in the short that also follow each other in the movie (touching or overlapping)
        become one piece."""
        out = []
        for s, e in self.p:
            if out and s <= out[-1][1] + 0.02 and s >= out[-1][0] - 0.02:
                out[-1][1] = max(out[-1][1], e)
            else:
                out.append([s, e])
        self.p = out
