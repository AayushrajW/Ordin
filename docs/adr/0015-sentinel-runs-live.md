# 0015 — The Sentinel dashboard runs the scenarios, and does not store them

## Context
Slice 8 renders the scenario registry on a page. The natural implementation stores each
run and displays the most recent one: cheap, fast, and what a monitoring dashboard
normally does.

It is also the failure the registry's own docstring warns about. A stored result can
show green from an hour ago — after the code changed, after the database was replaced,
after somebody broke the thing the scenario exists to catch. A check that cannot
currently fail manufactures confidence, and a dashboard is exactly where manufactured
confidence gets believed.

## Decision
**Every page load runs the scenarios against the live application** and renders what
happened, with the timestamp it finished at. Nothing is stored and nothing is cached.

Three consequences follow from that, all deliberate:

- It is a **POST** (`/sentinel/run`). The scenarios establish their own preconditions —
  pushing a fixture through the pipeline, redacting a specimen — so this writes, and a
  GET that writes is a lie to every cache between here and the browser.
- It **requires a session and the dev environment**. Scenarios exercise authorization
  boundaries by design; a diagnostic that runs privileged checks should not be reachable
  unauthenticated, and in a deployment it should not be a route at all.
- Scenario registration is **discovered**, not listed. Three places imported the scenario
  modules by name and the test's copy fell behind — slice 5b added four scenarios and the
  pytest suite kept running eleven. `load_scenarios()` walks `sentinel/scenarios_*.py`.

## Consequences
- The page takes a few seconds to load, because it is doing work. That is the honest
  cost of the number being current.
- An ERROR row is rendered as its own state, never folded into pass or fail. A scenario
  that raised proved nothing; showing it as a pass is how a dashboard lies, and showing
  it as a failure makes a broken scenario look like a broken system.
- The dev-environment restriction is a guard, not a security claim. Anyone with a
  session in a dev deployment can trigger it. It is not an authorization boundary and is
  not presented as one.
- Because the run is live, a judge can break something on purpose — comment out the
  disclosure check — reload, and watch a critical row go red. That is the point of the
  page, and it does not work against a stored report.
