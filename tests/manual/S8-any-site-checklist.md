# S8 manual checklist: capture on any site

Automated coverage: `cd extension && npm run test:unit` (generic query and result reading, and the Defender and Sentinel lab captures read the same through generic capture as through their console parsers), `npm test` (an added site in Chrome and Edge: the hook is registered, a search request is captured with its results through the real relay, and removing the site removes the hook), and `uv run pytest` (ticket triggers). This list covers real consoles, which the tests have never seen.

For each console you can reach in a lab (Elastic/Kibana, LogScale, Splunk, Chronicle, a ticketing system), add it with **Listen on this site**, reload its tab, start a case and run three searches: one with results, one with none, one with a syntax error.

| Console | Query text right | Row count right | Error shown | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

- [ ] A search that returns results appears in the timeline with the exact query text and a summary line.
- [ ] A search with no results is kept as a negative finding.
- [ ] A failed search shows the console's error.
- [ ] Page loads, autocomplete and saved-search lists do **not** appear as queries.
- [ ] Firefox: the same, after adding the site and reloading the tab (runtime registration is untested in Firefox).
- [ ] Removing the site from the popup stops capture after the tab reloads.

## Ticket triggers

- [ ] Open an incident in Defender, then within a few seconds open a ticket for it in your ticketing system (added as a site): Inspector suggests a case for the incident at once.
- [ ] Opening a second incident in the same console is not a ticket: the suggestion waits for the dwell and a pivot, as before.

Where generic capture misreads a console, save a HAR of one search as in `tests/manual/S3-lab-capture-guide.md`; a console parser can then read it exactly.
