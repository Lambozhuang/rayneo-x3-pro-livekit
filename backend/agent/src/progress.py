"""The state machine: judge verdicts in, step changes and corrections out.

The code holds the current step; the judge only ever answers "is step N done,
wrong, not yet placed, or can't you see" about that step. This class turns the
stream of answers into events (pure Python, no I/O; eval/replay_eval.py runs it
over the recorded run, gpt/watch.py in the live session):

  correct   `confirm` times in a row           -> DONE: step N is in place, N += 1
                                                  (FINISHED when it was the last)
  wrong     `wrong_confirm` of the last WINDOW -> WRONG: once, with the judge's sentence;
                                                  said again only after REARM not_placed
                                                  in a row (the brick was taken off)
  not_placed / cannot_see                     -> nothing is said

Wrong is counted over a window, not in a row: with a wrong brick on the plate
the VLM flips between "wrong" (a yellow strip, not lime) and "not_placed" (no
lime brick there). In a lab run (2026-10-07) every lone not_placed reset a
count of three in a row, so a correction took ~9 s and was said four times. A
wrong verdict, on the other hand, nearly always had a wrong brick behind it
(74 of 76), so two of the last three is enough.

Steps never go back on their own: a hand, a lifted brick or a bad angle must
not undo a step. `confirm` is an experiment knob (GPT_WATCH_CONFIRM); the
replays in eval/RESULTS.md compare 1 and 2. `wrong_confirm` is
GPT_WATCH_WRONG_CONFIRM.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

WINDOW = 3  # verdicts a wrong count looks back over
REARM = 3   # not_placed in a row after which a correction may be said again


class Kind(Enum):
    DONE = "done"          # step `step` confirmed in place; `step` is the one just completed (1-based)
    FINISHED = "finished"  # the last step confirmed
    WRONG = "wrong"        # step `step` is placed wrongly; `text` says how


@dataclass(frozen=True)
class Event:
    kind: Kind
    step: int
    text: str = ""


class Tracker:
    def __init__(self, total: int, confirm: int = 2, step: int = 1, wrong_confirm: int | None = None) -> None:
        self.total = total
        self.confirm = max(1, confirm)
        self.wrong_confirm = min(WINDOW, max(1, wrong_confirm or self.confirm))
        self.step = step  # 1-based current step; total + 1 once finished
        self._ok = 0
        self._recent: deque[str] = deque(maxlen=WINDOW)
        self._empty = 0  # not_placed in a row
        self._said_wrong = False

    @property
    def finished(self) -> bool:
        return self.step > self.total

    def set_step(self, step: int) -> None:
        """Jump (restart, or the wearer insisting); counters reset."""
        self.step = max(1, min(step, self.total + 1))
        self._reset()

    def _reset(self) -> None:
        self._ok = self._empty = 0
        self._recent.clear()
        self._said_wrong = False

    def feed(self, answer: str, reason: str = "") -> Event | None:
        """One verdict about the current step. Returns an event when something changed."""
        if self.finished:
            return None
        self._recent.append(answer)
        self._empty = self._empty + 1 if answer == "not_placed" else 0
        if self._empty >= REARM:
            self._said_wrong = False
        if answer == "correct":
            self._ok += 1
            if self._ok >= self.confirm:
                done = self.step
                self.step += 1
                self._reset()
                return Event(Kind.FINISHED if self.finished else Kind.DONE, done)
            return None
        self._ok = 0
        if (answer == "wrong" and not self._said_wrong
                and sum(a == "wrong" for a in self._recent) >= self.wrong_confirm):
            self._said_wrong = True
            return Event(Kind.WRONG, self.step, reason)
        return None
