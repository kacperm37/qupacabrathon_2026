# Qupacabrathon 2026

You and one teammate-per-qubit are going to play a game that no classical
strategy can win, run it on a real quantum computer, and prove statistically that
you won. Two qubits, five instructions, one number to beat. The circuit is
derived to its last step in the notes, so building it is the floor every team
reaches. The contest is the experiment around it: measure the device, size your
runs against what it says, and choose which bet to place.

This repository holds the code and the submission path. The rules and the
background are two PDFs at <https://qupacabrathon.dev>.

## What to read, in order

1. **Challenge Instructions** — the rules. What the game is, how a win is
   certified, what you may spend, how you submit, and how you are scored. About
   20 minutes.
2. **Background Notes** — the mathematics, from complex numbers to the odd-cycle
   game. Written for a student with linear algebra and no quantum coursework.
   About 90 minutes cold, about 40 if you have had the course.
3. `challenge/submission-template.py` — the script you copy, fill in and submit.
   One function is yours. The rest is fixed.
4. `challenge/notebook-to-script.md` — the crossing from the notebook you
   explored in to the file an organizer executes.
5. `challenge/hardware.py` — what happens on the device side once your pull
   request is approved: the one line that changes, what a circuit costs, and
   what comes back. Nothing in it touches a QPU.

## Running the numbers

Every quantity in both documents is computed by one script, so you can regenerate
any of them rather than trusting a table:

```
uv run --python 3.12 scripts/game_numbers.py
```

Before you commit to a run, price it and check it clears the certification gate:

```
uv run --python 3.12 scripts/plan_check.py --n 5 --shots 34 --delta 0.015
```

That is a standard calibration run: $3.54, sized so it certifies with 90%
probability at the deficit named in `--delta`, and it measures the one device
number that sizes every later run.

`--delta` is required and has no default, because the event publishes no device
deficit. It is your team's own assumption, reached by predicting it from the
published device facts in the Background Notes or by measuring it with a run.
The 0.015 above is an illustration and not a claim about either QPU.

Every shot costs money on this meter, so a plan is sized for the power it needs
rather than rounded up to a boundary; buying the bare minimum instead fails
about half the time. `--balance` takes what you have left of your $20.00 cap
after run 1.

## Writing your strategy

Explore in the starter notebook, `challenge/simulator.py`, against the simulator,
which is free and unlimited:

```
uvx marimo edit --sandbox challenge/simulator.py
```

When you are ready to submit, copy the template into `submissions/`, named for
your team and the run, and find `build_circuits`:

```
cp challenge/submission-template.py submissions/<your-team>_run1.py
```

`build_circuits` is the only function you write, and it ships as a stub that
raises until you fill it in. It returns one circuit per question, in the order
the file documents. The circuit is derived to the last step in the Background
Notes, so filling it in is the floor; the decisions that separate teams live in
the parameter block above it, which sets the cycle size, the shots, and whether
to pay for Pauli-twirled variants (`TWIRLS`). Change nothing else: the
parameter block and the fixed `main` below your function are what let an
organizer read a submission in ten seconds and know what it costs. Copy rather
than edit `challenge/` in place, because the template is what your second run
starts from.

`challenge/notebook-to-script.md` walks the whole crossing.

## Submitting

You never run against hardware yourself, and you never hold an API key. Fork this
repository, branch, commit your file in `submissions/`, and open a pull request. A
mentor approves it, an organizer checks your branch out and executes it against
the event key, posts your counts on the pull request, and closes it. Nothing gets
merged. The instructions have the whole path under "Submit it", including both
deadlines.

Before you open that pull request:

```
uv run --python 3.12 scripts/submission_check.py submissions/<your-team>_run1.py
```

It runs your script against a local simulator, validates what it wrote, and checks
your parameters. It is the one command that gates a submission, and the same check
runs automatically on your pull request.

## The two things that will cost you

The money is shared. Twelve teams spend from one pot, so an arithmetic mistake in
your run plan costs every other team rather than only you. That is why
`plan_check.py` exists and why the gate runs on the parameters in your submitted
script rather than on a plan you typed somewhere else.

Your circuit is the same at every cycle size, and only one angle changes. So a
better-executed experiment shows up as a larger certified cycle, not as a third
decimal place. Design the experiment in simulation, then spend.
