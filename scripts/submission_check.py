# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The one command that gates a submission.

    uv run --python 3.12 scripts/submission_check.py submissions/<your-team>_run1.py

Four stages, stopping at the first one that fails:

1. Inspect the source, without running it. Portability, no credential, no
   absolute path, no network module, no disallowed mitigation library, a PEP 723
   header with pinned versions, and a parameter block that can be read without
   executing anything.
2. Execute it against a local PennyLane simulator, in a scratch copy of this
   repository, at the same n and shots. First it rebuilds the circuits and
   checks the game's shape, a shared preparation identical in every circuit and
   then single-qubit gates depending only on that wire's own question, which is
   the structure the classical bound is a statement about. Then it runs the
   sweep. The device string is the only thing swapped, which is what makes this
   evidence about the run an organizer will make.
3. Validate what it wrote. Both files present, one entry per question in the
   fixed order, four answer keys each, every circuit summing to exactly the
   declared shot count, and a claimed win rate that matches what the counts say.
4. Read the script's own parameter block and hand it to `plan_check.py`, the
   script's own declared DELTA included. The run that executes is the run that
   passed the arithmetic gate, against the assumption its own author declared.

Exit status is 0 when every stage passes and 1 otherwise. Every failure names
what failed, where, and what to change.

An optional second argument is the team's remaining dollars against its cap:

    uv run --python 3.12 scripts/submission_check.py <script> 6.10

Without it stage 4 checks against the full per-team cap, which is right for a
run 1 and too generous for a run 2 following a run 1 that already spent. An
organizer reading the spend ledger passes the remainder; a team checking its
own run 1 leaves it off.

Nothing here reaches a quantum device or the network. Stage 2 runs a simulator
with the hardware routing stripped out of the environment, so this command is
safe to run as often as you like and costs nothing.
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from game_numbers import (  # noqa: E402
    CHSH_CEILING,
    MINIMUM_SHOTS,
    P_3SIGMA,
    QPU_ROUTES,
    certified_p_nl,
    confidence_half_width,
    omega_c,
    p_value,
)

# The names an organizer reads off a submission to know what it costs and where
# it goes. QPU and DELTA joined on 21 August 2026, when the event stopped
# publishing a device deficit and stopped fixing the device: both are required
# rather than optional, because an optional parameter needs a default and a
# shipped default deficit is exactly the thing that was removed.
REQUIRED_PARAMETERS = ("TEAM", "RUN", "N", "SHOTS", "QPU", "DELTA", "DEVICE")

# Read when present, defaulted when absent. TWIRLS joined the template on
# 20 August 2026, and a submission copied from the earlier template carries no
# such name; it means one task per question, which is what the default says.
OPTIONAL_PARAMETERS = {"TWIRLS": 1}

SIMULATOR = "default.qubit"

# Stripped from the child environment in stage 2. Removing the routing is what
# makes a hardware device string impossible rather than merely unlikely, and
# removing the credentials means a script that reached for one would stop rather
# than spend.
STRIPPED_FROM_ENVIRONMENT = (
    "QBRAID_DEVICE",
    "QBRAID_API_KEY",
    "QBRAID_ACCESS_TOKEN",
    # The Open Quantum era's variables. Stripping stale names costs nothing,
    # and an organizer machine may still carry them.
    "QUPACABRATHON_BACKEND",
    "OPENQUANTUM_TOKEN",
    "OPENQUANTUM_CLIENT_ID",
    "OPENQUANTUM_CLIENT_SECRET",
)

# Networking belongs to the device layer, which is `pennylane` and the qBraid
# runtime underneath it. A submitted script that opens its own connection
# is doing something the organizer executing it cannot account for.
NETWORK_MODULES = frozenset(
    {"socket", "requests", "httpx", "aiohttp", "urllib", "http", "ftplib", "telnetlib"}
)

# Post-execution mitigation is disallowed outright, so importing a library that
# does it is caught here rather than by an organizer at 5:00 PM.
MITIGATION_MODULES = frozenset({"mitiq", "qermit", "qiskit_research", "zne", "pyGSTi"})
MITIGATION_ATTRIBUTES = frozenset(
    {
        "mitigate_with_zne",
        "fold_global",
        "poly_extrapolate",
        "richardson_extrapolate",
        "exponential_extrapolate",
    }
)

# Names whose value is a secret if it is written down rather than read from the
# environment.
CREDENTIAL_NAMES = re.compile(r"(?i)(token|secret|password|passwd|credential|api_?key)")

# Literal shapes that are a key however they were assigned.
CREDENTIAL_LITERALS = re.compile(
    r"(?i)^(sk-[a-z0-9]|sk_live|oq_live|oq_sk|qbraid_[a-z0-9]{8}|bearer\s+\S)"
)

# A token inside any string literal that would only resolve on one machine.
ABSOLUTE_PATH = re.compile(r"^(?:~[/\\]|/[A-Za-z_.][^\s'\"]{2,}|[A-Za-z]:[\\/])")


class Failure(Exception):
    """A stage's verdict. Carries what to change, never a traceback."""

    def __init__(self, stage: str, problems: list[str]) -> None:
        super().__init__(stage)
        self.stage = stage
        self.problems = problems


def fail(stage: str, *problems: str) -> Failure:
    return Failure(stage, list(problems))


# --------------------------------------------------------------------------
# Stage 1: inspect the source
# --------------------------------------------------------------------------


def pep723_block(source: str) -> str | None:
    """The TOML inside a `# /// script` block, or `None` when there is none."""
    match = re.search(
        r"(?m)^# /// script$\s(?P<body>(?:^#(?:| .*)$\s)+)^# ///$", source
    )
    if match is None:
        return None
    return "".join(
        line.removeprefix("# ").removeprefix("#") + "\n"
        for line in match.group("body").splitlines()
    )


def raw_pep723(source: str) -> str:
    """The `# /// script` block verbatim, markers included, or empty."""
    match = re.search(r"(?m)^# /// script$\s(?:^#(?:| .*)$\s)+^# ///$", source)
    return "" if match is None else match.group(0)


def check_pep723(source: str) -> list[str]:
    block = pep723_block(source)
    if block is None:
        return [
            "no PEP 723 header. The organizer's machine installs your dependencies "
            "from it, so a script without one runs against whatever happens to be "
            "there. Copy the `# /// script` block from "
            "challenge/submission-template.py."
        ]
    try:
        meta = tomllib.loads(block)
    except tomllib.TOMLDecodeError as exc:
        return [f"the PEP 723 header is not valid TOML: {exc}"]

    problems = []
    dependencies = meta.get("dependencies")
    if not dependencies:
        problems.append("the PEP 723 header declares no dependencies")
        return problems
    for entry in dependencies:
        if "==" not in entry:
            problems.append(
                f"dependency {entry!r} is not pinned. Write it as "
                f"{entry.split('[')[0].strip()}==<version>, so the run an organizer "
                "makes uses the versions you tested against."
            )
    if "requires-python" not in meta:
        problems.append('the PEP 723 header has no `requires-python = ">=3.12"`')
    return problems


def string_constants(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """Every string literal, with each f-string yielded whole.

    An f-string reaches the parser as one literal fragment per gap between its
    substitutions, so `f"results/{name}/counts.json"` would otherwise arrive as a
    fragment beginning with a slash. Substitutions come back as `{}`, which keeps
    a fragment boundary from looking like the start of a path.
    """
    fragments = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node)
        if isinstance(part, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield node.lineno, "".join(
                part.value
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
                else "{}"
                for part in node.values
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in fragments
        ):
            yield node.lineno, node.value


def check_absolute_paths(tree: ast.Module) -> list[str]:
    problems = []
    for lineno, value in string_constants(tree):
        for token in re.split(r"[\s'\"(),\[\]]+", value):
            if token and ABSOLUTE_PATH.match(token):
                problems.append(
                    f"line {lineno}: {token!r} is an absolute path. An organizer runs "
                    "this on a machine that is not yours, so build every path from "
                    "`Path(__file__)` or leave it to the template."
                )
    return problems


def check_credentials(tree: ast.Module) -> list[str]:
    problems = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            for target in node.targets:
                name = None
                if isinstance(target, ast.Name):
                    name = target.id
                elif isinstance(target, ast.Subscript) and isinstance(
                    target.slice, ast.Constant
                ):
                    name = str(target.slice.value)
                if name and CREDENTIAL_NAMES.search(name) and len(value.value) >= 8:
                    problems.append(
                        f"line {node.lineno}: {name} is assigned a literal. A key never "
                        "appears in a submitted script. The runtime reads "
                        "QBRAID_API_KEY out of the organizer's environment itself."
                    )

    for lineno, value in string_constants(tree):
        if CREDENTIAL_LITERALS.match(value.strip()):
            problems.append(
                f"line {lineno}: this string literal is shaped like an API key. "
                "Delete it and let the plugin read the environment."
            )
    return dedupe(problems)


def check_imports(tree: ast.Module) -> list[str]:
    problems = []
    for node in ast.walk(tree):
        modules: list[str] = []
        lineno = 0
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
            lineno = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
            lineno = node.lineno
        for module in modules:
            top = module.split(".")[0]
            if top in NETWORK_MODULES:
                problems.append(
                    f"line {lineno}: imports {module}. The device layer is the "
                    "only thing that talks to a network, and an organizer cannot "
                    "account for a connection your script opens itself."
                )
            if top in MITIGATION_MODULES:
                problems.append(
                    f"line {lineno}: imports {module}, a post-execution "
                    "mitigation library. Only mitigation that changes what the device "
                    "does is allowed. See the challenge instructions, "
                    "What you may change about the run."
                )

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in MITIGATION_ATTRIBUTES:
            problems.append(
                f"line {node.lineno}: uses {node.attr}, which is post-execution "
                "mitigation. It reprocesses counts, and a bound that counts trials "
                "cannot be fed a fit. See the challenge instructions, What you may "
                "change about the run."
            )
    return dedupe(problems)


def read_parameters(tree: ast.Module) -> tuple[dict[str, object], list[str]]:
    """The parameter block, read without executing a line of the script."""
    found: dict[str, object] = {}
    problems = []
    names = REQUIRED_PARAMETERS + tuple(OPTIONAL_PARAMETERS)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id in names):
                continue
            try:
                found[target.id] = ast.literal_eval(node.value)
            except ValueError:
                problems.append(
                    f"line {node.lineno}: {target.id} is computed rather than written "
                    "down. An organizer has to be able to read what a run costs off "
                    "the top of the file."
                )
    for name in REQUIRED_PARAMETERS:
        if name not in found and not any(name in problem for problem in problems):
            problems.append(
                f"the parameter block has no {name}. It needs all of "
                f"{', '.join(REQUIRED_PARAMETERS)}, at module level, each one a "
                "literal."
            )
    for name, default in OPTIONAL_PARAMETERS.items():
        if name not in found and not any(name in problem for problem in problems):
            found[name] = default
    return found, problems


def check_parameter_values(parameters: dict[str, object]) -> list[str]:
    problems = []
    team = parameters.get("TEAM")
    if isinstance(team, str) and not re.fullmatch(r"[A-Za-z0-9_-]{3,50}", team):
        problems.append(
            f"TEAM = {team!r} is not a valid identifier. Letters, digits, underscores "
            "and hyphens only."
        )
    if parameters.get("RUN") not in (1, 2):
        problems.append(f"RUN = {parameters.get('RUN')!r} is not 1 or 2.")
    n = parameters.get("N")
    if not isinstance(n, int) or isinstance(n, bool) or n < 3 or n % 2 == 0:
        problems.append(f"N = {n!r} is not an odd cycle. Pick an odd n at least 3.")
    shots = parameters.get("SHOTS")
    if not isinstance(shots, int) or isinstance(shots, bool) or shots < 1:
        problems.append(f"SHOTS = {shots!r} is not a run.")
    twirls = parameters.get("TWIRLS", 1)
    if not isinstance(twirls, int) or isinstance(twirls, bool) or not 1 <= twirls <= 16:
        problems.append(
            f"TWIRLS = {twirls!r} is not an integer between 1 and 16. Each "
            "twirl is a separately billed task per question, so the count is "
            "bounded."
        )
    elif isinstance(shots, int) and not isinstance(shots, bool) and shots % twirls != 0:
        problems.append(
            f"SHOTS = {shots} does not split into TWIRLS = {twirls} equal "
            "variants. Every variant gets the same honest trials, so pick "
            "SHOTS as a multiple of TWIRLS; the published S_90 tables are "
            "sized at TWIRLS = 1, so round S up to the next multiple."
        )
    elif (
        isinstance(shots, int)
        and not isinstance(shots, bool)
        and shots // twirls < MINIMUM_SHOTS
    ):
        problems.append(
            f"SHOTS = {shots} over TWIRLS = {twirls} variants is "
            f"{shots // twirls} shots per variant, below the {MINIMUM_SHOTS} "
            "floor the event enforces per circuit task."
        )
    qpu = parameters.get("QPU")
    if qpu not in QPU_ROUTES:
        problems.append(
            f"QPU = {qpu!r} is not a device this event offers. Pick one of "
            f"{sorted(QPU_ROUTES)}. Name the device, never the route."
        )
    # Nothing here compares DELTA against the device. The event publishes no
    # deficit for either device, and this is the team's own declared number:
    # what is checked is that it is a deficit at all, and `check_plan` below
    # checks that the shot count and the budget are consistent with it.
    delta = parameters.get("DELTA")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        problems.append(f"DELTA = {delta!r} is not a number.")
    elif not 0.0 <= delta < 0.5:
        problems.append(
            f"DELTA = {delta} is not a device deficit in [0, 0.5). It is "
            "omega_q - omega, the shortfall the run is sized against."
        )
    device = parameters.get("DEVICE")
    if not isinstance(device, str):
        problems.append(f"DEVICE = {device!r} is not a device string.")
    return problems


def check_build_circuits(tree: ast.Module) -> list[str]:
    """Reject the shipped stub before paying an execution to discover it."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_circuits":
            body = [
                statement
                for statement in node.body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                )
            ]
            if len(body) == 1 and isinstance(body[0], ast.Raise):
                return [
                    f"line {body[0].lineno}: build_circuits is still the stub the "
                    "template ships, so this submission has no circuits to run. "
                    "Return 2n gate functions in the order question_order(n) "
                    "gives, and see the Background Notes at "
                    "https://qupacabrathon.dev for the derivation."
                ]
            return []
    return ["the script defines no build_circuits"]


# A device route named in the file rather than resolved by the organizer's
# environment. The pattern matches only strings that open with a vendor prefix,
# so the team's own `QPU = "emerald"` label passes and a route does not.
DEVICE_ROUTE_LITERAL = re.compile(r"(?i)^(aws:|qrn:|rigetti:|iqm:|ionq:|azure:)")


def check_device_literals(tree: ast.Module) -> list[str]:
    """Reject a script that names a hardware route itself.

    The predecessor of this check enforced `auto_confirm=True` on the Open
    Quantum plugin, whose submit path otherwise blocked on `input()`. The qBraid
    Runtime submit path has no confirmation prompt (verified by reading
    `QbraidDevice.submit` in qbraid 0.12.2), so that check is retired. What the
    qBraid port needs instead is this one.

    The split it enforces changed on 21 August 2026, when teams were given the
    device choice. The team picks the device, by label, in QPU. The organizer
    owns the route that reaches that device, carried by QBRAID_DEVICE, which is
    what lets a device be swapped for its fallback without touching twelve
    identically checked submissions. A script that hardcodes a route takes that
    decision away and silently overrides where its run is sent.
    """
    problems = []
    for lineno, value in string_constants(tree):
        if DEVICE_ROUTE_LITERAL.match(value.strip()):
            problems.append(
                f"line {lineno}: {value!r} names a hardware route. The QPU comes "
                "from the organizer's QBRAID_DEVICE environment, never from the "
                "script, so the announced device and its fallback stay an "
                "organizer decision."
            )
    return dedupe(problems)


def inspect_source(path: Path) -> dict[str, object]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise fail("1, source", f"line {exc.lineno}: {exc.msg}") from exc

    parameters, parameter_problems = read_parameters(tree)
    problems = (
        check_pep723(source)
        + check_absolute_paths(tree)
        + check_credentials(tree)
        + check_imports(tree)
        + parameter_problems
        + check_parameter_values(parameters)
        + check_build_circuits(tree)
        + check_device_literals(tree)
    )
    if problems:
        raise fail("1, source", *problems)
    return parameters


# --------------------------------------------------------------------------
# Stage 2: execute against a local simulator
# --------------------------------------------------------------------------


def swap_device(source: str, tree: ast.Module) -> tuple[str, bool]:
    """Force DEVICE to the simulator, and say whether that changed anything."""
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "DEVICE":
                end = node.end_lineno or node.lineno
                original = "".join(lines[node.lineno - 1 : end])
                if original.strip() == f'DEVICE = "{SIMULATOR}"':
                    return source, False
                lines[node.lineno - 1 : end] = [f'DEVICE = "{SIMULATOR}"\n']
                return "".join(lines), True
    return source, False


def build_sandbox(path: Path, root: Path) -> Path:
    """A scratch copy of the repository layout, with the script in `submissions/`.

    The script is run here rather than where it sits, for two reasons. It reaches
    `scripts/` through `parents[1]`, so it has to sit one level below a root that
    has one. And a check should leave nothing behind: everything the run writes
    lands in this directory and goes away with it.
    """
    shutil.copytree(
        SCRIPTS_DIR,
        root / "scripts",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    submissions = root / "submissions"
    submissions.mkdir()
    source = path.read_text(encoding="utf-8")
    swapped, changed = swap_device(source, ast.parse(source))
    if changed:
        print(f"  DEVICE swapped to {SIMULATOR!r} for this check")
    target = submissions / path.name
    target.write_text(swapped, encoding="utf-8")
    return target


def require_uv() -> None:
    if shutil.which("uv") is None:
        raise fail(
            "2, execution",
            "uv is not on PATH. It is what installs the versions your PEP 723 "
            "header pins. Install it from https://docs.astral.sh/uv/ and try again.",
        )


def child_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in STRIPPED_FROM_ENVIRONMENT
    }


# Runs in the sandbox under the submission's own PEP 723 header, so it resolves
# exactly the versions the run would while this checker stays dependency-free.
# It imports the submission as a module, calls `build_circuits` exactly the way
# the fixed region does, and records every circuit as [name, wires, params]
# triples, parameters flattened to [real, imag] pairs.
STRUCTURE_PROBE = '''\
"""Rebuild the submission's circuits and record their gate structure as JSON.

Written and run by scripts/submission_check.py."""

import importlib.util
import json
import sys
from pathlib import Path

import numpy
import pennylane as qml

# Dropped before the shape is judged. A barrier or a snapshot is an annotation,
# an identity does nothing, and a global phase is unobservable, so none of them
# can carry a question from one player to the other.
COSMETIC = {"Barrier", "Snapshot", "Identity", "GlobalPhase"}


def main() -> int:
    submission, n, out = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    spec = importlib.util.spec_from_file_location("submission_under_check", submission)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    record = []
    for gates in module.build_circuits(n, module.strategy_angle(n)):
        tape = qml.tape.make_qscript(gates)()
        ops = []
        for op in tape.operations:
            if op.name in COSMETIC:
                continue
            params = []
            for parameter in op.parameters:
                flat = numpy.asarray(parameter, dtype=complex).reshape(-1)
                params.extend([[float(v.real), float(v.imag)] for v in flat])
            ops.append([op.name, [str(w) for w in op.wires], params])
        record.append(ops)
    out.write_text(json.dumps(record), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def run_structure_probe(
    target: Path, root: Path, environment: dict[str, str], n: int
) -> list:
    probe = root / "structure_probe.py"
    out = root / "structure.json"
    header = raw_pep723(target.read_text(encoding="utf-8"))
    probe.write_text(header + "\n\n" + STRUCTURE_PROBE, encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--python",
                "3.12",
                "--script",
                str(probe),
                str(target),
                str(n),
                str(out),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise fail(
            "2, structure",
            "rebuilding the circuits for inspection did not finish in 10 "
            "minutes. build_circuits has to return quickly, because the run "
            "an organizer makes calls it once before anything executes.",
        ) from exc
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip().splitlines()
        raise fail(
            "2, structure",
            "the circuits could not be rebuilt for inspection: importing the "
            "script and calling build_circuits(N, strategy_angle(N)) failed. "
            "The usual cause is an import your notebook had and this script "
            "does not, since this is the first thing that runs your code.",
            *tail[-12:],
        )
    return json.loads(out.read_text(encoding="utf-8"))


def check_structure(record: list, n: int) -> list[str]:
    """The nonlocal-game shape the rebuilt circuits have to keep.

    Everything up to and including the last multi-wire gate is the shared
    preparation, identical in all 2n circuits. What follows has to be
    single-wire, wire 0 depending only on the first player's question and
    wire 1 only on the second player's. Each player's question value appears
    in exactly two circuits, which is what makes the dependence checkable.
    """
    if len(record) != 2 * n:
        return [f"build_circuits returned {len(record)} circuits, expected {2 * n}."]

    questions = question_order(n)
    problems: list[str] = []
    preparations = []
    local_gates = []
    for index, ops in enumerate(record):
        gates = [
            (
                name,
                tuple(wires),
                tuple((round(p[0], 9), round(p[1], 9)) for p in params),
            )
            for name, wires, params in ops
        ]
        for name, wires, _ in gates:
            for wire in wires:
                if wire not in ("0", "1"):
                    problems.append(
                        f"question {questions[index]}: {name} acts on wire "
                        f"{wire}. The run is two wires, 0 for the first player "
                        "and 1 for the second, with the measurement owned by "
                        "the template, so there is no other wire to reach."
                    )
        last_multi = max(
            (i for i, gate in enumerate(gates) if len(gate[1]) > 1), default=-1
        )
        preparations.append(tuple(gates[: last_multi + 1]))
        suffix = gates[last_multi + 1 :]
        local_gates.append(
            (
                tuple(gate for gate in suffix if gate[1] == ("0",)),
                tuple(gate for gate in suffix if gate[1] == ("1",)),
            )
        )
    if problems:
        return dedupe(problems)

    for index in range(1, 2 * n):
        if preparations[index] != preparations[0]:
            problems.append(
                "the gates up to and including the last two-qubit gate differ "
                f"between the circuits for questions {questions[0]} and "
                f"{questions[index]}. That prefix is the shared state the "
                "players agreed on before any question arrived, so it has to "
                "be identical in all 2n circuits. A two-qubit gate that "
                "depends on the question lets the players read each other's "
                "questions, and the bounds say nothing about players who do. "
                "See the instructions, What you may change about the run."
            )
            break

    for player, wire_label in ((0, "0"), (1, "1")):
        seen: dict[int, int] = {}
        for index, question in enumerate(questions):
            vertex = question[player]
            if vertex not in seen:
                seen[vertex] = index
                continue
            other = seen[vertex]
            if local_gates[index][player] != local_gates[other][player]:
                problems.append(
                    f"wire {wire_label}'s gates differ between the circuits "
                    f"for questions {questions[other]} and {questions[index]}, "
                    f"which ask player {player + 1} the same vertex {vertex}. "
                    "After the shared preparation, each player's gates may "
                    "depend only on that player's own question. See the "
                    "instructions, What you may change about the run."
                )
                break
    return dedupe(problems)


def check_circuit_structure(
    target: Path, root: Path, environment: dict[str, str], n: int
) -> None:
    record = run_structure_probe(target, root, environment, n)
    problems = check_structure(record, n)
    if problems:
        raise Failure("2, structure", problems)
    print("  circuit shape: shared preparation, then per-player local gates")


def run_simulated(target: Path, root: Path, environment: dict[str, str]) -> str:
    print(f"  running {target.name} on {SIMULATOR}, this takes a minute")
    try:
        completed = subprocess.run(
            ["uv", "run", "--python", "3.12", "--script", str(target)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise fail(
            "2, execution",
            "the script did not finish in 30 minutes on a simulator. Something in "
            "build_circuits is not terminating, or n and shots are far larger than "
            "the cap allows.",
        ) from exc

    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip().splitlines()
        raise fail(
            "2, execution",
            f"the script exited {completed.returncode} on the simulator. It has to "
            "run start to finish here before it runs on hardware, because an "
            "organizer executing it is spending shared money.",
            *tail[-12:],
        )
    return completed.stdout


# --------------------------------------------------------------------------
# Stage 3: validate what it wrote
# --------------------------------------------------------------------------


def question_order(n: int) -> list[tuple[int, int]]:
    return [(i, i) for i in range(n)] + [(i, (i + 1) % n) for i in range(n)]


def is_win(x: int, y: int, a: int, b: int) -> bool:
    return a == b if x == y else a != b


def load_json(path: Path, label: str) -> dict[str, object]:
    if not path.exists():
        raise fail(
            "3, output",
            f"{label} was not written to results/{path.parent.name}/. The template "
            "writes both files at the end of main, so a missing one means the run "
            "stopped early.",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise fail("3, output", f"{label} is not valid JSON: {exc}") from exc


def check_counts(
    counts: dict[str, dict[str, int]], n: int, shots: int
) -> list[float]:
    """Per-question win rates, or a verdict. Nothing here is repaired."""
    problems = []
    expected = [f"{x}|{y}" for x, y in question_order(n)]
    if list(counts.keys()) != expected:
        missing = [key for key in expected if key not in counts]
        extra = [key for key in counts if key not in expected]
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing[:5])}")
        if extra:
            detail.append(f"unexpected {', '.join(extra[:5])}")
        if not detail:
            detail.append("the same keys in a different order")
        raise fail(
            "3, output",
            f"counts.json does not carry the {2 * n} questions of C_{n} in the order "
            f"question_order({n}) gives: {'; '.join(detail)}. The order is what "
            "scores each answer against the question it answered.",
        )

    answer_keys = [f"{a}:{b}" for a in (0, 1) for b in (0, 1)]
    rates = []
    for (x, y), key in zip(question_order(n), expected, strict=True):
        table = counts[key]
        if sorted(table) != sorted(answer_keys):
            problems.append(
                f"counts.json[{key!r}] has answer keys {sorted(table)}, expected "
                f"{answer_keys}."
            )
            continue
        total = sum(table.values())
        if total != shots:
            problems.append(
                f"counts.json[{key!r}] sums to {total}, and the parameter block "
                f"declares SHOTS = {shots}. Every circuit gets exactly the same "
                "honest trials, which is what the certification counts."
            )
            continue
        rates.append(
            sum(table[f"{a}:{b}"] for a in (0, 1) for b in (0, 1) if is_win(x, y, a, b))
            / shots
        )
    if problems:
        # One circuit's failure usually means many, and thirteen copies of the
        # same sentence buries what to change.
        if len(problems) > 3:
            problems = problems[:3] + [f"and {len(problems) - 3} more circuits like it."]
        raise fail("3, output", *problems)
    return rates


def check_benchmark(
    benchmark: dict[str, object], rates: list[float], n: int, shots: int, team: str
) -> None:
    problems = []
    for key in ("algorithmName", "device", "metricName", "metricValue"):
        if key not in benchmark:
            problems.append(f"benchmark.json has no {key!r}, which the database requires.")

    game = benchmark.get("nonlocalGame")
    if not isinstance(game, dict):
        problems.append(
            "benchmark.json has no nonlocalGame block, which is what makes the claim "
            "recomputable."
        )
        raise fail("3, output", *problems)
    for key in ("game", "winRate", "shotsPerCircuit", "countsFile"):
        if key not in game:
            problems.append(f"benchmark.json nonlocalGame has no {key!r}.")

    measured = sum(rates) / len(rates)
    claimed = game.get("winRate")
    if isinstance(claimed, (int, float)) and not math.isclose(
        float(claimed), measured, rel_tol=1e-9, abs_tol=1e-12
    ):
        problems.append(
            f"benchmark.json claims winRate {claimed!r}, and counts.json says "
            f"{measured!r}. The database recomputes the win rate from the counts and "
            "rejects a mismatch, so this submission would be refused after the money "
            "was spent."
        )

    half_width = confidence_half_width(rates, shots)
    claimed_uncertainty = game.get("uncertainty")
    if isinstance(claimed_uncertainty, (int, float)) and not math.isclose(
        float(claimed_uncertainty), half_width, rel_tol=1e-6
    ):
        problems.append(
            f"benchmark.json claims uncertainty {claimed_uncertainty!r}, and "
            f"confidence_half_width over the counts gives {half_width!r}. The "
            "database recomputes it at 1e-6 relative tolerance."
        )

    if game.get("shotsPerCircuit") != shots:
        problems.append(
            f"benchmark.json claims shotsPerCircuit {game.get('shotsPerCircuit')!r}, "
            f"and the parameter block declares SHOTS = {shots}."
        )
    params = game.get("params")
    if isinstance(params, dict) and params.get("n") != n:
        problems.append(
            f"benchmark.json claims n = {params.get('n')!r}, and the parameter block "
            f"declares N = {n}."
        )
    if game.get("eventTeam") not in (None, team):
        problems.append(
            f"benchmark.json claims eventTeam {game.get('eventTeam')!r}, and the "
            f"parameter block declares TEAM = {team!r}."
        )
    if problems:
        raise fail("3, output", *problems)

    print(f"  win rate  {measured:.6f} +/- {half_width:.6f}, recomputed from the counts")
    p = p_value(rates, shots, omega_c(n))
    print(
        f"  p-value   {p:.3e} (exact binomial tail) against omega_c = "
        f"{omega_c(n):.6f}"
    )
    if p <= P_3SIGMA:
        print(
            f"  certified nonlocal content p_NL = {certified_p_nl(rates, shots, n):.4f} "
            f"(CHSH ceiling {CHSH_CEILING:.5f})"
        )


def validate_output(root: Path, parameters: dict[str, object]) -> None:
    team = str(parameters["TEAM"])
    run = int(parameters["RUN"])  # type: ignore[arg-type]
    n = int(parameters["N"])  # type: ignore[arg-type]
    shots = int(parameters["SHOTS"])  # type: ignore[arg-type]

    out_dir = root / "results" / f"{team}_run{run}"
    if not out_dir.is_dir():
        raise fail(
            "3, output",
            f"nothing was written to results/{team}_run{run}/. The template names "
            "that folder from TEAM and RUN, so a run that wrote nowhere else has "
            "had its output path edited.",
        )
    counts_document = load_json(out_dir / "counts.json", "counts.json")
    benchmark = load_json(out_dir / "benchmark.json", "benchmark.json")

    counts = counts_document.get("counts")
    if not isinstance(counts, dict):
        raise fail("3, output", "counts.json has no `counts` object.")

    rates = check_counts(counts, n, shots)
    check_benchmark(benchmark, rates, n, shots, team)


# --------------------------------------------------------------------------
# Stage 4: the arithmetic gate
# --------------------------------------------------------------------------


def check_plan(parameters: dict[str, object], balance: float | None = None) -> None:
    """Hand the script's own parameters to `plan_check.py` and read its verdict.

    A subprocess rather than an import, because `plan_check.py` is also what a
    mentor runs by hand to talk through a plan before any script exists. Going
    through the same entry point is what stops the gate and the conversation
    drifting apart.

    The deficit comes from the script's own DELTA rather than from a default,
    so the plan that is checked is the plan against the assumption the team
    declared. `plan_check.py` requires it and ships no default, which is what
    makes that impossible to skip.

    The device comes from the script's own QPU for the same reason, and here it
    decides the price rather than the shot count. The two QPUs charge the same
    task fee and different per-shot rates, so checking a Garnet submission at
    Emerald's rate would tell the team it can afford less than it can.

    `balance` is the team's remaining dollars against its cap. Left out, the
    plan is checked against the full cap, which is right for a run 1 and too
    generous for a run 2 that follows a run 1 that already spent. An organizer
    reading the spend ledger passes the remainder.
    """
    n, shots = int(parameters["N"]), int(parameters["SHOTS"])  # type: ignore[arg-type]
    twirls = int(parameters.get("TWIRLS", 1))  # type: ignore[arg-type]
    delta = float(parameters["DELTA"])  # type: ignore[arg-type]
    qpu = str(parameters["QPU"])
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "plan_check.py"),
        "--n",
        str(n),
        "--shots",
        str(shots),
        "--delta",
        repr(delta),
        "--qpu",
        qpu,
    ]
    if twirls != 1:
        command += ["--twirls", str(twirls)]
    if balance is not None:
        command += ["--balance", repr(balance)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    for line in completed.stdout.rstrip().splitlines():
        print(f"  {line}")
    if completed.returncode != 0:
        raise fail(
            "4, plan",
            f"plan_check.py rejected N = {n} at {shots} shots per circuit on "
            f"{qpu} against the declared delta = {delta}. Its output is above, "
            "and it says whether the plan misses the certification gate, the "
            "cap, or both.",
        )


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def dedupe(problems: list[str]) -> list[str]:
    seen, unique = set(), []
    for problem in problems:
        if problem not in seen:
            seen.add(problem)
            unique.append(problem)
    return unique


def report(failure: Failure) -> int:
    print()
    print(f"FAILED at stage {failure.stage}")
    for problem in failure.problems:
        print(f"  {problem}")
    print()
    print("Nothing was submitted and nothing was spent. Fix the above and run this again.")
    return 1


def main(argv: list[str]) -> int:
    if not 1 <= len(argv) <= 2:
        print(__doc__)
        print(
            "Give it the script you are about to submit, and optionally the "
            "team's remaining dollars against its cap."
        )
        return 1
    path = Path(argv[0]).resolve()
    if not path.is_file():
        print(f"{argv[0]} is not a file.")
        return 1
    balance: float | None = None
    if len(argv) == 2:
        try:
            balance = float(argv[1])
        except ValueError:
            print(f"{argv[1]!r} is not a dollar balance.")
            return 1
        if balance <= 0.0:
            print(f"a balance of ${balance:.2f} buys nothing; this team is spent out.")
            return 1

    print(f"Checking {path.name}")
    print()

    try:
        print("Stage 1, source")
        parameters = inspect_source(path)
        print(
            f"  TEAM {parameters['TEAM']}, RUN {parameters['RUN']}, "
            f"N {parameters['N']}, SHOTS {parameters['SHOTS']}, "
            f"TWIRLS {parameters.get('TWIRLS', 1)}, "
            f"QPU {parameters['QPU']!r}, DELTA {parameters['DELTA']}, "
            f"DEVICE {parameters['DEVICE']!r}"
        )
        print("  portable, no credential, no absolute path, dependencies pinned")
        print()

        with tempfile.TemporaryDirectory(prefix="submission-check-") as scratch:
            root = Path(scratch)
            print("Stage 2, simulated run")
            require_uv()
            target = build_sandbox(path, root)
            environment = child_environment()
            check_circuit_structure(target, root, environment, int(parameters["N"]))  # type: ignore[arg-type]
            run_simulated(target, root, environment)
            print("  the sweep completed")
            print()

            print("Stage 3, output")
            validate_output(root, parameters)
            print()

        print("Stage 4, plan")
        check_plan(parameters, balance)
    except Failure as failure:
        return report(failure)

    print()
    print(f"PASSED. {path.name} is ready to submit.")
    print("Next: commit it, open the pull request, and wait for a mentor to approve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
