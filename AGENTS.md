# Working in this repo

A voice-and-vision assistant on AR glasses, built to measure how the network changes the experience. README.md says what the system is and how to run it; docs/TASK.md says what the experiment is and why; docs/TODO.md is the open list. Read those before changing anything.

## What this is

- A lab system, not a product. A missing setting means refuse to start; no defaults that hide a mistake, no fallbacks that keep a broken run going.
- Two architectures under `backend/agent/src/`, `gpt/` and `gemini/`, picked by `AGENT_BACKEND`. Each is described in its own terms; shared code lives at `src/` top level.

## How to work

- Start from the simplest thing that can work. Add a mechanism only after a run shows it is needed.
- Nothing runs against a model API or the glasses without being asked. When a run goes wrong, read its log and record first (`backend/runs/`, `deploy/report.py`) and find the cause before adding anything.
- Anything that needs the glasses is done by a person; give the exact command, do not fake the device.
- Changes wait in the working tree until they have been looked at. Commit only when told, on the current branch.
- `archive/` is not read.

## Writing

README, comments, docstrings, commit messages: every line is a sentence with a verb that says what the thing does or is for. No noun fragments, no describing the surface instead of the job, no referents the reader does not have, no vague headers, no comparing one architecture to the other, no padding. Read it back as someone who has never seen the code. In Markdown files a paragraph is one line, no hard wraps.
