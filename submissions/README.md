# submissions/

Your team's scripts go here, one file per hardware run:

```
submissions/<your-team>_run1.py
submissions/<your-team>_run2.py
```

`<your-team>` is your chosen name joined to the number the organizers assigned
you by an underscore, the same identifier that names your branch, your row in the
spend ledger and your folder in the results database.

Make each file by copying `challenge/submission-template.py` and filling in
`build_circuits`. Copy it rather than editing it in place: the template is what
your run 2 starts from, and it is the file a mentor compares your submission
against.

```
cp challenge/submission-template.py submissions/<your-team>_run1.py
```

Then, before you open the pull request:

```
uv run --python 3.12 scripts/submission_check.py submissions/<your-team>_run1.py
```

GitHub Actions runs that same command on every pull request that touches this
directory, so a red check tells you what to change without anyone having to be
available.

Executing the script writes `results/<your-team>_run<N>/`, which is untracked.
The results an organizer files are the ones their hardware run produced, never
ones a team committed from its own machine.

`challenge/notebook-to-script.md` walks the whole crossing from the notebook you
explored in to the file that lands here.
