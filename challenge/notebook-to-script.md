# From the notebook to the script

You explore in a marimo notebook. An organizer executes a `.py` script against
the event key. This document is the crossing between the two, and it is the part
of the weekend that decides whether your team gets a hardware run at all.

The rules live in the Challenge Instructions at <https://qupacabrathon.dev> and
are cited here by section title. Nothing below changes any of them.

Every command is written out. Substitute your own team identifier for
`quantum_coyotes_07` wherever it appears.

## What crosses

Two things cross from the notebook into the script.

- The body of `build_circuits`, which is the one function your team writes.
- The parameter block: `TEAM`, `RUN`, `N`, `SHOTS`, `TWIRLS`, `DEVICE`.

Everything else in `challenge/submission-template.py` is fixed. It owns the
sweep, the measurement, the arithmetic and the writing of results, so that twelve
submissions have one surface a checker can validate and a mentor can read in ten
seconds. Nothing else from your notebook travels: no plots, no `mo.ui` elements,
no printing, no scratch cells.

## Before you start

Fork <https://github.com/qupacabras-lab/qupacabrathon_2026> with the Fork button,
then clone your fork and make your branch. The branch name is your team
identifier, which is your chosen name joined by an underscore to the number the
organizers assigned you. That same identifier names your submitted file, your row
in the spend ledger and your folder in the results database, so pick it once and
spell it the same way every time.

```
git clone https://github.com/<your-github-username>/qupacabrathon_2026.git
cd qupacabrathon_2026
git switch -c quantum_coyotes_07
```

Everything below happens inside that clone.

## Where the key lives

The event key lives in an untracked `.env` file on the organizer machine and is
read at runtime. Students hold no key and no balance, so nothing you run needs
one. The local simulator asks for no credential.

A submitted script reads its key from the environment and contains none.
qBraid Runtime reads `QBRAID_API_KEY` out of the environment itself, so no
credential is ever an argument in the file. The template's `check_environment` only asks
whether one of them is present. It never reads a value, because a value read into
the script would be one traceback away from the output.

A key never appears in a notebook cell, a submitted script, a results file, a
slide, or a commit message. `.gitignore` lists `.env`, but a key pasted into a
tracked file stays in the history after you delete it. Stage 1 of the gate
rejects a variable whose name looks like a credential and is assigned a string
literal, and rejects any string shaped like a key, wherever it sits in the file.

If you find yourself wanting to type a key somewhere, the thing you are trying to
do is run hardware yourself. No team does that. See the Challenge Instructions,
Submit it.

## 1. Work in a copy of the notebook

`challenge/simulator.py` is the starter notebook. It builds the circuit, sweeps
the 2n questions against a local simulator, and certifies the result locally.
Copy it to the top of the repository and work in the copy:

```
cp challenge/simulator.py explore.py
uvx marimo edit --sandbox explore.py
```

`--sandbox` builds an isolated environment from the notebook's own PEP 723
header, so nothing is installed into your machine's Python. The notebook finds
`scripts/game_numbers.py` by walking up from wherever it sits, so a copy
anywhere inside your clone still imports what it needs.

Simulator time is free and unlimited, and designing the experiment there before
spending anything is the point of the exercise. See the Challenge Instructions,
Design it in simulation.

`challenge/` is organizer-authored and nothing in it changes, `simulator.py`
included, so a clean starter is always one `cp` away. Your copy lives at the top
of the repository, next to `challenge/` rather than inside it. Keep it out of
`submissions/` as well, because the automatic check runs the submission gate on
every `.py` file it finds there and a notebook would fail it. The one file an
organizer reads is the one in `submissions/`.

## 2. Check the notebook outside marimo

A marimo notebook is a plain `.py` file, so it runs with no marimo session at
all. Run it that way, then run the flattened export, and compare both against
what the notebook showed you:

```
uv run --python 3.12 --script explore.py
uvx marimo export script explore.py -o explore_flat.py
uv run --python 3.12 --script explore_flat.py
```

`marimo export script` writes the cell bodies out in dependency order with the
app scaffolding removed. All three should print the same numbers. Delete
`explore_flat.py` afterwards. It is a check, not a deliverable.

### When the export runs differently

A difference here is almost always a cell whose result depended on the order you
ran it in by hand. Work through these in order.

- Restart the notebook and run it from the top. If a fresh notebook run now
  agrees with the export, what differed was session state you had built up by
  hand, and it is already fixed.
- Look for a cell that changes an object in place instead of assigning a new one.
  A cell holding `seen.append(1)` that you ran four times leaves four entries in
  the session. A fresh run executes it once and leaves one. marimo re-runs
  dependent cells for you, but it cannot see a mutation reach inside an object
  another cell owns.
- Look for `mo.ui` values. Run as a script, `mo.ui.slider(3, 21, value=5)` is at
  its initial value of 5, not at whatever you dragged it to.
- Look for a random draw with no fixed seed. Shot noise moves the last digits of
  a win rate on its own, so compare at the precision the numbers deserve rather
  than digit for digit.

In every case the repair is the same. Make the circuit construction a function of
`n` and the angle alone, taking nothing from a cell you happened to run. That
function is the only thing that crosses.

## 3. Copy the template

```
cp challenge/submission-template.py submissions/quantum_coyotes_07_run1.py
```

Copy it, never edit it in place. The template is what your run 2 starts from and
it is the file a mentor compares your submission against.

## 4. Move the circuit into `build_circuits`

`build_circuits(n, theta)` returns a list of exactly 2n functions, one per
question, in the order `question_order(n)` gives. Entry `k` of the list is the
circuit for question `k` of that list.

Each entry takes no arguments, applies gates to wire 0 and wire 1, and returns
nothing. It attaches no measurement: `main` adds `qml.sample(wires=[0, 1])` and
owns the shot count, which is what guarantees every circuit the same honest
trials. It prints nothing and draws nothing.

Open your copy, find `build_circuits`, and replace the
`raise NotImplementedError(...)` the template ships with your circuit
construction. Leave the `def` line and the docstring above it as they are. This
is the shape, with a placeholder circuit in it:

```python
def build_circuits(n: int, theta: float) -> list[Callable[[], None]]:
    def gates_for(x: int, y: int) -> Callable[[], None]:
        def circuit() -> None:
            qml.Hadamard(wires=0)
            qml.CNOT(wires=[0, 1])

        return circuit

    return [gates_for(x, y) for x, y in question_order(n)]
```

The placeholder answers every question identically and ignores `theta`, so it
wins the vertex questions, loses every edge, and lands at a win rate of exactly
0.5. It is here to show the shape and nothing else. What each question does, and
where the angle enters, is the work.

**Both questions are in scope, and only one of them is yours per wire.** The
function receives `x` and `y` together because it builds all 2n circuits at
once, but the circuit it builds has to keep the game's shape: the gates up to
and including the last two-qubit gate are identical in every circuit, and after
them wire 0's gates may depend only on `x` and wire 1's only on `y`. Stage 2 of
the gate rebuilds your circuits and checks exactly that, because players who can
read each other's questions beat every bound in the Challenge Instructions
without any physics. See the Challenge Instructions, What you may change about
the run.

`qml`, `Callable` and `question_order` are already imported or defined in the
template, so a circuit built out of PennyLane gates needs no new import at all.

**Bring across only what the template does not already have.** An import your
notebook used and the template does not declare fails at stage 2 of the gate, in
a scratch copy, costing nothing:

```
FAILED at stage 2, structure
  the circuits could not be rebuilt for inspection: importing the script and calling build_circuits(N, strategy_angle(N)) failed. The usual cause is an import your notebook had and this script does not, since this is the first thing that runs your code.
  Traceback (most recent call last):
    ...
    File ".../submissions/quantum_coyotes_07_run1.py", line 141, in build_circuits
      import marimo as mo
  ModuleNotFoundError: No module named 'marimo'
```

**The order is the one thing nothing checks.** `counts.json` gets its keys from
`question_order(n)` inside the template, so a list built in a different order
scores each answer against the wrong question, reports a loss, and raises
nothing. Catch it in the notebook instead, with the equal-rate check under Design
it in simulation in the Challenge Instructions. A strategy at the optimum wins
all 2n questions at the same rate, so a list built in the wrong order shows up as
per-question win rates that are not all equal.

## 5. Set the parameter block

The template already carries these lines near the top, above `build_circuits`.
Edit them in place rather than adding a second block anywhere else. Each one
stays a literal you wrote down:

```python
TEAM = "quantum_coyotes_07"
RUN = 1
N = 13
SHOTS = 53
TWIRLS = 1
QPU = "emerald"
DELTA = 0.015
DEVICE = "default.qubit"
```

An organizer reads what a run costs off these lines, and stage 1 of the gate
reads them the same way, without executing anything. A value computed from
something else is rejected for that reason. Reassigning any of them later in the
file stops the run, because the parameters approved on the pull request have to
be the parameters that spend the money.

Leave `DEVICE` as it ships. The organizer swaps that single string at execution
time, which is why a script that runs by accident spends nothing. `QPU` is a
different line and it is yours: it names which of the two QPUs this run goes to,
by label. Never write a route string; the gate rejects one.

`DELTA` is the device deficit you are sizing against, and the event publishes no
value for it. Predict it from the published device facts in the Background Notes,
or measure it with a run of your own. It is the assumption the rest of the block
is built on, so decide it before `N` and `SHOTS`.

`N` and `SHOTS` do not come from the notebook. Size them with `plan_check.py`,
which prices the sweep and says whether it clears the certification gate at the
deficit you declared:

```
uv run --python 3.12 scripts/plan_check.py --n 13 --shots 53 --delta 0.015
```

`TWIRLS` stays at 1 unless you are deliberately buying Pauli-twirled variants;
its comment in the template states the mechanism and the price, `SHOTS` has to
divide by it, and `plan_check.py --twirls` prices the k extra task fees.

See the Challenge Instructions, Size it. Stage 4 of the gate runs this same tool
on the values in your file, so the run that executes is the run that passed the
arithmetic.

## 6. What the script writes

Executing the script creates `results/quantum_coyotes_07_run1/` holding
`counts.json` and `benchmark.json`, in exactly the shape the results database
reads. That folder is untracked, and the results an organizer files are the ones
their hardware run produced.

The gate in step 8 executes the script for you, in a scratch copy you never see.
To look at the two files yourself, run it directly:

```
uv run --python 3.12 --script submissions/quantum_coyotes_07_run1.py
```

`counts.json` carries one entry per question and four answer counts in each,
every one of them summing to exactly `SHOTS`. From a placeholder run at n = 13
and 35 shots:

```json
{
  "0|0": {
    "0:0": 13,
    "0:1": 0,
    "1:0": 0,
    "1:1": 22
  },
  "1|1": {
    "0:0": 18,
    "0:1": 0,
    "1:0": 0,
    "1:1": 17
  }
}
```

The verifier checks `sum(counts[c]) == shots` for every circuit `c`, because a
single scalar total hides unequal allocation and postselection. Declaring 2000
shots per circuit while running 50 turns a real 0.6 sigma into a claimed 4.8
sigma, because the gate counts the trials it is told about. See the Challenge
Instructions, What counts as a result.

The template owns the writing of both files. Leave that code alone, and the shape
is correct for free.

Running the script by hand twice refuses rather than overwriting:

```
RuntimeError: results/quantum_coyotes_07_run1/ already exists. Move it aside rather than losing what the device returned the first time.
```

Move the folder aside or delete it before you run again. The gate never hits
this, because it runs your script in a scratch copy of the repository and cleans
up after itself.

## 7. The portability bar

An organizer runs your script on a machine that is not yours, from a fresh
checkout of your branch, with none of your files on it.

- **Parameters at the top**, in the template's block, as literals.
- **No absolute paths.** Any path built from `Path(__file__)` is fine. A path
  that names your home directory is not, and stage 1 catches it:

  ```
  FAILED at stage 1, source
    line 143: '/Users/student/Desktop/angles.csv' is an absolute path. An organizer runs this on a machine that is not yours, so build every path from `Path(__file__)` or leave it to the template.
  ```

- **No local state.** No file the script expects to already exist, and nothing
  read from a folder your notebook wrote. A number your strategy needs goes into
  the file as a number.
- **Dependencies in the PEP 723 header**, every one pinned with `==`. The header
  the template ships is the one that was tested. Adding an import means adding it
  there, pinned, and running the gate again.
- **No network module of your own**, and no post-execution mitigation library.
  Stage 1 rejects both by name. See the Challenge Instructions, What you may
  change about the run.

## 8. Run the gate

One command decides whether the script is submittable:

```
uv run --python 3.12 scripts/submission_check.py submissions/quantum_coyotes_07_run1.py
```

It takes well under a minute at n = 13 and longer as n grows. It reaches no
quantum device and costs nothing, so run it as often as you like. A pass looks
like this:

```
Checking quantum_coyotes_07_run1.py

Stage 1, source
  TEAM quantum_coyotes_07, RUN 1, N 13, SHOTS 35, TWIRLS 1, DEVICE 'default.qubit'
  portable, no credential, no absolute path, dependencies pinned

Stage 2, simulated run
  circuit shape: shared preparation, then per-player local gates
  running quantum_coyotes_07_run1.py on default.qubit, this takes a minute
  the sweep completed

Stage 3, output
  win rate  0.500000 +/- 0.070264, recomputed from the counts
  p-value   1.000e+00 (exact binomial tail) against omega_c = 0.961538

Stage 4, plan
  Run plan: C_13, 35 shots per circuit, 26 circuits
  ...
  PLAN PASSES

PASSED. quantum_coyotes_07_run1.py is ready to submit.
Next: commit it, open the pull request, and wait for a mentor to approve.
```

That win rate of 0.500000 is the placeholder from step 4, which certifies
nothing. The gate checks that a script is safe, portable and self-consistent. It
does not check that a strategy is any good, and it is not the thing that tells
you whether yours works. The notebook is.

Every failure names what to change and where. The most common one on a first
attempt is forgetting step 4 entirely:

```
FAILED at stage 1, source
  line 141: build_circuits is still the stub the template ships, so this submission has no circuits to run. Return 2n gate functions in the order question_order(n) gives, and see the Background Notes at https://qupacabrathon.dev for the derivation.

Nothing was submitted and nothing was spent. Fix the above and run this again.
```

## 9. Open the pull request

Commit the submission script and your notebook copy, and push the branch to your
fork:

```
git add submissions/quantum_coyotes_07_run1.py explore.py
git commit -m "Run 1: C_13 at 35 shots per circuit"
git push -u origin quantum_coyotes_07
```

Then open the pull request against `qupacabras-lab/qupacabrathon_2026`, base
branch `main`. GitHub shows a "Compare & pull request" button on your fork right
after the push. If it is not there, go to your fork on GitHub, choose your branch
from the branch menu, and click "Contribute", then "Open pull request".

GitHub Actions runs the same gate on the pull request, so a red check is a
complete answer and nobody has to be free for you to make progress. A mentor
reviews and approves, and that approval is the sign-off record. An organizer then
checks your branch out, executes it against the event key, posts your counts on
the pull request, and closes it unmerged. Your results come back as
`counts.json` and `benchmark.json`. See the Challenge Instructions, Submit it and
Read what came back.

For run 2, stay on the same branch. Copy the template again to
`submissions/quantum_coyotes_07_run2.py`, set `RUN = 2`, run the gate on the new
file, push, and open a second pull request.
