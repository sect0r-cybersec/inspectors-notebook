"use strict";

// Recognises incident, alert, case and ticket pages on any site from the URL alone
// (FR-2), so start detection works without per-platform rules. Most platforms put the
// record in the URL: /incidents/4821, /alerts/da638..., /cases/123, ServiceNow's
// incident.do?sys_id=..., Jira's /browse/SOC-123, or the same inside a #fragment route.
// A record word followed by something that looks like an ID is a record page; a record
// word on its own (/incidents, /alerts) is a list page and is not.
(() => {
  const RECORD_WORD = /^(incident|alert|case|ticket|detection|investigation|offense|issue)s?\d*(\.do)?$/i;
  const NOT_AN_ID = /^(list|queue|new|create|search|overview|all|open|closed|mine|dashboard)$/i;
  const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const JIRA_KEY = /^[A-Z][A-Z0-9]+-\d+$/;
  const ID_PARAMS = ["incidentid", "alertid", "caseid", "ticketid", "detectionid", "offenseid", "sys_id"];

  function looksLikeId(segment) {
    if (!segment || NOT_AN_ID.test(segment)) return false;
    if (GUID.test(segment) || /^\d{2,}$/.test(segment)) return true;
    // Mixed IDs such as INC0012345, da638123456789 or ldt:abc:123: long enough and with a digit.
    return segment.length >= 4 && /\d/.test(segment) && /^[\w:.-]+$/.test(segment);
  }

  function kindOf(word) {
    return word.toLowerCase().replace(/\.do$/, "").replace(/\d+$/, "").replace(/s$/, "");
  }

  function segments(text) {
    return text
      .split(/[/?&=]/)
      .map((s) => {
        try {
          return decodeURIComponent(s);
        } catch {
          return s;
        }
      })
      .filter(Boolean);
  }

  function fromSegments(parts) {
    for (let i = 0; i < parts.length - 1; i++) {
      if (RECORD_WORD.test(parts[i]) && looksLikeId(parts[i + 1])) {
        return { kind: kindOf(parts[i]), incidentId: parts[i + 1] };
      }
    }
    for (let i = 0; i < parts.length - 1; i++) {
      if (parts[i].toLowerCase() === "browse" && JIRA_KEY.test(parts[i + 1])) {
        return { kind: "issue", incidentId: parts[i + 1] };
      }
    }
    return null;
  }

  function recordFromUrl(url) {
    let u;
    try {
      u = new URL(url);
    } catch {
      return null;
    }
    // Fragment routes are decoded first: Azure portal links encode the record's path.
    const found = fromSegments(segments(decodeURIComponentSafe(u.hash.slice(1)))) ?? fromSegments(segments(u.pathname));
    if (found) return found;
    const pathWords = segments(u.pathname).filter((s) => RECORD_WORD.test(s));
    for (const [key, value] of u.searchParams) {
      const k = key.toLowerCase();
      if (ID_PARAMS.includes(k) && looksLikeId(value)) {
        const word = pathWords[0] ?? k.replace(/(id|_id)$/, "");
        return { kind: word === "sys" ? "record" : kindOf(word), incidentId: value };
      }
      if (k === "id" && pathWords.length && looksLikeId(value)) {
        return { kind: kindOf(pathWords[0]), incidentId: value };
      }
    }
    return null;
  }

  function decodeURIComponentSafe(text) {
    try {
      return decodeURIComponent(text);
    } catch {
      return text;
    }
  }

  globalThis.InspectorIncidents = { recordFromUrl };
})();
