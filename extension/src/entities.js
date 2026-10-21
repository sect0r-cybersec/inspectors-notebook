"use strict";

// Pulls entity-like values out of text (FR-21 suggestions, FR-19 matching later).
// Types run in order and each match is masked before the next type runs, so a URL's
// host is not also reported as a domain and powershell.exe is a file, not a domain.
(() => {
  // Domains are only reported for these TLDs: free text is full of dotted words
  // (j.smith, Table.Column) that a generic pattern would report as domains.
  const TLDS = new Set(
    ("com net org info biz io co ai app dev xyz top site online club shop live tech cloud " +
      "uk de fr nl ru cn jp br in au ca us eu ch se no it es pl ua kz ir kp tk ml ga cf gq " +
      "cc me tv ws su pw onion local lan corp internal").split(" "),
  );

  const TYPES = [
    ["url", /\bhttps?:\/\/[^\s"'<>()[\]{}]+/gi],
    ["email", /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}\b/g],
    ["ipv4", /\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b/g],
    ["sha256", /\b[a-fA-F0-9]{64}\b/g],
    ["sha1", /\b[a-fA-F0-9]{40}\b/g],
    ["md5", /\b[a-fA-F0-9]{32}\b/g],
    ["file", /\b[\w.-]+\.(?:exe|dll|ps1|psm1|bat|cmd|vbs|vbe|js|jse|hta|msi|scr|sys|lnk|iso|zip)\b/gi],
    ["domain", /\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,63})\b/gi],
  ];

  const LOWERCASE = new Set(["sha256", "sha1", "md5", "domain", "email"]);

  function extractEntities(text) {
    if (typeof text !== "string" || !text) return [];
    let remaining = text;
    const found = [];
    const seen = new Set();
    for (const [type, pattern] of TYPES) {
      remaining = remaining.replace(pattern, (match, tld) => {
        if (type === "domain" && !TLDS.has(tld.toLowerCase())) return match;
        let value = type === "url" ? match.replace(/[.,;:]+$/, "") : match;
        if (LOWERCASE.has(type)) value = value.toLowerCase();
        const key = `${type}:${value}`;
        if (!seen.has(key)) {
          seen.add(key);
          found.push({ type, value });
        }
        return " ".repeat(match.length);
      });
    }
    return found;
  }

  globalThis.InspectorEntities = { extractEntities };
})();
