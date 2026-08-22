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
    import math
    import sys
    from pathlib import Path

    import marimo as mo
    import numpy
    import pennylane as qml

    # The repository root, found by walking up from this file until `scripts/`
    # comes into view. Copy this notebook anywhere inside your clone and it
    # still finds what it needs, which is what makes working in a copy the
    # normal thing to do rather than a special case.
    REPO = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "scripts" / "game_numbers.py").is_file()
    )
    sys.path.insert(0, str(REPO / "scripts"))

    from game_numbers import (
        CAP_PER_TEAM,
        DEFAULT_QPU,
        DELTA_EXAMPLE,
        P_3SIGMA,
        POWER_TARGET,
        QPU_ROUTES,
        certification_power,
        chsh_ceiling_power,
        cost,
        critical_visibility,
        delta_from_readout,
        delta_from_readout_asym,
        largest_delta_certified,
        largest_n_affordable,
        largest_n_feasible,
        n_circuits,
        omega_c,
        omega_q,
        p_value,
        quantum_advantage,
        rates_for_qpu,
        readout_asym_block_gap,
        readout_asym_rates,
        readout_drop,
        readout_from_delta,
        shots_affordable,
        shots_for_significance,
    )

    # The submission template, loaded by path because its file name carries a
    # hyphen. Every rule of the game used below comes from it: the question
    # order, the win condition, the tally of one circuit's shots, and the sweep
    # itself. The sweep run here is the sweep an organizer runs against the
    # event key, with the device string pointed at a local simulator.
    _spec = importlib.util.spec_from_file_location(
        "submission_template", REPO / "challenge" / "submission-template.py"
    )
    assert _spec is not None and _spec.loader is not None
    template = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(template)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # The odd-cycle game, in simulation

    This notebook is where your team designs the experiment. A local simulator
    costs nothing and there is no limit on how much of it you run, so everything
    gets settled here before an organizer spends money on hardware. Section
    "Design it in simulation" of the Challenge Instructions is the rule this
    notebook serves.

    It hands you five things.

    1. The circuit: one Bell pair, one rotation per player.
    2. The 2n questions of a sweep, in the order the submission template fixes.
    3. Two worked strategies that both lose, and the test that says why.
    4. A sizing panel, where a choice of n turns into shots and dollars.
    5. The error dials: which device faults reward a countermeasure, which
       provably do not, and how to read the difference off your own counts.

    The experiment is yours. The Background Notes derive the circuit to the
    last step, so reproducing the optimum is the floor rather than the
    contest. What separates teams is what happens around it: measuring the
    device, reading run 1's profile, sizing run 2 against what it said, and
    deciding which levers are worth their price.

    Every bound, shot count and price here comes from
    `scripts/game_numbers.py`, imported rather than restated, so nothing in this
    file can drift from the rules. Both documents are at
    https://qupacabrathon.dev.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The circuit

    Five instructions, and they are the same five at every cycle size.

    1. A Hadamard on wire 0.
    2. A CNOT from wire 0 onto wire 1. The two wires now hold a Bell pair.
    3. An `RY` on wire 0, by an angle Alice picks from the label she was sent.
    4. An `RY` on wire 1, by an angle Bob picks from the label he was sent.
    5. Measure both wires.

    Wire 0 is the first player and wire 1 is the second, at every question. The
    Background Notes build the Bell pair under "Two qubits and entanglement" and
    work the strategy out under "Nonlocal games".

    One fact carries the whole design. After the two rotations the two measured
    bits agree with probability `cos^2((theta_A - theta_B) / 2)`, so only the
    difference of the two angles enters. A strategy is a choice of two functions
    from a vertex label to an angle, one function per player, and nothing else.
    """)
    return


@app.function
def game_circuit(angle_a, angle_b):
    """The gates for one question: a Bell pair, then one rotation per player.

    Returns a function of no arguments that applies gates to wires 0 and 1,
    which is the shape `build_circuits` in the submission template returns. The
    measurement is attached by the template, so every circuit in a sweep is
    measured the same way and gets the same honest trials.
    """

    def circuit():
        qml.Hadamard(wires=0)
        qml.CNOT(wires=[0, 1])
        qml.RY(angle_a, wires=0)
        qml.RY(angle_b, wires=1)

    return circuit


@app.function
def sweep_from_angles(n, theta_a, theta_b):
    """The 2n circuits of one sweep, in the order the template fixes.

    `theta_a` and `theta_b` each take a vertex label and return an angle. That
    pair of functions is the whole strategy.
    """
    return [
        game_circuit(theta_a(x), theta_b(y))
        for x, y in template.question_order(n)
    ]


@app.cell
def _():
    # One question as the device sees it, with two placeholder angles in the
    # rotations. The measurement comes from the template.
    print("One question, drawn")
    print(
        qml.draw(
            template.measured_circuit(
                qml.device("default.qubit", wires=2),
                game_circuit(0.4, 1.1),
                8,
            )
        )()
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The 2n questions

    One sweep asks every question once. The first n are the vertex questions,
    where both players get the same label and win by agreeing. The last n are
    the edge questions, where the two labels are neighbours on the ring and the
    players win by disagreeing. Each edge is asked once, in one direction, and
    that orientation is part of the game.

    `question_order` in `challenge/submission-template.py` fixes the order, and
    entry k of the list your `build_circuits` returns answers question k of it.
    Nothing checks the pairing, so a list in another order scores your answers
    against the wrong questions and reports a loss.
    """)
    return


@app.cell
def _():
    # Search at a small cycle. The circuit is identical at every n, so a
    # strategy that reaches omega_q(5) in simulation is the same strategy that
    # reaches omega_q(37), and a small sweep runs in a blink. Change this and
    # every cell below follows.
    DEMO_N = 5

    # What the sizing rule buys at this n and the illustration deficit. Your own
    # runs are sized at the deficit you declare in DELTA, not at this one.
    DEMO_SHOTS = shots_for_significance(DEMO_N, DELTA_EXAMPLE)

    print(f"Exploring on C_{DEMO_N}")
    print(f"  circuits          {n_circuits(DEMO_N)}")
    print(f"  shots per circuit {DEMO_SHOTS}")
    print(f"  on hardware       ${cost(DEMO_N, DEMO_SHOTS):.2f}, and here it is free")
    return DEMO_N, DEMO_SHOTS


@app.cell
def _(DEMO_N):
    print(f"One sweep of C_{DEMO_N}, in order")
    for _k, (_x, _y) in enumerate(template.question_order(DEMO_N)):
        _kind = "same vertex" if _x == _y else "edge"
        _won = "agree" if template.is_win(_x, _y, 0, 0) else "differ"
        print(
            f"  [{_k:>2}] {template.question_key(_x, _y):<6} "
            f"{_kind:<12} won when the two answers {_won}"
        )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Reading a candidate

    Four functions below read a strategy, and each answers a different
    question.

    `exact_rates` returns the exact win probability of every question, with no
    shots involved. The simulator computes the four outcome probabilities
    instead of sampling them, which is the strategy itself with no counting
    noise in the way. Search with this one.

    `simulate` runs a real sweep at a shot count and returns the 2n measured win
    rates. It calls `run_sweep` from the submission template, so the loop that
    runs here is the loop that runs on hardware.

    `certification_report` prints what the gate reads off a sweep: the pooled
    win count and the trial count, which are the only two inputs of the
    one-sided exact binomial tail test, `p_value` in `scripts/game_numbers.py`.
    Section "What counts as a result" of the Challenge Instructions states the
    threshold p has to clear.

    `equal_rate_check` prints the lowest and the highest of the 2n rates. At the
    optimum all 2n are equal to omega_q(n), vertex questions and edge questions
    alike, which the Background Notes derive under "Nonlocal games". A candidate
    whose rates are not all equal is not the optimum, so this is the test to run
    while you search.
    """)
    return


@app.function
def exact_rates(n, theta_a, theta_b):
    """The exact win probability of each of the 2n questions, with no shots.

    The four outcome probabilities of one circuit come back directly from the
    simulator, and the win condition picks out the ones that count.
    """
    device = qml.device("default.qubit", wires=2)
    rates = []
    for (x, y), gates in zip(
        template.question_order(n),
        sweep_from_angles(n, theta_a, theta_b),
        strict=True,
    ):

        @qml.qnode(device)
        def outcome_probabilities():
            gates()
            return qml.probs(wires=[0, 1])

        probabilities = outcome_probabilities()
        rates.append(
            sum(
                float(probabilities[2 * a + b])
                for a in (0, 1)
                for b in (0, 1)
                if template.is_win(x, y, a, b)
            )
        )
    return rates


@app.function
def simulate(n, theta_a, theta_b, shots):
    """Run one sweep on the local simulator and return the 2n win rates."""
    questions = template.question_order(n)
    counts = template.run_sweep(
        questions,
        sweep_from_angles(n, theta_a, theta_b),
        "default.qubit",
        shots,
        route=None,
    )
    return [
        template.question_win_rate(x, y, counts[template.question_key(x, y)], shots)
        for x, y in questions
    ]


@app.function
def certification_report(n, rates, shots):
    """Print what the certification gate reads off one sweep."""
    measured = sum(rates) / len(rates)
    margin = measured - omega_c(n)
    # The gate pools the counts: this many wins out of this many trials, and
    # the p-value is the exact binomial tail at the classical bound.
    wins = round(shots * sum(rates))
    print(
        f"  trials            {len(rates) * shots} "
        f"({len(rates)} circuits at {shots} shots)"
    )
    print(f"  pooled wins       {wins}")
    print(f"  measured omega    {measured:.6f}")
    print(f"  classical bound   {omega_c(n):.6f}")
    print(f"  margin            {margin:+.6f}")
    p = p_value(rates, shots, omega_c(n))
    verdict = "certified" if p <= P_3SIGMA else "not certified"
    print(f"  p-value           {p:.3e} against the gate {P_3SIGMA:.3e}")
    print(f"  {verdict} at 3 sigma")


@app.function
def equal_rate_check(n, rates):
    """Print how far apart the 2n question rates are. The optimum is flat."""
    print(f"  mean over 2n      {sum(rates) / len(rates):.6f}")
    print(f"  lowest question   {min(rates):.6f}")
    print(f"  highest question  {max(rates):.6f}")
    print(f"  gap               {max(rates) - min(rates):.6f}, and 0.000000 at the optimum")
    print(f"  every question at the optimum wins at omega_q({n}) = {omega_q(n):.6f}")


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Example 1, and it loses

    Both players rotate by nothing, whatever label they were sent. The two
    angles are then equal at every question, their difference is zero, and the
    two bits agree on every shot. Every vertex question is won, every edge
    question is lost, and the win rate is one half.

    Run it for the pipeline. This is the sweep an organizer executes, pointed at
    the local simulator, and it produces the same per-circuit counts a hardware
    run produces.
    """)
    return


@app.function
def always_zero(v):
    """Rotate by nothing, whatever the label. A starting point, not an answer."""
    return 0.0


@app.cell
def _(DEMO_N, DEMO_SHOTS):
    print("Example 1, both players rotate by nothing")
    print("Exact win probabilities")
    equal_rate_check(DEMO_N, exact_rates(DEMO_N, always_zero, always_zero))
    print("Sweep")
    _rates = simulate(DEMO_N, always_zero, always_zero, DEMO_SHOTS)
    print("Result")
    certification_report(DEMO_N, _rates, DEMO_SHOTS)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Example 2, the classical colouring

    Colour the ring alternately, and have both players rotate by pi on the odd
    vertices. The two angles agree at every vertex question, so all n of those
    are won. Neighbours differ by pi at every edge except the one that closes an
    odd ring, so n - 1 of the n edge questions are won and the last one is lost.

    That is the best a colouring can do, and it is the deterministic strategy in
    the classical-value theorem of the Background Notes, written as rotations.
    The win rate lands on omega_c(n) exactly, the margin is zero, and no shot
    count certifies anything. The Bell pair is in the circuit and buys nothing
    here, because two equal angles use none of it.

    Both examples are decided rather than random: every question comes out at
    probability 0 or 1, so the measured rates match the exact ones shot for
    shot. A strategy with rates strictly between 0 and 1 wanders around its
    exact values instead, which is why the search runs on `exact_rates`.
    """)
    return


@app.function
def parity_colouring(v):
    """The classical 2-colouring as an angle: pi on odd vertices, nothing on even."""
    return math.pi * (v % 2)


@app.cell
def _(DEMO_N, DEMO_SHOTS):
    print("Example 2, both players colour the ring by parity")
    print("Exact win probabilities")
    equal_rate_check(DEMO_N, exact_rates(DEMO_N, parity_colouring, parity_colouring))
    print("Sweep")
    _rates = simulate(DEMO_N, parity_colouring, parity_colouring, DEMO_SHOTS)
    print("Result")
    certification_report(DEMO_N, _rates, DEMO_SHOTS)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Where your work starts

    Both examples give the two players the same angle at every question, and
    both sit at or below the classical bound. The Background Notes show under
    "Nonlocal games" how the two win conditions pull the differences in opposite
    directions, and they stop where the choice of the two angle functions
    begins. That choice is your team's.

    The tool for the search is already above. Write two angle functions, call
    `exact_rates`, and read `equal_rate_check`. While any two of the 2n rates
    differ, the candidate has room left in it.

    When a candidate holds up, carry it into
    `challenge/submission-template.py`. Copy that file to
    `submissions/<your-team>_run1.py` and fill in `build_circuits`, which
    returns what `sweep_from_angles` returns here: 2n gate functions, in the
    order `question_order(n)` gives. The template hands your function the angle
    `strategy_angle(n)`, and what your strategy does with it is your decision.
    `challenge/` stays as the organizers wrote it, this notebook included, so
    explore here and submit from `submissions/`.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Size it

    The circuit does not change with n. What changes is how many circuits a
    sweep holds, how many shots each one needs to clear the gate, and what that
    costs.

    Move the two sliders. The cycle size n is the axis you compete on. The
    device deficit is how far below omega_q the hardware lands, and there is no
    published value for it: it is the number your team declares in `DELTA` in
    its own parameter block, and reaching a defensible one is the design work.

    The slider opens on 0.015, which is the illustration Section "Size it" of
    the Challenge Instructions prices its worked examples at, so the panel below
    reproduces that section's table row for row. It is not a measurement of
    either device. The slider reaches 0.06, which covers both devices' published
    specifications pushed through the readout law in the Background Notes, so
    whatever your own homework produces you can dial it here first.
    """)
    return


@app.cell
def _():
    n_slider = mo.ui.slider(
        start=3, stop=49, step=2, value=13, label="cycle size n", show_value=True
    )
    delta_slider = mo.ui.slider(
        start=0.002,
        stop=0.060,
        step=0.001,
        value=DELTA_EXAMPLE,
        label="device deficit",
        show_value=True,
    )
    qpu_picker = mo.ui.dropdown(
        options=sorted(QPU_ROUTES),
        value=DEFAULT_QPU,
        label="QPU (price only)",
    )
    mo.vstack([n_slider, delta_slider, qpu_picker])
    return delta_slider, n_slider, qpu_picker


@app.cell
def _(delta_slider, n_slider, qpu_picker):
    _n = n_slider.value
    _delta = delta_slider.value
    _qpu = qpu_picker.value
    _task, _shot = rates_for_qpu(_qpu)
    print(f"C_{_n} against a device deficit of {_delta:.4f}, priced on {_qpu}")
    print(f"  rates                 ${_task:.2f}/task + ${_shot:.5f}/shot")
    print(f"  circuits in a sweep   {n_circuits(_n)}")
    print(f"  classical bound       omega_c = {omega_c(_n):.6f}")
    print(f"  quantum bound         omega_q = {omega_q(_n):.6f}")
    print(f"  margin                {quantum_advantage(_n):.6f}")
    print(f"  visibility needed     {critical_visibility(_n):.4f}")
    print(f"  device win rate       omega   = {omega_q(_n) - _delta:.6f}")
    _shots = shots_for_significance(_n, _delta)
    if _shots is None:
        print("  the deficit is wider than the margin, so this device loses at")
        print(f"  C_{_n} and no shot count repairs it")
    else:
        print(f"  shots per circuit     {_shots} (S_90: certifies with")
        print(
            f"                        probability "
            f"{certification_power(_n, _shots, _delta):.3f} at this deficit)"
        )
        print(f"  total shots           {n_circuits(_n) * _shots}")
        print(
            f"  cost                  ${cost(_n, _shots, qpu=_qpu):.2f} "
            f"of the ${CAP_PER_TEAM:.2f} cap"
        )
        _other = next(q for q in sorted(QPU_ROUTES) if q != _qpu)
        _gap = cost(_n, _shots, qpu=_other) - cost(_n, _shots, qpu=_qpu)
        _share = _shot * _shots / (_task + _shot * _shots)
        print(
            f"  the same sweep on {_other} costs "
            f"${cost(_n, _shots, qpu=_other):.2f}, {_gap:+.2f}"
        )
        print(
            f"  shot term is {100 * _share:.0f}% of this bill, which is all the "
            f"device choice can move"
        )
        print(
            f"  keeps {POWER_TARGET:.0%} power up to a deficit of "
            f"{largest_delta_certified(_n, _shots):.6f}"
        )
    return


@app.cell
def _(delta_slider, n_slider):
    # The gate at that plan, run through the same bound a real sweep goes
    # through. Every circuit is taken to win at omega_q - delta, which is the
    # equal-rate optimum the shot count is inverted from.
    _n = n_slider.value
    _delta = delta_slider.value
    _shots = shots_for_significance(_n, _delta)
    if _shots is None:
        print(f"C_{_n} certifies at no shot count against a deficit of {_delta:.4f}")
    else:
        _rates = [omega_q(_n) - _delta] * n_circuits(_n)
        print(f"The gate at C_{_n}, every circuit winning at {omega_q(_n) - _delta:.6f}")
        print("  shots     p at the expected outcome     P(certify)")
        for _s in (_shots, _shots // 2, _shots // 4):
            _p = p_value(_rates, _s, omega_c(_n))
            _power = certification_power(_n, _s, _delta)
            print(f"  {_s:>6}    {_p:>10.3e}                    {_power:.3f}")
        print("  the expected outcome clearing the gate is not the same thing as")
        print("  the run clearing it: the outcome lands below its own expectation")
        print("  half the time, which is why plans are sized for power")
    return


@app.cell
def _(delta_slider):
    _delta = delta_slider.value
    print(
        f"Cost of certifying at 3 sigma with {POWER_TARGET:.0%} power, "
        f"against a deficit of {_delta:.4f}"
    )
    print(f"{'n':>4} {'circuits':>9} {'S_90':>8} {'dollars':>9}  within cap")
    for _n in (3, 5, 7, 9, 11, 13, 15, 17):
        _shots = shots_for_significance(_n, _delta)
        if _shots is None:
            print(f"{_n:>4} {n_circuits(_n):>9} {'infeasible':>8}")
        else:
            _price = cost(_n, _shots)
            _fits = "yes" if _price <= CAP_PER_TEAM else "no"
            print(
                f"{_n:>4} {n_circuits(_n):>9} {_shots:>8} "
                f"{'$' + format(_price, '.2f'):>9}  {_fits}"
            )
    print(f"  ceiling on physics         n = {largest_n_feasible(_delta)}")
    _best = largest_n_affordable(CAP_PER_TEAM, _delta)
    if _best is None:
        print(f"  the ${CAP_PER_TEAM:.2f} cap buys no certified n at this deficit")
    else:
        print(
            f"  largest n the cap buys     n = {_best[0]} at {_best[1]} shots "
            f"per circuit, ${_best[2]:.2f}"
        )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Put noise in it

    Everything above this point ran on `default.qubit`, which is a perfect
    device. On a perfect device the measured win rate sits at omega_q(n), the
    deficit is zero, and every shot count in the panel above is buying certainty
    about something that was never in doubt. That is a bad place to design an
    experiment, because the whole reason a sweep needs shots is that the device
    it runs on is not perfect.

    So put a device deficit in and watch what it costs. `default.mixed` is the
    same simulator carrying a density matrix instead of a state vector, which is
    what lets a channel act on it. The channel used here is the simplest one that
    reproduces a deficit: each measured bit is flipped with probability p, on
    both wires, just before the measurement.

    One line of algebra says what that does. Both win conditions read the parity
    of the two answer bits, since a vertex question wants them equal and an edge
    question wants them different. Flipping one bit flips the parity and turns a
    win into a loss. Flipping both leaves the parity alone. So a fraction
    2p(1 - p) of the shots have their verdict reversed, and

        delta = 2 p (1 - p) (2 omega_q(n) - 1)

    which is `delta_from_readout(n, p)` in `scripts/game_numbers.py`. The
    Background Notes derive it under "Readout error, and the deficit you can
    dial", and that derivation is the whole of the prediction route: the notes
    also carry each device's published readout error, and pushing one through
    this formula is how you reach a deficit to declare in `DELTA` without
    spending a shot. Run it the other way here, dial a p and watch the deficit
    come out, and the arithmetic stops being something to take on faith.
    """)
    return


@app.function
def with_readout_error(gates, p):
    """Wrap one circuit so both measured bits flip with probability `p`.

    The gates are the team's, unchanged, and the flips go on immediately before
    the template attaches the measurement. Nothing here is a mitigation or a
    correction: it is the device being worse, which is the point.
    """

    def circuit():
        gates()
        qml.BitFlip(p, wires=0)
        qml.BitFlip(p, wires=1)

    return circuit


@app.function
def exact_noisy_rates(n, theta_a, theta_b, p):
    """Exact win probability of each question under a bit flip of `p` per wire.

    The same calculation `exact_rates` does, on `default.mixed` and with the
    channel in the circuit. No shots, so what comes back is the strategy and the
    noise with no counting noise on top.
    """
    device = qml.device("default.mixed", wires=2)
    rates = []
    for (x, y), gates in zip(
        template.question_order(n),
        sweep_from_angles(n, theta_a, theta_b),
        strict=True,
    ):

        @qml.qnode(device)
        def outcome_probabilities():
            with_readout_error(gates, p)()
            return qml.probs(wires=[0, 1])

        probabilities = outcome_probabilities()
        rates.append(
            sum(
                float(probabilities[2 * a + b])
                for a in (0, 1)
                for b in (0, 1)
                if template.is_win(x, y, a, b)
            )
        )
    return rates


@app.function
def simulate_noisy(n, theta_a, theta_b, p, shots):
    """Run one sweep on the noisy simulator and return the 2n measured win rates.

    Calls `run_sweep` from the submission template, exactly as `simulate` does,
    with the device string pointed at `default.mixed` and the channel wrapped
    around each circuit. So this is the loop that runs on hardware, against a
    device that gets some of its bits wrong.
    """
    questions = template.question_order(n)
    counts = template.run_sweep(
        questions,
        [with_readout_error(g, p) for g in sweep_from_angles(n, theta_a, theta_b)],
        "default.mixed",
        shots,
        route=None,
    )
    return [
        template.question_win_rate(x, y, counts[template.question_key(x, y)], shots)
        for x, y in questions
    ]


@app.cell
def _():
    p_slider = mo.ui.slider(
        start=0.0,
        stop=0.05,
        step=0.0005,
        value=0.005,
        label="readout flip probability p, per wire",
        show_value=True,
    )
    p_slider
    return (p_slider,)


@app.cell
def _(p_slider):
    # What that dial does to the deficit, before any shot is drawn. The closed
    # form and the exact simulator agree here to 1e-14, so the two columns
    # differing would mean the channel is not the one the formula describes.
    _p = p_slider.value
    print(f"A flip probability of {_p:.4f} per wire")
    print(f"{'n':>4} {'omega_q':>10} {'delta':>10} {'omega':>10} {'margin left':>12}")
    for _n in (3, 7, 13, 29, 43):
        _delta = delta_from_readout(_n, _p)
        _left = quantum_advantage(_n) - _delta
        _verdict = f"{_left:>12.6f}" if _left > 0 else f"{'lost':>12}"
        print(
            f"{_n:>4} {omega_q(_n):>10.6f} {_delta:>10.6f} "
            f"{omega_q(_n) - _delta:>10.6f} {_verdict}"
        )
    print(f"  the illustration deficit       {DELTA_EXAMPLE} (not either device)")
    _dial = readout_from_delta(13, DELTA_EXAMPLE)
    print(f"  the p that reproduces it       {_dial:.5f} per wire at n = 13")
    print("  push each device's published readout error the other way to")
    print("  predict its deficit; the Background Notes carry both figures")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Watch it happen to a strategy you already have

    The cell below takes `parity_colouring` from Example 2, which wins at exactly
    omega_c(n) with no noise, and runs it noiseless and noisy side by side. Both
    are exact probabilities rather than sampled ones, so what separates the two
    columns is the channel and nothing else.

    The predicted drop uses `readout_drop(omega_ideal, p)`, which is the same
    formula with the noiseless win rate left as an argument instead of fixed at
    omega_q(n). That is what makes it usable on a candidate that is not yet
    optimal, which is every candidate while you are still searching.
    """)
    return


@app.cell
def _(DEMO_N, p_slider):
    _p = p_slider.value
    _clean = exact_rates(DEMO_N, parity_colouring, parity_colouring)
    _noisy = exact_noisy_rates(DEMO_N, parity_colouring, parity_colouring, _p)
    _w0 = sum(_clean) / len(_clean)
    _w = sum(_noisy) / len(_noisy)
    print(f"parity_colouring on C_{DEMO_N} at a flip probability of {_p:.4f}")
    print(f"  noiseless win rate  {_w0:.6f}, which is omega_c({DEMO_N})")
    print(f"  noisy win rate      {_w:.6f}")
    print(f"  drop, measured      {_w0 - _w:.6f}")
    print(f"  drop, predicted     {readout_drop(_w0, _p):.6f}")
    print(f"  they agree to       {abs((_w0 - _w) - readout_drop(_w0, _p)):.1e}")
    print()
    print("  the same channel on a strategy that had reached the optimum instead:")
    print(f"    noiseless         {omega_q(DEMO_N):.6f}, which is omega_q({DEMO_N})")
    print(f"    drop              {delta_from_readout(DEMO_N, _p):.6f}, the device deficit")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Read the deficit back off your own counts

    This is the motion you will perform on run 1. An organizer hands back
    `counts.json`, you turn it into the 2n win rates, and the deficit is
    omega_q(n) less their mean. Nothing else in the analysis needs the number the
    device was assumed to have.

    Two numbers come out of the cell below and they answer different questions.

    The measured deficit is what the device did, read off counts alone. The
    largest deficit the plan certifies, `largest_delta_certified(n, shots)` from
    `scripts/game_numbers.py`, is what the sweep you bought can survive. A run
    certifies when the first is below the second, and the gap between them is the
    margin you paid for. That is the whole of experiment design here: buy enough
    margin to cover the deficit you will meet, and no more.

    The sweep below runs `parity_colouring`, so its measured deficit is mostly
    the strategy's own shortfall rather than the device's, and it certifies at no
    p at all. The last two lines are the ones to read: they price the same sweep
    for a team whose strategy has reached the optimum, and that comparison flips
    from certifying to not certifying as you move the slider.
    """)
    return


@app.cell
def _(DEMO_N, DEMO_SHOTS, p_slider):
    _p = p_slider.value
    print(f"Sweep of C_{DEMO_N} at {DEMO_SHOTS} shots, flip probability {_p:.4f}")
    _rates = simulate_noisy(DEMO_N, parity_colouring, parity_colouring, _p, DEMO_SHOTS)
    print()
    print("Result")
    certification_report(DEMO_N, _rates, DEMO_SHOTS)
    _measured = omega_q(DEMO_N) - sum(_rates) / len(_rates)
    _survives = largest_delta_certified(DEMO_N, DEMO_SHOTS)
    print(f"  measured delta    {_measured:.6f}, read off these counts alone")
    print(f"  plan survives     {_survives:.6f} at {DEMO_SHOTS} shots per circuit")
    print()
    print(f"  the same sweep bought by a team whose strategy reached omega_q({DEMO_N}):")
    _optimal = delta_from_readout(DEMO_N, _p)
    print(f"    deficit it meets  {_optimal:.6f}")
    print(
        f"    verdict           {'certifies' if _optimal < _survives else 'does not certify'}, "
        f"since the deficit is {'under' if _optimal < _survives else 'over'} what the plan survives"
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Two things to take from this

    The deficit you measure is omega_q(n) less the win rate your run produced, so
    every bit of distance between your strategy and the optimum lands inside it
    and is then carried into every later sizing decision. That is exactly what
    the sweep above shows: `parity_colouring` reports a deficit near 0.07 at
    n = 5 with the noise dial at zero, and none of it is the device. Settle the
    strategy against `equal_rate_check` on the noiseless simulator first, then
    measure the device. A team that calibrates with a suboptimal strategy
    measures its own mistake and then declares that mistake as its `DELTA`,
    sizing most of a $20.00 cap against a number about its own code.

    And the shot count is the thing that buys margin. Move p up past the deficit
    the plan was sized for and the same sweep at the same price stops certifying.
    That is what a shot count is for, and it is invisible on a perfect simulator.
    The meter is continuous, a task fee plus a per-shot rate, so margin is never
    free: every shot above the sized plan is a purchase, and the S_90 sizing
    already carries the margin the published tables decided to buy.

    The bit-flip channel is not the only noise a device has, and it is not
    claimed to be either QPU's. It is the one channel whose effect on this game is a
    single line of algebra, which makes it the one to design against. When you
    want to see what else does, `qml.DepolarizingChannel` on the CNOT,
    `qml.AmplitudeDamping` for energy loss and `qml.ThermalRelaxationError` for
    T1 and T2 all drop into `with_readout_error` the same way. What none of them
    changes is the shape of the problem: some deficit exists, it has to be
    measured, and the sweep has to be sized against it.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Error you can counter, and error you cannot

    Real readout is worse than the symmetric flip above in one specific way:
    reading a 1 as a 0 is usually more likely than reading a 0 as a 1. Call
    the two probabilities e0 and e1, per wire. An obvious idea follows: if the
    device mangles the two bits asymmetrically, maybe the angles should be
    chosen against the noise rather than for the noiseless optimum.

    That idea is a dead end, and provably so. For any strategy in this
    circuit family, each question's noisy win rate is an affine increasing
    function of its noiseless one, with a slope shared by every question, so
    whatever maximises the noiseless mean maximises the noisy mean too. The
    Background Notes prove it under "Noise and the strategy", and the cells
    below let you watch it fail to help. Design your angles for the noiseless
    optimum, whatever the readout does.

    What the asymmetry does leave is a fingerprint on the per-question
    profile, and learning to read that profile is the skill this section
    teaches, because a different error family, coherent angle
    miscalibration, leaves a bigger fingerprint and can be countered. The
    cells run on a made-up candidate with varied angles, standing in for the
    strategy your team will actually have. Swap yours in.
    """)
    return


@app.function
def with_asym_readout_error(gates, e0, e1):
    """Wrap one circuit so each wire reads 0 as 1 with `e0` and 1 as 0 with `e1`.

    The asymmetric version of `with_readout_error`. The channel is written as
    explicit Kraus operators because PennyLane's `BitFlip` is symmetric;
    applied immediately before the measurement it acts exactly as the
    classical confusion matrix [[1 - e0, e1], [e0, 1 - e1]] on each wire.
    """
    flip_up = numpy.array([[0.0, 0.0], [math.sqrt(e0), 0.0]])
    flip_down = numpy.array([[0.0, math.sqrt(e1)], [0.0, 0.0]])
    keep = numpy.array([[math.sqrt(1.0 - e0), 0.0], [0.0, math.sqrt(1.0 - e1)]])

    def circuit():
        gates()
        qml.QubitChannel([keep, flip_down, flip_up], wires=0)
        qml.QubitChannel([keep, flip_down, flip_up], wires=1)

    return circuit


@app.function
def exact_asym_rates(n, theta_a, theta_b, e0, e1):
    """Exact win probability of each question under asymmetric readout flips."""
    device = qml.device("default.mixed", wires=2)
    rates = []
    for (x, y), gates in zip(
        template.question_order(n),
        sweep_from_angles(n, theta_a, theta_b),
        strict=True,
    ):

        @qml.qnode(device)
        def outcome_probabilities():
            with_asym_readout_error(gates, e0, e1)()
            return qml.probs(wires=[0, 1])

        probabilities = outcome_probabilities()
        rates.append(
            sum(
                float(probabilities[2 * a + b])
                for a in (0, 1)
                for b in (0, 1)
                if template.is_win(x, y, a, b)
            )
        )
    return rates


@app.function
def demo_ramp_a(v):
    """A stand-in candidate for Alice: varied angles, nowhere near the optimum."""
    return 0.7 * v


@app.function
def demo_ramp_b(v):
    """Bob's half of the stand-in candidate."""
    return 0.7 * v - 0.3


@app.function
def offset_player(theta, bias):
    """One player's angle function shifted by a constant.

    As a noise model this is a per-player additive miscalibration: the device
    rotates by `bias` more than that player asked, at every question. As a
    countermeasure it is the same function with the opposite sign, which is
    why this error family is one your run 2 can act on.
    """

    def shifted(v):
        return theta(v) + bias

    return shifted


@app.function
def miscalibrated(theta, epsilon):
    """One player's angle function scaled by 1 + epsilon.

    A multiplicative drive miscalibration: every rotation runs `epsilon`
    fractionally long. The counter is the inverse scale, requested angles
    divided by 1 + epsilon.
    """

    def scaled(v):
        return (1.0 + epsilon) * theta(v)

    return scaled


@app.cell
def _(DEMO_N):
    # The dead end, watched directly. Sweep a constant offset on Bob and read
    # where the noiseless and the noisy means peak: the same place. Then check
    # every question against the affine law the Background Notes prove.
    _e0, _e1 = 0.001, 0.02
    print(f"Asymmetric readout, e0 = {_e0} (read 0 as 1), e1 = {_e1} (read 1 as 0)")
    _grid = [round(-0.2 + 0.03 * _k, 2) for _k in range(61)]
    _clean_means, _noisy_means = [], []
    for _b in _grid:
        _tb = offset_player(demo_ramp_b, _b)
        _clean_means.append(
            sum(exact_rates(DEMO_N, demo_ramp_a, _tb)) / (2 * DEMO_N)
        )
        _noisy_means.append(
            sum(exact_asym_rates(DEMO_N, demo_ramp_a, _tb, _e0, _e1)) / (2 * DEMO_N)
        )
    _peak_clean = _grid[_clean_means.index(max(_clean_means))]
    _peak_noisy = _grid[_noisy_means.index(max(_noisy_means))]
    print(f"  noiseless mean peaks at offset {_peak_clean:+.2f}")
    print(f"  noisy mean peaks at offset     {_peak_noisy:+.2f}")
    print("  same offset: tuning the strategy to the readout noise buys nothing")

    _clean = exact_rates(DEMO_N, demo_ramp_a, demo_ramp_b)
    _noisy = exact_asym_rates(DEMO_N, demo_ramp_a, demo_ramp_b, _e0, _e1)
    _worst = 0.0
    for _k, (_x, _y) in enumerate(template.question_order(DEMO_N)):
        _vertex, _edge = readout_asym_rates(_clean[_k], _e0, _e1)
        _closed = _vertex if _x == _y else _edge
        _worst = max(_worst, abs(_noisy[_k] - _closed))
    print(f"  affine law vs the channel, worst question: {_worst:.1e}")
    print(
        f"  fingerprint it does leave: vertex block sits (e0 - e1)^2 = "
        f"{readout_asym_block_gap(_e0, _e1):.1e} above the edge block"
    )
    print(
        f"  and the mean deficit at the optimum would be "
        f"delta_from_readout_asym({DEMO_N}, {_e0}, {_e1}) = "
        f"{delta_from_readout_asym(DEMO_N, _e0, _e1):.6f}"
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Coherent miscalibration, the error family you can counter

    A device can also be wrong before the readout: the rotation it performs is
    not quite the rotation you asked for. Two simple models. A per-player
    additive offset adds a constant to every angle one player requests. A
    multiplicative error runs every rotation fractionally long.

    These behave nothing like readout noise. Only the difference of the two
    players' angles enters any probability, so an offset shared by both
    players cancels identically and is invisible; the cell below shows the
    rates not moving. A one-player offset shifts every difference by the same
    constant, which moves the vertex block and the edge block in opposite
    directions, first order in the offset, while the mean only drops at
    second order. A multiplicative error distorts each question by an amount
    that depends on that question's angles, so the profile stops being flat
    in a patterned way.

    That is what makes this family actionable where readout noise is not:
    the per-question profile of your own run 1 is the measurement, the model
    has one parameter, and the counter is a line in your angle functions.
    Whether either QPU actually has such a bias is an open question: the dry
    run's profile was flat to within its error bars. The lever is real, and
    it may find nothing to move.
    """)
    return


@app.cell
def _(DEMO_N):
    # The three coherent dials, side by side, on the stand-in candidate.
    _eps, _b = 0.03, 0.08
    _base = exact_rates(DEMO_N, demo_ramp_a, demo_ramp_b)
    _mult = exact_rates(
        DEMO_N, miscalibrated(demo_ramp_a, _eps), miscalibrated(demo_ramp_b, _eps)
    )
    _one = exact_rates(DEMO_N, offset_player(demo_ramp_a, _b), demo_ramp_b)
    _both = exact_rates(
        DEMO_N, offset_player(demo_ramp_a, _b), offset_player(demo_ramp_b, _b)
    )
    print(f"Per-question exact rates, eps = {_eps}, b = {_b}")
    print(f"{'question':>9} {'clean':>8} {'x(1+eps)':>9} {'Alice+b':>8} {'both+b':>8}")
    for _k, (_x, _y) in enumerate(template.question_order(DEMO_N)):
        print(
            f"{template.question_key(_x, _y):>9} {_base[_k]:>8.4f} "
            f"{_mult[_k]:>9.4f} {_one[_k]:>8.4f} {_both[_k]:>8.4f}"
        )
    _moved = max(abs(_both[_k] - _base[_k]) for _k in range(2 * DEMO_N))
    print(f"  both players offset together: largest rate change {_moved:.1e},")
    print("  because only angle differences enter, so a shared offset is invisible")
    return


@app.cell
def _(DEMO_N):
    # Fit and counter. The device secretly over-rotates; the profile alone
    # recovers the parameter, and the inverse request cancels it.
    _true_eps = 0.045
    _observed = exact_rates(
        DEMO_N,
        miscalibrated(demo_ramp_a, _true_eps),
        miscalibrated(demo_ramp_b, _true_eps),
    )

    def _residual(eps_guess):
        _predicted = exact_rates(
            DEMO_N,
            miscalibrated(demo_ramp_a, eps_guess),
            miscalibrated(demo_ramp_b, eps_guess),
        )
        return sum((_p - _o) ** 2 for _p, _o in zip(_predicted, _observed))

    _candidates = [0.002 * _k for _k in range(51)]
    _fitted = min(_candidates, key=_residual)
    _scale = 1.0 / (1.0 + _fitted)
    _countered = exact_rates(
        DEMO_N,
        miscalibrated(miscalibrated(demo_ramp_a, _scale - 1.0), _true_eps),
        miscalibrated(miscalibrated(demo_ramp_b, _scale - 1.0), _true_eps),
    )
    _clean_mean = sum(exact_rates(DEMO_N, demo_ramp_a, demo_ramp_b)) / (2 * DEMO_N)
    print(f"A hidden multiplicative error of {_true_eps} on the device")
    print(f"  observed mean   {sum(_observed) / len(_observed):.6f}")
    print(f"  fitted eps      {_fitted:.3f} from the per-question profile alone")
    print(f"  countered mean  {sum(_countered) / len(_countered):.6f}")
    print(f"  clean mean      {_clean_mean:.6f}, the target the counter recovers")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### The run 1 recipe

    On hardware you cannot rerun the sweep at zero cost, so the fit above
    runs on the one profile run 1 hands you. The motion is the same four
    steps at any error model.

    1. Turn `counts.json` into the 2n per-question rates.
    2. Look at the profile against what your strategy predicts: flat blocks,
       a tilted block, one question out of line, a vertex-edge gap.
    3. Fit the one-parameter model that matches the shape, exactly as the
       cell above fits eps.
    4. Counter it in your run 2 angle functions, which the template lets you
       change freely, and keep the change in your flash talk: a measured
       bias and its counter is a real experiment.

    Two honesty notes. A gap between blocks can also be readout asymmetry,
    which you cannot counter, so check its size first: readout asymmetry
    caps the gap at (e0 - e1)^2, tiny, while a coherent offset moves it
    first order. And the organizers' dry run saw a per-question profile
    consistent with flat, so the honest expectation is that there may be no
    coherent bias to find. A fit that finds nothing, reported as finding
    nothing, is a better experiment than a counter applied to noise.

    The other lever the run itself exposes is `TWIRLS` in the submission
    template: k Pauli-twirled variants per question, each unitarily
    equivalent to your circuit, folding coherent error on the CNOT into a
    stochastic channel. It costs k task fees per question and its gain on
    this device is unmeasured, which is exactly the kind of bet the
    Challenge Instructions, What you may change about the run, prices and
    leaves to you.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Choose your weekend

    The deficit is one number and it sizes everything else. The circuit is
    identical at every n, so the deficit is taken to be the same at every n,
    and a cheap certifying sweep at low n measures it. What that measurement
    no longer buys is the old default path: calibrating first and then
    committing at the top affordable n does not fit the $20.00 cap, because
    the frontier commit already prices at nearly the whole cap whatever the
    deficit is. Calibrate-then-commit still works a rung or two down, and that
    is one of three genuinely different weekends the cap funds:

    - The ladder: certify n = 9 (run 1, and it doubles as the deficit
      measurement), then n = 11 (run 2). Two certifications, a measured
      deficit between them, and run 2 sized on a number about your device
      rather than about a published guess.
    - The one-shot commit: skip run 1 entirely, keep its dollars, and buy
      the largest n the cap affords, sized for 90% power at the deficit you
      declared without measuring. Priced at nearly the whole cap, no
      measurement of your own under it, so the declaration is the whole bet.
    - The nonlocal-content chase: stay at n = 5 and spend everything on shots.
      Smallest n, but the tightest certified lower bound on the win rate, and
      the only path with a real chance of certifying nonlocal content past
      the CHSH ceiling, which no two-qubit CHSH experiment can reach.

    Both runs are yours to spend, and either deadline accepts a first
    submission. Section "Size it" of the Challenge Instructions prices all
    three paths; Section "Read what came back" is where you read the deficit
    off the counts an organizer hands back.

    The equal-rate test earns its keep here too. The deficit you measure is
    omega_q(n) less the win rate your run produced, so any gap between your
    strategy and the optimum lands inside it and is then carried into every
    later sizing decision. Settle the strategy in simulation first.
    """)
    return


@app.cell
def _(delta_slider):
    # The three archetypes, priced live at the deficit on the slider. At the
    # slider's opening 0.015 these are the same numbers Section "Size it" of
    # the Challenge Instructions carries, which is that section's illustration
    # rather than either device. Dial your own declared deficit to reprice them.
    _delta = delta_slider.value
    print(f"Three weekends inside the ${CAP_PER_TEAM:.2f} cap, deficit {_delta:.4f}")

    _nine = shots_for_significance(9, _delta)
    _eleven = shots_for_significance(11, _delta)
    if _nine is None or _eleven is None:
        print("  ladder             9 then 11 is infeasible at this deficit")
    else:
        _ladder = cost(9, _nine) + cost(11, _eleven)
        print(
            f"  ladder             certify C_9 (${cost(9, _nine):.2f}), then "
            f"C_11 (${cost(11, _eleven):.2f}): ${_ladder:.2f}"
        )

    _commit = largest_n_affordable(CAP_PER_TEAM, _delta)
    if _commit is None:
        print("  one-shot commit    nothing certifies inside the cap")
    else:
        print(
            f"  one-shot commit    C_{_commit[0]} at {_commit[1]} shots "
            f"per circuit, ${_commit[2]:.2f}"
        )

    _chase_shots = shots_affordable(5, CAP_PER_TEAM)
    _odds = chsh_ceiling_power(5, _chase_shots, _delta)
    print(
        f"  chase              C_5 at {_chase_shots} shots per circuit, "
        f"${cost(5, _chase_shots):.2f}, P(beat CHSH ceiling) = {_odds:.2f}"
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Before anything is spent

    Four things hold before a pull request goes up.

    1. Your strategy reaches omega_q(n) in simulation, with `equal_rate_check`
       flat across all 2n questions.
    2. The same strategy still certifies at the deficit you expect the device to
       have. Run it through `simulate_noisy` at the p that produces that deficit
       and confirm the measured deficit lands under
       `largest_delta_certified(n, shots)` for the sweep you are buying. A plan
       that only clears the gate on a perfect device has no margin in it.
    3. `scripts/plan_check.py` agrees that the sweep you plan clears the gate
       and fits what your team has left.
    4. `scripts/submission_check.py` passes on the script itself.

    Every hardware run is executed by an organizer against one event key, so the
    script you submit is the run that happens. Section "Submit it" of the
    Challenge Instructions has the rest of the path.
    """)
    return


if __name__ == "__main__":
    app.run()
