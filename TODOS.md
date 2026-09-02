# TODOS

Deferred work, with the context needed to pick it up. Items are written down
here rather than left as intentions.

## Phase 1 (backtest correctness) — deferred out of scope

### Half-day sessions need a real exchange calendar
`python_backend/app/session.py` assumes a 16:00 ET close. US equities close at
13:00 ET on roughly nine half-days a year. On an unhandled half-day no bar
satisfies `is_session_last_bar`, so a flatten-by-close rule never fires and the
strategy carries a position overnight that it believed it had closed.

Mitigated, not fixed: `audit_early_close_risk()` reports any session whose tape
ends well before the assumed close, and every `BacktestResult` carries the list
in `audit.sessions_with_early_close_risk`. The failure is loud rather than
silent, but it is still a failure.

Fix: add `exchange_calendars` and source `session_closes` from it. Small change,
one new dependency. Covered by `tests/test_session.py::test_half_day_override_restores_the_last_bar_flag`,
which already proves the override path works — only the source of the overrides
is missing.

### The RSI filter in `morning_momentum` fights its own entry condition
An overnight gap is one large positive delta, so a short-period RSI reads close
to 100 on the gap bar. With the default `rsi_period=5, rsi_max=70`, the filter
rejects precisely the gaps the strategy is hunting. Not a code bug — the code
does what it says — but the default parameters are close to mutually exclusive
on intraday data.

Options: evaluate RSI on the bar before the gap, use a longer RSI period, or
raise `rsi_max`. Needs a decision about what the filter is actually for
(excluding already-extended names) before changing a number.

### `sector_momentum` is single-symbol momentum, not sector rotation
Renamed in its docstring to say what it does. Real sector rotation needs several
symbols priced at the same instants, and the engine feeds a strategy exactly one
symbol. Requires multi-symbol support in the engine — see Phase 4.

The registry key is still `sector_momentum` for API compatibility. Rename it
when there is a migration path for stored bot configs.

### Wilder's RSI vs SMA-based RSI
`indicators/technical.py::calculate_rsi` averages gains and losses with
`rolling().mean()`. The conventional RSI (Wilder) uses an exponential average.
Values differ, particularly on short periods. Not a look-ahead issue and left
alone deliberately: changing it would move every backtest number for reasons
unrelated to the correctness work. Decide explicitly, then change once.

## Phase 2 (persistence and consolidation) — deferred out of scope

### The Postgres schema has never run against Postgres
No Docker daemon and no local Postgres were available, so the schema is verified
two ways that do not need a server:

* the models' DDL is compiled for the `postgresql` dialect and asserted on
  (`tests/test_db_schema.py`), and
* the migration is rendered offline with `alembic upgrade head --sql` against a
  Postgres URL (`tests/test_migrations.py`).

That is genuine verification and it caught two real defects: a `SERIAL` primary
key where the standard is `bigint generated always as identity`, and a partial
index predicate rendered as `enabled IS 1` — valid SQLite, a hard syntax error on
Postgres, in the baseline migration.

What it cannot catch is anything only a live server rejects. Before trusting this
in anything but a test: `docker compose up postgres migrate` and confirm the
migration applies cleanly. Until someone has done that, treat "the schema works"
as an inference, not an observation.

### The test suite runs on SQLite, not Postgres
Deliberate — it keeps the suite fast and server-free — but it means jsonb
behaviour, real `numeric` precision enforcement, concurrent-write behaviour and
lock contention are all untested. SQLite does not enforce `numeric(18,8)`
precision at all.

Worth adding once Docker is available: the same persistence tests parameterised
over both backends, skipped when no Postgres is reachable.

### Redis is declared and used by nothing
`docker-compose.yml` starts Redis. No application code connects to it, in either
service, and nothing in Phases 3–6 currently needs it. Left running rather than
removed because it is pre-existing, but it is dead infrastructure.

### `aiosqlite` is in requirements and unused
The persistence layer is synchronous SQLAlchemy over `sqlite+pysqlite`. Nothing
imports `aiosqlite`. Pre-existing; left alone.

### One pre-existing eslint error in the Node server
`server/src/index.ts:56` — an unused `next` argument in the Express error
handler. Present before this work (verified against HEAD) and unrelated to it, so
it was not touched. Express requires the four-argument signature to recognise the
function as an error handler, so the fix is renaming it `_next`, not deleting it.

### The UI does not yet surface cost assumptions or audit warnings
`BacktestPanel.tsx` renders return, Sharpe, drawdown, win rate and final capital.
It does not show the slippage, commission and sizing those numbers assume, nor
the `audit` block — including `sessions_with_early_close_risk`, which is how an
unhandled half-day announces itself. The data is all in the response and the
types now describe it. Belongs with Phase 5.

### FastAPI CORS is wide open
`main.py` sets `allow_origins=["*"]` with `allow_credentials=True`. Browsers
reject credentialed requests against a wildcard origin, so this is both
permissive and not doing what it appears to. Low urgency while Node is the only
public surface and the Python engine is internal to the compose network — but it
should not stay this way if the engine is ever exposed.

## Phase 3 (risk gate) — deferred out of scope

### The runner MUST write equity snapshots, or nothing trades
`bot_max_daily_loss` and `account_max_daily_loss` fail closed when today's P&L
cannot be determined, and P&L is measured against `equity_snapshots`. Until a
start-of-day snapshot exists for the account and for each bot, every opening
order is blocked. That is deliberate — a missing input must not read as a
comfortable one — but it is an operational prerequisite, not a detail.

Phase 4's runner has to call `risk.context.record_start_of_day_equity()` at
session open for the account and for every enabled bot, and then snapshot each
bot per tick. Per-bot P&L is only as fresh as the last snapshot, because the
broker has no concept of bots and there is no other source of per-bot equity.

### Account risk limits live in environment variables, not the database
`AccountRiskLimits.from_env()` reads `RISK_MAX_TOTAL_EXPOSURE_PCT`,
`RISK_MAX_DAILY_LOSS_PCT` and `RISK_MAX_OPEN_POSITIONS`. There is one account and
one operator, so a table plus a settings screen would have been built for nobody.
Phase 5 wants them editable from the UI, which means a migration and a singleton
row at that point.

Per-bot limits are already in the database (`bots.risk_limits` jsonb), because
those genuinely differ per bot.

### `bot_max_daily_loss` includes unrealised P&L only as of the last snapshot
It compares the latest bot equity snapshot against the first of the day. Between
snapshots, an open position moving against the bot is invisible to the limit. The
mitigation is snapshot cadence, which is the runner's responsibility — noted
above. Nothing here computes marks on its own.

### `flat_by_close` is in the bot's risk limits and the gate does not read it
The strategy enforces it, via `BarContext.is_session_last_bar` from Phase 1. It
is kept in `BotRiskLimits` because it belongs to a bot's risk configuration, and
`test_flat_by_close_is_not_a_gate_rule` asserts the gate does not claim it — a
rule that silently does nothing is worse than no rule.

### The gate does not check `BrokerAccount.trading_blocked`
The broker reports when an account is restricted from trading, and the gate has
no rule for it. Not added because it is not in the plan's ten and adding rules
silently is how a rule table stops matching its documentation. It is a real
candidate for an eleventh rule; the decision belongs to you, not to me.

### A blocked order occupies the bar's idempotency slot
`orders` has a unique index on `(bot_id, symbol, bar_timestamp)`, and a refusal
is a row like any other. So re-evaluating the same bar raises `IntegrityError`
rather than silently double-recording. Correct for the data, wrong for a runner,
which would crash instead of skipping. The runner must call
`repository.find_order_for_bar()` first —
`test_runner_can_detect_a_replayed_bar_before_recording` demonstrates the pattern.

### Symbol conflict is resolved by refusal, not by arbitration
`position_symbol_conflict` blocks a second bot from opening a position in a
symbol another bot already holds. That is the conservative choice and it is
crude: whichever bot gets there first wins, permanently, until it exits. Real
arbitration — priority, proportional allocation, or a shared position with
attributed P&L — is a portfolio-layer design question, not a rule tweak.

## Phase 4 (bot runner) — deviations and deferrals

### Polling, not a websocket
The plan specified an `IntradayClock` reading a websocket stream. `PollingClock`
uses the REST bars endpoint instead, which returns completed bars, and serves both
the daily and intraday roles from one class parameterised by timeframe.

Reason: a websocket client cannot be tested against a live feed here, and an
untested streaming client is exactly the code that ships broken. Polling is the
same interface with the same guarantees and is fully covered by tests.

What is actually given up is latency — a bar is acted on up to `SETTLE_SECONDS`
plus one poll interval after it completes. That matters below one-minute bars and
not above them. If sub-minute trading is ever wanted, the websocket becomes
worthwhile, and it slots in behind `BarClock` without touching the runner.

### Synchronous, not async
The plan said "supervised async run loop". The loop is synchronous. Nothing at
one-minute cadence is I/O-bound enough to need concurrency, and a sync loop is
deterministically testable — every runner test drives a whole session in
milliseconds with no event loop to reason about.

Supervision is real regardless: each tick is caught, audited and counted, one bad
bar does not end a session, and `max_consecutive_errors` disables a bot that is
failing every bar.

### One bot, one symbol, one process
A bot configured for several symbols needs one `runner.main` process per symbol.
Interleaving symbols in one thread would let a slow data call for one symbol
delay decisions for another, and that failure is invisible — a bar acted on late
rather than an error.

Process-per-pair is also easier to supervise: systemd, a container restart
policy, or compose already know how to keep a process alive, and a crash takes
one symbol down rather than the whole book. A multiplexing clock is the
alternative if that ever becomes unwieldy.

There is no daemon or supervisor tree here. `python -m runner.main` runs one
pair until stopped; keeping it alive is the deployment's job, and the hosting
target is still undecided (D4).

### "Matches Alpaca's exactly" was verified against a simulator
The exit criterion names Alpaca. No Alpaca credentials exist in this environment,
so it is verified against `SimBroker`, which keeps its own books from the fills
it grants. Our position is derived from the fills we recorded, so it is a real
independent comparison — but it is not Alpaca.

`SimBroker` also fills immediately, completely, and at a price the test sets.
Partial fills, queueing and rejections-after-acceptance are not modelled. The
router handles partial status (`'partial'`) and the timeout path is tested, but
a genuinely partial fill sequence has never run through it.

Before trusting this with money: run a paper session against Alpaca and compare
`GET /reconciliation` against the Alpaca dashboard at the close.

### The runner recomputes indicators on every tick
`_tick` calls `calculate_all_indicators` plus `strategy.prepare` over the full
window each bar, which is O(n) per tick and O(n²) per session. At 390 bars a
session that is trivial. It is not trivial for a `HistoricalClock` replay over
months, so the backtester — which prepares once — remains the tool for long
histories. Do not reach for the runner to do a backtest.

### Mid-session reconciliation can race a partial fill
Reconciliation compares broker positions against ours. With immediate complete
fills that is exact. Against a real broker, a check landing between a partial
fill and its acknowledgement would see a genuine mismatch and halt the bot for no
good reason. The fix is to skip reconciliation while any order is non-terminal —
`orders_open_idx` exists for that query — and it is not implemented.

### The runner inherits the half-day calendar gap
`is_session_last_bar` comes from `app/session.py`, which assumes a 16:00 close.
On an unhandled half-day the flat-by-close backstop never fires and a bot holds
overnight against its own configuration. Same root cause as the Phase 1 item
above; `exchange_calendars` fixes both at once.

## Phase 5 (UI) — findings and deferrals

### Node has no test suite, and it cost two silent breakages
Both were found only when a UI tried to use the endpoints, weeks after they were
written:

* `/api/strategies` returned a bare array from Node's own registry until Phase 2
  repointed it at the engine, which wraps the list in `{"strategies": [...]}`.
  The TypeScript cast hid the change, so the Trading page's strategy dropdown was
  empty from Phase 2 until Phase 5.
* `GET /backtest/runs` and its siblings existed in the engine from the moment
  backtests started being persisted, and were never mounted in Node. Every
  request 404ed.

Same root cause: adding an engine endpoint is not the same as making it
reachable, and nothing in `server/` is tested. A handful of supertest cases
asserting that each route the frontend calls returns non-404 would have caught
both. Worth doing before Phase 6 adds an approval queue that the UI has to reach.

### Account risk limits are still environment variables
`GET /risk/rules` shows them read-only. Making them editable needs the migration
and singleton row noted under Phase 3. The kill switch and per-bot limits are
editable from the UI; account-wide ones are not.

### The approval queue UI is deliberately absent
Phase 5's brief lists a pending-approval queue, and Phase 6 builds the backend
for it. A queue view with no backend is a dead panel, so instead the footer and
the router state the actual position: live orders are refused. Both halves land
together in Phase 6.

### Starting a bot is still two steps
The UI enables a bot; a runner process has to be attached separately
(`python -m runner.main --bot-id N`). The bot table reports which of the two
states a bot is in — "off", "no runner", "running" — rather than collapsing them
into one indicator, because a bot enabled with nothing attached is the state most
likely to be misread as working.

Closing that gap means a supervisor that watches `bots.enabled` and manages
processes, which is the same decision as the hosting target (D4).

### The bot form takes strategy parameters as raw JSON
It shows the strategy's real defaults and validates against the strategy before
storing, so an invalid tuning is refused with the engine's own message. But it is
a JSON textarea, not per-parameter fields. Generating typed inputs needs each
strategy to describe its parameters (type, range, units), which none of them do.
`default_parameters()` is the start of that; a `parameter_schema()` would finish it.

### Blocked-order counts are lifetime, not per session
The "Blocked" column counts every blocked order a bot has ever had. Useful for
"what is my gate stopping?", misleading for "what happened today". Needs a date
filter on the query.

## Phase 6 (live gating) — findings and remaining gaps

### `server/` now has tests, and writing them was the point
31 vitest cases asserting that every path `web/src/utils/api.ts` calls is
mounted, reaches the engine at the expected path, and is not reshaped on the way
through. This closes the gap that caused two silent breakages in Phase 2 and 5.

The list of frontend paths is hard-coded in the test. A route added to the client
and not the server fails there rather than in a browser. Keep it in step.

### Alembic does not diff a changed check constraint
Autogenerate detected the new `live_settings` table, three new columns, an index
and a new check constraint — but not the *modified* `orders_status_check`, which
had to widen to accept `awaiting_approval`. Verified by inserting one against the
migrated schema and watching it be rejected.

Any future migration that changes an existing constraint's expression has to add
the drop/recreate by hand. Autogenerate will not tell you.

The same migration's downgrade also had to resolve rows before narrowing the
constraint back, or it fails on exactly the databases where the feature was used
and leaves a half-rebuilt table behind.

### Approval is a decision, not a session
Anyone who can reach the API can approve a live order. There is no login, no
per-user attribution, and `approval_granted` records a note but not a who.

That is consistent with the rest of the system — nothing here has auth — and it
is a real gap the moment this is exposed beyond localhost. The Node BFF exists
precisely to hold auth and currently holds none.

### The approval queue is polled, not pushed
The UI refetches every two seconds, and the app-bar badge does the same. Fine for
one operator on one machine. A websocket or SSE would be the honest answer if the
timeout were ever tightened much below a minute, because at that point the poll
interval is a meaningful fraction of the window.

### Auto-approve has no expiry of its own
Once enabled it stays enabled until someone turns it off. A time-boxed version —
"unattended for the next four hours" — would fit the design better, since the
whole reason the flag exists is to cover a period when nobody is watching. Not
built; it is a real product decision rather than an oversight.

### The live ceiling is per order, not per day
`max_order_value` caps one order. Nothing caps the number of live orders, so a
strategy that signals every bar could place many small ones inside the ceiling.
The account-level `max_daily_loss_pct` bounds the damage after the fact; a daily
order count or notional total would bound it in advance.

### Live submission still has not touched Alpaca
Everything in this phase is verified against `SimBroker`. The approval path was
exercised end to end, but the final hop — `submit_approved` against the real
Alpaca live endpoint — has never run. Deliberately: the credentials in this
environment are placeholders, and pointing a live order at a real venue to see
what happens is not a test.

Before any real money: set a small ceiling, approve exactly one order manually
against Alpaca *paper* first, and confirm the fill and the reconciliation.

## Known consequence of Phase 1

Every backtest number produced before this change is void. The old engine filled
at the signal bar's close, annualised minute bars as daily, accumulated VWAP
across sessions, and let five strategies read the dataset's length. Results are
not merely optimistic — they describe an algorithm that could not be run.
Re-run anything that mattered.

## All six phases are done

The plan's sequence is complete. What exists: a backtest engine whose numbers
describe reachable trades, a single strategy core shared by backtest and live, a
schema and repository layer, an eleven-rule risk gate that records why it
refused, a runner that works a full session unattended, a UI to create and tune
and halt bots, and live orders that cannot leave the building without a person
saying so.

What has never happened: a single order against a real broker. Everything is
verified against a simulator. The list below is what stands between here and
that, and the Postgres item has been outstanding since Phase 2.
