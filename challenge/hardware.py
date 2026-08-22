# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo==0.23.16",
#     "pennylane==0.45.1",
#     "numpy==2.5.2",
# ]
# ///

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")

with app.setup:
    import importlib.util
    import json
    import sys
    from pathlib import Path

    import marimo as mo

    # Same root walk as `simulator.py`, for the same reason: this notebook works
    # from a copy anywhere inside your clone.
    REPO = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "scripts" / "game_numbers.py").is_file()
    )
    sys.path.insert(0, str(REPO / "scripts"))

    from game_numbers import (
        CAP_PER_TEAM,
        DEVICE_ID,
        SHOT_DOLLARS,
        TASK_DOLLARS,
        certification_power,
        chsh_ceiling_power,
        cost,
        n_circuits,
        omega_q,
        shots_affordable,
        shots_for_significance,
    )

    _spec = importlib.util.spec_from_file_location(
        "submission_template", REPO / "challenge" / "submission-template.py"
    )
    assert _spec is not None and _spec.loader is not None
    template = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(template)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # The hardware side

    Nothing in this notebook talks to a QPU. You hold no key, and every cell
    below runs locally on numbers that are already known. What it shows is what
    happens after your pull request is approved: the one line that changes, what
    the vendor charges for, how a sweep travels, and what comes back.

    Read it before you size your run. The reason it exists at all is that a QPU
    is a special-purpose instrument. You design the experiment in simulation,
    where a mistake costs nothing, and the device is the last thing you point it
    at.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## One line differs

    Your submitted script is `challenge/submission-template.py` with your
    `build_circuits` in it. The parameter block near the top carries a device
    string, and it ships pointing at the simulator:

    ```python
    DEVICE = "default.qubit"
    ```

    You never change it. An organizer swaps that single string to `"qbraid"` at
    execution time, after a mentor approved the pull request. That is the whole
    difference between a practice run and a hardware run: the circuits, the
    sweep, the tally and the files written are identical, which is why a
    strategy validated in simulation is the strategy that runs.

    Even swapped, the string is inert on your laptop. The qBraid route needs
    two things from its environment, and you have neither:

    - `QBRAID_DEVICE`, the QPU to route to. Without it the template raises
      before any circuit is built.
    - A credential, `QBRAID_API_KEY`. Without one the template raises before
      the first shot.

    So a student who runs their own submission spends nothing, twice over. The
    organizer's machine has both, and that machine is the only one that does.
    Note what is absent: no QPU name appears in your file. Which device the
    event runs on is an organizer decision, and it can change between the
    announced device and its fallback without touching a single submission.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The key is never an argument

    `hardware_route` in the template is the whole of it:

    ```python
    route = os.environ.get("QBRAID_DEVICE")
    ```

    No credential passes through that function, or through the runtime call, or
    through any file you write. qBraid Runtime reads `QBRAID_API_KEY` out of the
    environment itself. That is a rule with teeth: a key in a submitted script
    is a key in a public pull request, and the gate rejects a script that
    carries a literal one, the same way it rejects a script that names a
    hardware route itself.

    There is no confirmation prompt anywhere in that path. The submit call is
    the call that spends, which is exactly why your sweep is priced by
    `plan_check.py` and approved on the pull request before an organizer runs
    it unattended.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What a circuit costs

    The meter is continuous dollars, a task fee per circuit plus a per-shot
    rate:
    """)
    return


@app.cell
def _():
    price = f"${TASK_DOLLARS:.2f} task + ${SHOT_DOLLARS:.5f} per shot, per circuit"
    sweep_at_13 = f"the S_90 sweep of C_13 is cost(13, 35) = ${cost(13, 35):.2f}"
    price, sweep_at_13
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Two consequences, and the second is the one that decides how you spend.

    A sweep is one task per circuit variant. The template submits one job per
    circuit, so $2n$ circuits are $2n$ task fees and nothing collapses into a
    batch. The per-task fee is real and you pay it $2n$ times. The `TWIRLS`
    parameter multiplies exactly this term: $k$ Pauli-twirled variants per
    question are $k$ tasks at the same total shots, so `cost(n, shots, k)`
    prices it, and whether the twirl buys anything on this device is
    unmeasured. That is the shape of a priced bet, and it is yours to take or
    leave.

    And every shot is a line item. There is no whole-credit boundary and no
    free shots below one, so nothing is "already bought": precision costs
    exactly what it costs. That is why every published plan is sized for
    certification probability, S_90, the smallest shot count that certifies
    with 90% probability at the assumed device deficit. Buying the bare minimum
    that could certify puts the expected outcome exactly at the gate, and an
    outcome lands below its own expectation half the time.
    """)
    return


@app.cell
def _():
    # The same sweep at three shot counts: (shots, dollars, certification
    # probability). The price moves with every shot, and what it buys is the
    # probability the run certifies at all.
    comparison = [
        (shots, round(cost(13, shots), 2), round(certification_power(13, shots), 3))
        for shots in (18, 35, 70)
    ]
    comparison
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How a sweep travels

    Four steps per circuit, in this order.

    1. Export. The circuit leaves PennyLane as an OpenQASM 2 string, exactly
       the gates the simulator ran.
    2. Submit. This is the call that spends. qBraid has no quote step: the
       rates the plans are priced on were measured by the organizers on
       2026-08-18, and `organizers/quote_check.py` re-confirms them before any
       run.
    3. Poll until the job returns.
    4. Read the counts.

    The circuits go up in a randomised order, so a device drifting over the
    sweep cannot bias one end of the question list; the counts are keyed by
    question, so nothing downstream notices. Each job is polled to completion
    before the next is submitted, so a $2n$ sweep is $2n$ sequential queue
    waits rather than $2n$ concurrent ones, and the wall clock is the sum.

    You never call any of this. `run_sweep` in the template does, and the only
    thing it reads is the organizer's `QBRAID_DEVICE`.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What comes back

    Two files, in `results/<team>_run<N>/`. Both are written by the template and
    neither needs anything from you.

    `counts.json` is the raw record: for each of the $2n$ questions, how many
    times each two-bit answer came back.
    """)
    return


@app.cell
def _():
    # The shape, built locally from a made-up single question. A real file
    # carries one entry per question, and every entry sums to SHOTS.
    example_counts = template.counts_document(
        {"0|0": {"0:0": 18, "0:1": 1, "1:0": 0, "1:1": 16}}
    )
    print(json.dumps(example_counts, indent=2))
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    The verifier checks that every question's counts sum to the shot count you
    declared. A scalar shot count would hide unequal allocation: declaring 35
    shots while running 5 on the questions your strategy finds hard turns a
    real result into a claimed one. Per-question counts make that impossible to
    state, so nobody has to be trusted about it.

    `benchmark.json` is the claim: win rate, uncertainty, $p$-value, device, and
    the game parameters. The results database recomputes the win rate from
    `counts.json` and compares, so the two files check each other.

    Both are printed with their SHA-256 as the run finishes. An organizer's log
    therefore carries an independent record of what the device returned, and a
    file edited afterwards no longer matches it.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What your team's cap buys

    Your team has $20.00 across both runs, and the arithmetic is entirely
    front-loaded: it is decided before anything runs, by the $n$ you choose and
    the shots you buy. Three archetypes fit inside the cap, and they are
    genuinely different weekends:
    """)
    return


@app.cell
def _():
    def _sweep_dollars(n):
        shots = shots_for_significance(n)
        return round(cost(n, shots), 2)

    ladder = ("certify 9 then 11", round(_sweep_dollars(9) + _sweep_dollars(11), 2))
    one_shot = ("one-shot commit at 13", _sweep_dollars(13))
    _chase_shots = shots_affordable(5, CAP_PER_TEAM)
    chase = (
        "nonlocal-content chase at 5",
        round(cost(5, _chase_shots), 2),
        f"P(beat CHSH ceiling) = {chsh_ceiling_power(5, _chase_shots):.2f}",
    )
    next_step = ("n = 15 sized for 90% power", _sweep_dollars(15))
    CAP_PER_TEAM, ladder, one_shot, chase, next_step
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Those are steps, not a curve, because the quantum advantage shrinks like
    $1/(2n)$ and the shots a certification needs grow like its inverse square:
    the cell above prices the same 90%-power sweep two rungs apart, and one
    rung is usually the difference between inside the cap and outside it. The
    step is where a plan lives or dies, and `scripts/plan_check.py` prints
    which side of it you are on.

    Where the rungs fall depends entirely on the device deficit you declared,
    which the event does not publish. Section "Size it" of the Challenge
    Instructions has the grid, and it says why a cheap measurement of the
    deficit at low $n$ transfers to every later run.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Before the pull request

    The path from here is in Section "Submit it" of the Challenge Instructions.
    In short: `scripts/submission_check.py` has to pass on your script, a mentor
    approves the pull request, and an organizer checks the branch out and runs
    it against the event key.

    The file that executes is the file on the branch. Nobody edits your script
    to run it, and nothing is merged, so what you submitted is what happened.
    """)
    return


if __name__ == "__main__":
    app.run()
