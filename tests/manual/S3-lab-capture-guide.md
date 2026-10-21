# S3 lab capture guide: filling the console parser gaps

Sections 1 and 2 are done: the Defender XDR and Sentinel query rules in `extension/src/parsers/` were written from lab captures on 21 October 2026, with sanitised fixtures in `extension/tests/fixtures/`. Still open: section 3, incident and alert URLs, because the lab had no incidents to capture. Until then incident IDs are not read. Re-run sections 1 and 2 if a console update breaks query capture.

Use the lab tenant only. Never capture from a client tenant.

## 1. Advanced hunting (Defender XDR)

1. Open advanced hunting at `security.microsoft.com` with DevTools open on the Network tab (Fetch/XHR filter).
2. Run a short query that returns rows, for example `DeviceInfo | take 3`.
3. Find the request that carries the KQL. Note:
   - its URL and method
   - where the query text sits in the request body (the JSON path)
   - where the column names and rows sit in the response
4. Run a query that returns no rows, and one that fails (a typo), and note how both responses look.
5. Save the three requests as a HAR (right-click in the Network list, "Save all as HAR"). HAR files can contain session tokens, so search the file for `Authorization`, `Cookie` and `Bearer` and remove them before saving it in the repo.

## 2. Logs queries (Sentinel in the Azure portal)

Repeat section 1 in Sentinel's Logs blade at `portal.azure.com`. Also note:

- whether the query editor runs in a frame on another origin (DevTools, Sources tab, frames list); if it does, that origin needs adding to the extension's permissions
- which request carries the query, and from which frame

## 3. Incident and alert URLs (still needed)

If the lab has no incidents, raise one: on an onboarded lab device, run Microsoft's detection test from the Defender portal (Settings, Endpoints, Onboarding, "Run a detection test"), or run a Caldera ability that Defender alerts on.

Then copy the address bar URL for each of these, and note which part is the ID:

- a Defender XDR incident page, and its alerts tab
- a Defender XDR alert page
- a Sentinel incident in the Azure portal
- a Sentinel incident in the Defender portal (unified)

## 4. Alert page entities

On a lab alert with several entity types (device, user, IP, file, hash), save the page in DevTools (Elements tab, right-click the `html` node, Copy outerHTML) and note where the entity panel sits. This is for seeding a case from the alert page (FR-5) in S4.

## Where to put it

Put raw captures in `.lab-captures/` (gitignored). Sanitised fixtures are extracted from them into `extension/tests/fixtures/<console>/`, with GUIDs and lab resource names replaced.

## The 20-query check (S3's exit test)

The query rules exist, so this can run now:

1. Close Inspector's Notebook, then run `uv run python extension/tests/fake_companion.py --recording` in a terminal. It stands in for the app and prints every capture as a JSON line.
2. In the lab, run 20 queries across both consoles: short and long, multi-line, with comments, with zero results, and one that fails.
3. Check every query appears once (`"kind": "query"`) with exactly the text you ran, followed by its result (`"kind": "result"`) with the right row count. No misses, no wrong text.
