import assert from "node:assert/strict";
import { test } from "node:test";
import "../../src/incidents.js";

const { recordFromUrl } = globalThis.InspectorIncidents;

// URL shapes are illustrative of common platforms; IDs are made up.
test("record pages are recognised across platforms", () => {
  const cases = [
    ["https://security.microsoft.com/incidents/4821?tid=x", "incident", "4821"],
    ["https://security.microsoft.com/incidents/4821/overview", "incident", "4821"],
    ["https://security.microsoft.com/incident2/4821/overview?tid=x", "incident", "4821"],
    ["https://security.microsoft.com/alerts/da638123456789012345_-1234567890?tid=x", "alert", "da638123456789012345_-1234567890"],
    ["https://siem.example.com/app/cases/123", "case", "123"],
    ["https://soc.example.com/tickets/INC0012345", "ticket", "INC0012345"],
    ["https://edr.example.com/activity/detections/ldt:abc123:456", "detection", "ldt:abc123:456"],
    ["https://tenant.service-now.example.com/incident.do?sys_id=9d385017c611228701d22104cc95c371", "incident", "9d385017c611228701d22104cc95c371"],
    ["https://jira.example.com/browse/SOC-123", "issue", "SOC-123"],
    ["https://siem.example.com/console/offenses?id=4421", "offense", "4421"],
    ["https://app.example.com/view?incidentId=7781", "incident", "7781"],
  ];
  for (const [url, kind, incidentId] of cases) {
    assert.deepEqual(recordFromUrl(url), { kind, incidentId }, url);
  }
});

test("Azure portal fragment routes are decoded", () => {
  const url =
    "https://portal.azure.com/#view/Microsoft_Azure_Security_Insights/IncidentPage.ReactView/incidentId/" +
    "%2Fsubscriptions%2Fs%2FresourceGroups%2Fr%2Fproviders%2FMicrosoft.OperationalInsights%2Fworkspaces%2Fw" +
    "%2Fproviders%2FMicrosoft.SecurityInsights%2FIncidents%2F7f3e2a10-1111-4222-8333-944455556666";
  assert.deepEqual(recordFromUrl(url), { kind: "incident", incidentId: "7f3e2a10-1111-4222-8333-944455556666" });
});

test("list pages and other pages are not records", () => {
  for (const url of [
    "https://security.microsoft.com/incidents?tid=00000000-0000-0000-0000-000000000001",
    "https://security.microsoft.com/alerts?tid=x",
    "https://security.microsoft.com/v2/advanced-hunting",
    "https://soc.example.com/tickets/new",
    "https://soc.example.com/tickets/queue",
    "https://siem.example.com/app/cases/",
    "https://siem.example.com/app/cases/overview",
    "https://docs.example.com/how-incidents-work",
    "https://example.com/?id=12345",
    "https://jira.example.com/browse/soc-123",
    "not a url",
  ]) {
    assert.equal(recordFromUrl(url), null, url);
  }
});
