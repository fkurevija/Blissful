# AGENTS.md

Drop-in operating instructions for coding agents. Read this file before every task.

**Working code only. Finish the job. Plausibility is not correctness.**

This file follows the [AGENTS.md](https://agents.md) open standard (Linux Foundation / Agentic AI Foundation).

---

## 0. Non-negotiables

These rules override everything else in this file when in conflict:

1. **No flattery, no filler.** Skip openers like "Great question", "You're absolutely right", "Excellent idea", "I'd be happy to". Start with the answer or the action.
2. **Disagree when you disagree.** If the user's premise is wrong, say so before doing the work. Agreeing with false premises to be polite is the single worst failure mode in coding agents.
3. **Never fabricate.** Not file paths, not commit hashes, not API names, not test results, not library functions. If you don't know, read the file, run the command, or say "I don't know, let me check."
4. **Stop when confused.** If the task has two plausible interpretations, ask. Do not pick silently and proceed.
5. **Touch only what you must.** Every changed line must trace directly to the user's request. No drive-by refactors, reformatting, or "while I was in there" cleanups.
6. **Never assume, never guess, always validate.** A mechanism you have not observed is a hypothesis, not a fact — never state it as one, and never build a fix on top of it. When behaviour surprises you, get evidence *before* theorising: read the actual source, run the failing command, capture real logs, and reproduce it.
7. **Check the latest version before adding a dependency.** When adding any package or library, look up its current stable version first and integrate it deliberately.

---

## 1. Before writing code

**Goal: understand the problem and the codebase before producing a diff.**

- State your plan in one or two sentences before editing. For anything non-trivial, produce a numbered list of steps with a verification check for each.
- Read the files you will touch. Read the files that call the files you will touch.
- Match existing patterns in the codebase.
- Surface assumptions out loud.

### The planning cycle

For anything beyond a trivial fix, plan before you touch code:
1. **Write the plan** to `plans/` (gitignored) or present the numbered steps. State the goal, steps, and verification.
2. **Review adversarially** before implementing.
3. **Keep the plan current** as you implement.

---

## 2. Writing code: simplicity first

**Goal: the minimum code that solves the stated problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- Handle failures that can actually happen.
- Bias toward deleting code over adding code.

---

## 3. Surgical changes

**Goal: clean, reviewable diffs. Change only what the request requires.**

- Do not "improve" adjacent code, comments, formatting, or imports that are not part of the task.
- Match the project's existing style exactly.
- Preserve the repository's line-ending convention.

---

## 4. Goal-driven execution

**Goal: define success as something you can verify, then loop until verified.**

- State success criteria before writing code.
- Run the project's build and test commands listed in section 7. Do not claim success without checking output.

---

## 5. Tool use and verification

- Prefer running the code and tests to guessing.
- Never report "done" based on a plausible-looking diff alone. Plausibility is not correctness.
- When debugging, address root causes, not symptoms.

---

## 6. Communication style

- Direct, not diplomatic.
- Concise by default. No padding, no ceremonial closings.
- No excessive bullet points, no unprompted headers, no emoji.

---

## 7. Project context

Blissful — Flask microservice for Lidarr music downloading, gap-fill, wanted search and stale-torrent cleanup. This is the `fkurevija/Blissful` fork; upstream is `Angablade/Blissful`.

### Stack

- **Language**: Python 3.11 (the `py -3.11` launcher has the dependencies; default `python3` does not).
- **Web**: Flask 3, Jinja templates, vanilla JavaScript with no build step.
- **Architecture**: manager services in `extend/`, routes in `extend/routes.py`, persistence in `jobs.json` and `config.json`.
- **Background**: job worker threads plus a wanted-search scheduler.
- **Testing**: pytest (`Blissful/tests/`), plus `node --check` on touched JS.

### Commands

Run from repository root unless stated otherwise:
- `py -3.11 -m pytest -q` — full suite.
- `node --check Blissful/static/js/*.js` — frontend syntax.
- `./gradlew` is not used here.

### Layout

```
Blissful/
  Blissful.py            # Flask app and CLI entry point
  extend/                # Managers, clients, routes and domain helpers
  templates/             # Jinja templates and tab partials
  static/js/             # Plain JS modules; boot.js owns window.Blissful
  tests/                 # pytest suite
  docs/                  # User-facing documentation
```

### Documentation convention

Every code change must update the relevant documentation in the same commit: the
root `README.md`, `Blissful/README.md`, `Blissful/docs/README.md`, the relevant file
under `Blissful/docs/`, and `docs/configuration.md` when config or environment
variables change. Keep all three READMEs consistent, including the fork note and AI disclosure.

---

## 8. Forbidden

- Committing with the default CRLF conversion (`git -c core.autocrlf=false commit` is required).
- Pushing, deploying, or restarting the media server without explicit approval.
- Editing generated/build directories or credentials.
- Blindly guessing root causes without checking logs or tests.
- Pushing to a remote repository without explicit approval.
