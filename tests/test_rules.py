from inspectors_notebook.rules import (
    HIDE,
    KEEP,
    REVIEW,
    CaseContext,
    decide,
    matching_entities,
    page_key,
    query_key,
    suggested_entities,
)


def page(url, **extra):
    return {"kind": "page_visit", "url": url, "title": "Page", **extra}


def query(text, **extra):
    return {"kind": "query", "query": text, **extra}


def result(rows, columns=("DeviceName", "RemoteIP"), **extra):
    return {"kind": "result", "rowCount": len(rows), "columns": list(columns), "rows": rows, **extra}


CASE = CaseContext(entities=["HOST-12", "203.0.113.7"], tenant="tenant-a")


def test_console_events_are_kept_during_a_case():  # FR-17
    assert decide(page("https://security.microsoft.com/v2/advanced-hunting"), CaseContext()).disposition == KEEP
    assert decide(query("DeviceInfo | take 1"), CaseContext()).reason == "console"


def test_enrichment_lookups_on_an_added_site_are_kept_and_matched_by_url():  # FR-11, FR-17
    # VirusTotal and AbuseIPDB put the value looked up in the URL; the analyst adds those sites.
    sha = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"
    case = CaseContext(entities=["203.0.113.7", sha, "evil.example.com"])
    for url in (
        "https://www.virustotal.com/gui/ip-address/203.0.113.7",
        f"https://www.virustotal.com/gui/file/{sha}/detection",
        "https://www.virustotal.com/gui/domain/evil.example.com/relations",
        "https://www.abuseipdb.com/check/203.0.113.7",
    ):
        d = decide(page(url, console="www.virustotal.com"), case)
        assert (d.disposition, d.reason) == (KEEP, "entity"), url
    other = decide(page("https://www.abuseipdb.com/check/192.0.2.50", console="www.abuseipdb.com"), case)
    assert (other.disposition, other.reason) == (KEEP, "console")


def test_zero_result_queries_are_kept_as_negative_findings():  # FR-20
    d = decide(result([]), CaseContext())
    assert (d.disposition, d.reason) == (KEEP, "negative_finding")


def test_entity_match_keeps_and_says_which():  # FR-19
    d = decide(result([["HOST-12", "10.1.1.1"]]), CASE)
    assert (d.disposition, d.reason, d.matched) == (KEEP, "entity", ("HOST-12",))


def test_entity_match_is_whole_value_and_case_insensitive():
    assert matching_entities(query('where RemoteIP == "203.0.113.70"'), ["203.0.113.7"]) == []
    assert matching_entities(query("where DeviceName == 'host-12'"), ["HOST-12"]) == ["HOST-12"]
    assert matching_entities(query("HOST-123"), ["HOST-12"]) == []
    assert matching_entities(page("https://x/machines/dc01.contoso.local"), ["dc01"]) == ["dc01"]


def test_entities_are_found_in_titles_errors_and_extracted_entities():
    assert matching_entities(page("https://x/", title="HOST-12 overview"), ["HOST-12"]) == ["HOST-12"]
    assert matching_entities({"kind": "result", "error": "no table HOST-12"}, ["HOST-12"]) == ["HOST-12"]
    event = {"kind": "result", "entities": [{"type": "ipv4", "value": "203.0.113.7"}]}
    assert matching_entities(event, ["203.0.113.7"]) == ["203.0.113.7"]


def test_entity_match_beats_every_hide_rule():  # FR-19 cannot be overridden
    event = page("https://x/devices/HOST-12", navigationOnly=True)
    ctx = CaseContext(entities=["HOST-12"], kept_pages={page_key(event)})
    assert decide(event, ctx, idle=True).disposition == KEEP


def test_idle_navigation_and_duplicates_are_hidden():  # FR-18
    idle = decide(query("x"), CaseContext(), idle=True)
    assert (idle.disposition, idle.reason) == (HIDE, "idle")
    assert decide(page("https://x/incidents", navigationOnly=True), CaseContext()).reason == "navigation"
    seen = page("https://x/hunting")
    assert decide(seen, CaseContext(kept_pages={page_key(seen)})).reason == "duplicate"
    q = query("DeviceInfo\n| take 1", rowCount=None)
    assert decide(query("DeviceInfo | take 1"), CaseContext(kept_queries={query_key(q)})).reason == "duplicate"


def test_other_tenant_goes_to_review_with_a_flag():  # FR-14
    d = decide(query("x", tenant="tenant-b"), CASE)
    assert (d.disposition, d.reason, d.flags) == (REVIEW, "other_tenant", ("other_tenant",))
    kept = decide(query("HOST-12", tenant="tenant-b"), CASE)
    assert (kept.disposition, kept.flags) == (KEEP, ("other_tenant",))
    assert decide(query("x", tenant="tenant-a"), CASE).disposition == KEEP
    assert decide(query("x"), CASE).disposition == KEEP  # no tenant known: not flagged


def test_analyst_decisions_win():  # FR-24
    assert decide(result([["HOST-12"]]), CASE, manual=HIDE).disposition == HIDE
    assert decide(query("x"), CaseContext(), idle=True, manual=KEEP).disposition == KEEP
    assert decide(query("x"), CaseContext(), manual="nonsense").disposition == KEEP


def test_suggested_entities_come_from_kept_events_only():  # FR-21
    events = [
        {"kind": "result", "entities": [{"type": "ipv4", "value": "203.0.113.7"}, {"type": "file", "value": "evil.exe"}]},
        {"kind": "result", "entities": [{"type": "domain", "value": "hidden.example.com"}]},
    ]
    decisions = [decide(events[0], CaseContext()), decide(events[1], CaseContext(), idle=True)]
    assert suggested_entities(events, decisions, ["203.0.113.7"]) == ["evil.exe"]


def test_suggestions_put_pivots_before_hashes():
    event = {"kind": "result", "entities": [
        {"type": "sha1", "value": "0" * 40},
        {"type": "sha256", "value": "a" * 64},
        {"type": "file", "value": "ntoskrnl.exe"},
        {"type": "ipv4", "value": "203.0.113.7"},
        {"type": "domain", "value": "evil.example.com"},
    ]}
    assert suggested_entities([event], [decide(event, CaseContext())], []) == [
        "203.0.113.7", "evil.example.com", "ntoskrnl.exe", "a" * 64, "0" * 40,
    ]


def test_the_same_query_against_another_tenant_is_not_a_duplicate():
    kept = query("DeviceInfo | take 1", tenant="tenant-a")
    ctx = CaseContext(tenant="tenant-a", kept_queries={query_key(kept)})
    assert decide(query("DeviceInfo | take 1", tenant="tenant-a"), ctx).reason == "duplicate"
    assert decide(query("DeviceInfo | take 1", tenant="tenant-b"), ctx).reason == "other_tenant"


def test_entities_in_notes_count():
    assert matching_entities({"kind": "note", "text": "HOST-12 beacons every minute"}, ["HOST-12"]) == ["HOST-12"]
