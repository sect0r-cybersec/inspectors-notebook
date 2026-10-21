# S6 manual checklist: processing queue

Automated coverage: `uv run pytest` (newest-first labelling, the 200-job cap, replaced and cancelled jobs, merged page captures, refresh coalescing, and the exit test: a 500-query burst keeps its order through the real pipe, capture never waits for labelling, and capped events stay in the timeline marked Not labelled). Labelling is tested with a stand-in model; the real one arrives in S7.

## In the real panel

- [ ] Run a long KQL session in the lab, or paste a burst of queries quickly: the panel keeps up, scrolling and typing a note stay smooth, and the newest query is at the top.
- [ ] Reload a Defender incident page several times quickly: one page event appears, not one per reload. Two reloads more than 2 s apart are two events.
- [ ] An incident page whose title settles after loading shows the final title, also after stopping and reopening the case.
- [ ] Closing the panel straight after a burst closes Inspector within a few seconds.

## Measured on the development machine (21 October 2026)

A probe sent 1,000 events (500 queries with results) through the pipe to the running panel while timing the panel's UI thread with `WM_NULL`:

| Build | Time for the panel to take in the burst | Slowest UI thread answer |
| --- | --- | --- |
| Before S6 (refresh per event) | 60.0 s | 16 ms |
| S6 (coalesced refresh) | 2.5 s | 4 ms |
