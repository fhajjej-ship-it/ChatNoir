# Email-code race: reproduce it, then verify the fix

Run from the repository root with Python 3.10+ (standard library only):

```sh
python3 examples/email-code-race/demo.py
```

Expected output:

```text
CHATNOIR / Synthetic email-code race (local SQLite)
vulnerable: requests=2; sessions=2; replay=0; legitimate=1
vulnerable: requests=8; sessions=8; replay=0; legitimate=1
fixed: requests=2; sessions=1; replay=0; legitimate=1
fixed: requests=8; sessions=1; replay=0; legitimate=1
PASS: reproduced the race; atomic claim permits exactly one session.
Synthetic fixture only: not the Swarmix AI runtime or a scanner detection test.
```

Exit **0** means the vulnerable behavior was reproduced **and** all fixed checks passed. Unexpected results or worker errors exit nonzero. The demo checks both returned successes and persisted session rows; later replay must fail and a fresh legitimate sign-in must work in each variant.

## What changes

Inspect [`consume_vulnerable` and `consume_fixed`](demo.py). Both requests can read the same unused code. The vulnerable update marks it consumed without rechecking eligibility, so both create sessions. The fixed conditional update checks that the code is still unused, unexpired and below the attempt limit; only an update affecting exactly one row permits session creation. The database enforces the claim, without a process-level authentication lock. Claiming and inserting the session share one transaction.

Each worker uses a separate connection to an actual temporary SQLite database. A barrier deliberately aligns reads before writes, making the race reproducible without sleeps; it does not mock database results. The demo runs with two and eight workers, then removes its temporary databases. It opens no server, makes no network requests and needs no accounts, API keys or model calls. All identities and codes are synthetic. The fixed fixture also has regression checks for wrong, expired and exhausted codes, and eligibility changes after the initial read:

```sh
python3 -m unittest discover -s tests -p 'test_email_code_race.py' -v
```

## Relation to the real finding

This is a minimal teaching reproduction of the single-use invariant described in the [Swarmix AI case study](../../README.md#real-app-swarmix-ai). It is independently written public fixture code, not private app source, a NextAuth browser flow or a PostgreSQL concurrency test. The real app was verified separately against PostgreSQL and actual NextAuth callbacks. In particular, eight vulnerable sessions are demonstrated here; the original app's before-fix browser proof measured two.

The simplified fixture omits mail delivery, HTTP authentication, rate limiting, incorrect-code attempt increments and production credential/session management. Do not deploy it as authentication code. ChatNoir's baseline scanner does not detect this race automatically; this demo illustrates source-guided reasoning and runtime fix verification, not detection accuracy or complete application security.
