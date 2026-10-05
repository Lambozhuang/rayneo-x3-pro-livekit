"""The state machine: judge verdicts in, step changes and corrections out.

The code holds the current step; the judge only ever answers "is step N done,
wrong, not yet placed, or can't you see" about that step. This class turns the
stream of answers into events (pure Python, no I/O; eval/replay_eval.py runs it
over the recorded run, gpt/watch.py in the live session):

  correct   `confirm` times in a row -> DONE: step N is in place, N += 1
                                        (FINISHED when it was the last)
  wrong     `confirm` times in a row -> WRONG: once per spell of wrong answers,
                                        with the judge's sentence; said again
                                        only after the brick has been seen gone
  not_placed / cannot_see           -> the counters reset, nothing is said
                                        (not_placed also ends a wrong spell)

Steps never go back on their own: a hand, a lifted brick or a bad angle must
not undo a step. `confirm` is an experiment knob (GPT_WATCH_CONFIRM); the
replays in eval/RESULTS.md compare 1 and 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    def __init__(self, total: int, confirm: int = 2, step: int = 1) -> None:
        self.total = total
        self.confirm = max(1, confirm)
        self.step = step  # 1-based current step; total + 1 once finished
        self._ok = 0
        self._bad = 0
        self._said_wrong = False

    @property
    def finished(self) -> bool:
        return self.step > self.total

    def set_step(self, step: int) -> None:
        """Jump (restart, or the wearer insisting); counters reset."""
        self.step = max(1, min(step, self.total + 1))
        self._ok = self._bad = 0
        self._said_wrong = False

    def feed(self, answer: str, reason: str = "") -> Event | None:
        """One verdict about the current step. Returns an event when something changed."""
        if self.finished:
            return None
        if answer == "correct":
            self._ok, self._bad = self._ok + 1, 0
            if self._ok >= self.confirm:
                done = self.step
                self.step += 1
                self._ok = self._bad = 0
                self._said_wrong = False
                return Event(Kind.FINISHED if self.finished else Kind.DONE, done)
            return None
        if answer == "wrong":
            self._bad, self._ok = self._bad + 1, 0
            if self._bad >= self.confirm and not self._said_wrong:
                self._said_wrong = True
                return Event(Kind.WRONG, self.step, reason)
            return None
        self._ok = self._bad = 0
        if answer == "not_placed":
            self._said_wrong = False
        return None
