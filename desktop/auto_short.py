"""Auto Short: continuous-dialogue shorts, made clip by clip.

The movie (or the chosen range / parts) is scanned in small chunks. As soon as enough dialogue has been found for
one short, that short is cut and exported - while the scan of the next stretch goes on. Silence is removed from
the picture AND the sound, so the result is people talking continuously.
"""
import os, json, shutil
import dialogue as D
import engine as E

MIN_LEN = 45.0
MAX_LEN = 59.0
CHUNK = 120.0              # seconds of movie scanned at a time (the first short appears after the first chunks)
GOOD_GAP = 1.0             # a pause at least this long is a natural place to end a short
MAX_PIECES = 120           # keeps the ffmpeg command short enough for Windows


def piece_cap(min_len, max_len):
    """Longest piece we keep whole. Smaller than (max - min) so a group can always be filled to a valid length."""
    return min(12.0, max(1.0, (max_len - min_len) * 0.9))


def total_len(buf):
    return sum(e - s for s, e in buf)


def pick_group(buf, min_len, max_len, final=False):
    """buf: [(start, end), ...] in time order. Returns (group, rest), or None when more dialogue is needed.

    The group is filled up to max_len. If a long pause (>= GOOD_GAP) exists after the minimum length, the short
    ends there (a natural end of an exchange); otherwise it is filled to the maximum."""
    total, n = 0.0, 0
    for s, e in buf:
        if total + (e - s) > max_len:
            break
        total += e - s
        n += 1
    overflow = n < len(buf)
    if not overflow:
        if final and total >= min_len:
            return buf, []
        return None
    if total < min_len:
        return None
    # end the short at the BIGGEST pause after the minimum length (a pause = the end of a sentence), never in the
    # middle of talking when a pause exists; a long pause (>= GOOD_GAP) later on wins a tie
    best_k, best_gap, acc = n, -1.0, 0.0
    for k in range(1, n + 1):
        acc += buf[k - 1][1] - buf[k - 1][0]
        if acc >= min_len and k < len(buf):
            gap = buf[k][0] - buf[k - 1][1]
            if gap >= best_gap or (gap >= GOOD_GAP and best_gap >= GOOD_GAP):
                best_k, best_gap = k, gap
    return buf[:best_k], buf[best_k:]


END_HOLD = 0.3             # the last words of a short get this much more time (if the pause allows it)


def hold_end(group, rest, limit):
    """The end of a short: a little extra time after the last word, but never into the next dialogue piece."""
    if not group:
        return group
    s, e = group[-1]
    room = (rest[0][0] - 0.05) if rest else limit
    return group[:-1] + [(s, max(e, min(e + END_HOLD, room)))]


def limit_pieces(pieces, max_n=MAX_PIECES):
    """[(start, length), ...]: if there are too many, the smallest gaps are bridged (nothing is dropped)."""
    pieces = [list(p) for p in pieces]
    while len(pieces) > max_n:
        gaps = [(pieces[i + 1][0] - (pieces[i][0] + pieces[i][1]), i) for i in range(len(pieces) - 1)]
        _, i = min(gaps)
        pieces[i][1] = pieces[i + 1][0] + pieces[i + 1][1] - pieces[i][0]
        del pieces[i + 1]
    return [tuple(p) for p in pieces]


def relative_items(items, total, number):
    """Overlay / text items of the Simple Edit tab -> items timed from the START of a short.
    rel_start / rel_end are seconds from the start of the clip (rel_end 0 = until the end)."""
    ovs, txs = [], []
    for it in items:
        d = dict(it)
        rs = float(it.get("rel_start", 0.0) or 0.0)
        re_ = float(it.get("rel_end", 0.0) or 0.0)
        d["start"] = rs
        d["end"] = min(total, re_) if re_ > 0 else total
        if it.get("kind") == "text":
            d["text"] = str(it.get("text", "")).replace("{n}", str(number))
        if d["end"] <= d["start"]:
            continue
        (ovs if it.get("kind") == "overlay" else txs).append(d)
    return ovs, txs


class AutoShortJob:
    """ranges: [(start, end), ...] in movie seconds. Each range is scanned on its own; a short never mixes
    dialogue from two different ranges."""

    def __init__(self, movie, ranges, opts, settings, items, out_dir, log, progress, on_short,
                 min_len=MIN_LEN, max_len=MAX_LEN, first_number=1, keep_last=False, chunk=CHUNK,
                 all_ranges=None, index_base=0, prior_made=None, on_resume=None):
        self.movie, self.ranges = movie, ranges
        self.opts, self.items, self.out_dir = dict(opts), items, out_dir
        # fewer flash cuts / nothing important lost: tiny pauses are not cut, sentence ends get more time,
        # soft talking counts as talking (each can be changed in the Auto Short panel)
        self.opts.setdefault("tail_ms", 350)
        self.opts.setdefault("min_cut_ms", 500)
        self.opts.setdefault("vad_threshold", 0.45)
        self.log, self.progress, self.on_short = log, progress, on_short
        self.min_len, self.max_len = float(min_len), float(max_len)
        self.number = int(first_number)
        self.keep_last = keep_last
        self.chunk = float(chunk)
        s = dict(settings)
        s["_denoise"] = bool(opts.get("denoise", True))
        s["_joint_fade"] = D.FADE
        s["fade_sec"] = 0.05
        boost = opts.get("boost")                          # retention boost; None / empty = off
        s["_boost"] = dict(E.BOOST_DEFAULT, **boost) if isinstance(boost, dict) and boost else {}
        self.runner = E.Runner(s, log, lambda *a: None, lambda c: None)
        self.made = 0
        self.stopped = False
        # resume: where to carry on if this run is stopped (saved after every chunk and every short)
        self.all_ranges = [list(map(float, r)) for r in (all_ranges or ranges)]
        self.index_base = int(index_base)
        self.made_list = list(prior_made or [])
        self.on_resume = on_resume
        self.ri = 0

    def stop(self):
        self.stopped = True
        self.runner.stop()

    # ------------------------------------------------------------------
    def run(self):
        self.info = E.probe_info(self.movie)
        self.crop = E.detect_crop(self.movie, self.info["duration"]) if self.runner.s["auto_crop"] else None
        if self.crop:
            self.log(f"Black bars detection: {self.crop}")
        self.base = E.Runner.safe_name(self.movie)[:40]
        os.makedirs(self.out_dir, exist_ok=True)
        self.work = os.path.join(self.out_dir, "_work")
        self.span_total = max(1.0, sum(b - a for a, b in self.ranges))
        self.span_done = 0.0
        self.mark(self.ranges[0][0])
        try:
            carry = []
            for ri, (a, b) in enumerate(self.ranges):
                if self.stopped:
                    break
                self.ri = ri
                if len(self.ranges) > 1:
                    self.log(f"--- Range {ri + 1}/{len(self.ranges)}: {_mmss(a)} - {_mmss(b)} ---")
                # ranges that follow each other directly (e.g. many 45 s parts) are one stretch of movie: the dialogue
                # left over at the end of one range goes on into the next range instead of being thrown away
                joins = ri + 1 < len(self.ranges) and abs(self.ranges[ri + 1][0] - b) < 1.0
                carry = self.scan_range(a, b, carry, flush=not joins) or []
                if self.stopped:
                    break
                self.span_done += b - a
                if ri + 1 < len(self.ranges):                    # this range is finished: carry on with the next one
                    self.ri = ri + 1
                    self.mark(self.ranges[ri + 1][0])
                else:
                    self.mark(b, finished=True)
        finally:
            shutil.rmtree(self.work, ignore_errors=True)
        if self.stopped:
            self.progress(self.span_done / self.span_total, f"Stopped - {self.made} short(s) ready. "
                                                            f"You can continue from {_mmss(self.resume_pos)}.")
        else:
            self.progress(1.0, f"Done - {self.made} short(s) ready.")
        self.log(f"Finished. {self.made} short(s) in: {self.out_dir}")
        return self.made

    def scan_range(self, a, b, carry=None, flush=True):
        cap = piece_cap(self.min_len, self.max_len)
        buf, t = list(carry or []), a
        while t < b - 0.5 and not self.stopped:
            c_end = min(b, t + self.chunk)
            info = D.find_speech(self.movie, t, c_end, self.opts, self.work, self.log)
            regs = info["regions"]
            nxt = c_end
            if c_end < b - 0.5 and regs:
                ls, le = regs[-1]
                if le >= c_end - 0.35 and ls > t + 1.0:     # speech runs past the chunk edge: scan it again next time
                    regs, nxt = regs[:-1], ls
            regs = D.split_long(regs, info["contour"], cap)
            buf.extend(regs)
            speech = sum(e - s for s, e in regs)
            self.log(f"[{_mmss(t)} - {_mmss(c_end)}] {info['detector']}: {len(regs)} dialogue pieces, "
                     f"{speech:.0f}s of talking")
            t = nxt
            self.progress((self.span_done + (t - a)) / self.span_total,
                          f"Scanned up to {_mmss(t)} - {self.made} short(s) ready")
            self.mark(min(buf[0][0], t) if buf else t)
            while not self.stopped:
                g = pick_group(buf, self.min_len, self.max_len)
                if not g:
                    break
                group, buf = g
                group = hold_end(group, buf, b)
                if not self.render(group):                      # stopped in the middle: the group is still to do
                    buf = group + buf
                self.mark(min(buf[0][0], t) if buf else t)
        if not flush and not self.stopped:
            if buf:
                self.log(f"{total_len(buf):.0f}s of dialogue carried on into the next range (not enough for a short yet).")
            return buf
        # end of this stretch of movie: whatever is left
        while buf and not self.stopped:
            g = pick_group(buf, self.min_len, self.max_len, final=True)
            if g:
                group, buf = g
                group = hold_end(group, buf, b)
                if not self.render(group):
                    buf = group + buf
                    self.mark(buf[0][0])
                    break
                continue
            left = total_len(buf)
            if self.keep_last and left >= 3.0:
                self.log(f"Last short is only {left:.0f}s (shorter than {self.min_len:.0f}s) - kept as you asked.")
                if not self.render(buf):
                    self.mark(buf[0][0])
            else:
                self.log(f"{left:.0f}s of dialogue left at the end of this range, shorter than "
                         f"{self.min_len:.0f}s - no short made from it.")
            break

    @property
    def resume_pos(self):
        return getattr(self, "_resume_pos", self.ranges[0][0])

    def mark(self, pos, finished=False):
        """Remembers where to continue. Written to _resume.json after every chunk and every short, so even closing
        the software in the middle of a run loses nothing."""
        self._resume_pos = float(pos)
        info = dict(movie=self.movie, ranges=self.all_ranges, range_index=self.index_base + self.ri,
                    pos=round(float(pos), 3), next_number=self.number, finished=bool(finished),
                    out_dir=self.out_dir, made=self.made_list)
        try:
            tmp = os.path.join(self.out_dir, "_resume.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.out_dir, "_resume.json"))
        except OSError:
            pass
        if self.on_resume:
            self.on_resume(info)

    def boost_texts(self, n, total):
        """'PART n' label and optional opening text for the first seconds of a short."""
        bo = self.runner.s.get("_boost") or {}
        out, end = [], min(3.0, total)
        if bo.get("hook"):
            out.append(dict(E.TEXT_DEFAULT, text=str(bo["hook"]).replace("{n}", str(n)), start=0.0, end=end, size=7.0,
                            pos="Custom", hcenter=True, y=18, outline=3, box=True, box_opacity=45, bold=True))
        if bo.get("part_label"):
            out.append(dict(E.TEXT_DEFAULT, text=f"PART {n}", start=0.0, end=end, size=4.5, pos="Top-Center",
                            hcenter=True, outline=2, shadow=True))
        return out

    def render(self, group):
        """Exports one short. Returns False when it was stopped in the middle (nothing is kept of it)."""
        pieces = limit_pieces(D.join_adjacent(group))
        total = sum(d for _, d in pieces)
        n = self.number
        self.number += 1
        mm, ss = divmod(int(pieces[0][0]), 60)
        name = f"{self.base}_short{n:02d}_{mm:02d}m{ss:02d}s.mp4"
        final = os.path.join(self.out_dir, name)
        ovs, txs = relative_items(self.items, total, n)
        txs = txs + self.boost_texts(n, total)
        S = dict(self.runner.s, overlays=ovs, texts=txs)
        self.log(f"Short {n}: {total:.1f}s of dialogue from {_mmss(pieces[0][0])} - {len(pieces)} piece(s), "
                 f"{len(pieces) - 1} cut(s), shortest piece {min(d for _, d in pieces):.1f}s, "
                 f"average {total / len(pieces):.1f}s - exporting ...")
        ok = bool(self.runner.cut(self.movie, pieces[0][0], total, final, self.info, self.crop, S, pieces=pieces))
        if self.stopped:
            self.number = n                              # this number is used again when you continue
            for junk in (final, final + ".tmp.mp4"):
                try:
                    os.remove(junk)
                except OSError:
                    pass
            return False
        if ok and os.path.isfile(final):
            self.made += 1
            d = dict(path=final, name=name, number=n, length=total, start=pieces[0][0])
            self.made_list.append(d)
            self.log(f"Short {n} ready: {name}")
            self.on_short(d)
        else:
            self.log(f"Short {n} failed (see the error above).")
        return True


def _mmss(t):
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
