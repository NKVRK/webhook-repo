/**
 * formatDate.js
 * -------------
 * Converts an ISO-8601 UTC timestamp string into the display format
 * required by the task specification:
 *
 *   "1st April 2021 - 9:30 PM UTC"
 *
 * Uses the Intl API for locale-safe month names and avoids
 * third-party date libraries.
 */

/**
 * Return the English ordinal suffix for a given day number.
 * e.g. 1 → "st", 2 → "nd", 3 → "rd", 4-20 → "th", 21 → "st", …
 *
 * @param {number} day - Day of the month (1–31)
 * @returns {string} Ordinal suffix
 */
function getOrdinalSuffix(day) {
  if (day >= 11 && day <= 13) return "th"; // special cases: 11th, 12th, 13th
  const lastDigit = day % 10;
  if (lastDigit === 1) return "st";
  if (lastDigit === 2) return "nd";
  if (lastDigit === 3) return "rd";
  return "th";
}

/**
 * Full month names indexed 0–11.
 */
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * Format an ISO-8601 UTC timestamp into human-readable form.
 *
 * @param {string} isoString - e.g. "2026-03-01T14:30:00Z"
 * @returns {string}         - e.g. "1st March 2026 - 2:30 PM UTC"
 */
export function formatTimestamp(isoString) {
  const date = new Date(isoString);

  const day = date.getUTCDate();
  const month = MONTHS[date.getUTCMonth()];
  const year = date.getUTCFullYear();

  // 12-hour clock conversion
  let hours = date.getUTCHours();
  const minutes = date.getUTCMinutes().toString().padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12; // 0 → 12 for midnight

  return `${day}${getOrdinalSuffix(day)} ${month} ${year} - ${hours}:${minutes} ${ampm} UTC`;
}
