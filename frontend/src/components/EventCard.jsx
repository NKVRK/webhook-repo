/**
 * EventCard.jsx
 * -------------
 * Renders a single webhook event in the required display format:
 *
 *   PUSH:         "{author}" pushed to "{to_branch}" on {timestamp}
 *   PULL_REQUEST: "{author}" submitted a pull request from "{from_branch}" to "{to_branch}" on {timestamp}
 *   MERGE:        "{author}" merged branch "{from_branch}" to "{to_branch}" on {timestamp}
 *
 * Each action type gets a distinct colour badge for quick visual scanning.
 */

import { formatTimestamp } from "../utils/formatDate";

/* ── colour / label map per action type ── */
const ACTION_STYLES = {
  PUSH: {
    badge: "bg-green-100 text-green-800 border border-green-300",
    icon: "↑",
    accent: "border-l-green-500",
  },
  PULL_REQUEST: {
    badge: "bg-blue-100 text-blue-800 border border-blue-300",
    icon: "⇄",
    accent: "border-l-blue-500",
  },
  MERGE: {
    badge: "bg-purple-100 text-purple-800 border border-purple-300",
    icon: "⇢",
    accent: "border-l-purple-500",
  },
};

/**
 * Build the human-readable message for a given event.
 *
 * @param {Object} event - Event document from the API
 * @returns {JSX.Element}
 */
function buildMessage(event) {
  const time = formatTimestamp(event.timestamp);

  switch (event.action) {
    case "PUSH":
      return (
        <span>
          <strong>&quot;{event.author}&quot;</strong> pushed to{" "}
          <strong>&quot;{event.to_branch}&quot;</strong> on {time}
        </span>
      );

    case "PULL_REQUEST":
      return (
        <span>
          <strong>&quot;{event.author}&quot;</strong> submitted a pull request from{" "}
          <strong>&quot;{event.from_branch}&quot;</strong> to{" "}
          <strong>&quot;{event.to_branch}&quot;</strong> on {time}
        </span>
      );

    case "MERGE":
      return (
        <span>
          <strong>&quot;{event.author}&quot;</strong> merged branch{" "}
          <strong>&quot;{event.from_branch}&quot;</strong> to{" "}
          <strong>&quot;{event.to_branch}&quot;</strong> on {time}
        </span>
      );

    default:
      return <span>Unknown action: {event.action}</span>;
  }
}

export default function EventCard({ event }) {
  const style = ACTION_STYLES[event.action] || ACTION_STYLES.PUSH;

  return (
    <div
      className={`border-l-4 ${style.accent} bg-white rounded-lg shadow-sm
                  p-4 mb-3 transition-all duration-300 hover:shadow-md`}
    >
      {/* Top row: action badge + request ID */}
      <div className="flex items-center gap-2 mb-2">
        <span
          className={`inline-flex items-center gap-1 text-xs font-semibold
                      px-2.5 py-0.5 rounded-full ${style.badge}`}
        >
          <span>{style.icon}</span>
          {event.action.replace("_", " ")}
        </span>
        <span className="text-xs text-gray-400 ml-auto font-mono">
          #{event.request_id.substring(0, 8)}
        </span>
      </div>

      {/* Event message */}
      <p className="text-gray-700 text-sm leading-relaxed">
        {buildMessage(event)}
      </p>
    </div>
  );
}
