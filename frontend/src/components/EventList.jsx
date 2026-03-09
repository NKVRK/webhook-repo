/**
 * EventList.jsx
 * -------------
 * Core polling component that:
 *   1. Fetches events from the last 15 seconds on mount (GET /webhook/events/all)
 *   2. Every 15 seconds, replaces the displayed events with the latest
 *      15-second window from the server (GET /webhook/events/all)
 *   3. Only shows events that occurred within the last 15 seconds,
 *      so the UI always reflects the most recent activity.
 *
 * Handles error states gracefully and shows a visual countdown
 * until the next poll cycle.
 */

import { useCallback, useEffect, useState } from "react";
import EventCard from "./EventCard";

/** Polling interval in milliseconds (15 seconds per spec) */
const POLL_INTERVAL_MS = 15_000;

export default function EventList() {
  const [events, setEvents] = useState([]);           // currently displayed events
  const [loading, setLoading] = useState(true);        // initial load spinner
  const [error, setError] = useState(null);            // error message (if any)
  const [lastPoll, setLastPoll] = useState(null);      // Date of last successful poll
  const [countdown, setCountdown] = useState(POLL_INTERVAL_MS / 1000);

  /**
   * Fetch the latest 15-second window of events from the server
   * and replace the current displayed list entirely.
   */
  const fetchLatestEvents = useCallback(async () => {
    try {
      const res = await fetch("/webhook/events/all");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      setEvents(data.events);
      setError(null);
    } catch (err) {
      console.error("Polling error:", err);
      setError("Connection lost. Will retry on next poll cycle…");
    } finally {
      setLastPoll(new Date());
      setCountdown(POLL_INTERVAL_MS / 1000);
    }
  }, []);

  /* ── initial fetch: load events from the last 15 seconds ── */
  useEffect(() => {
    const init = async () => {
      await fetchLatestEvents();
      setLoading(false);
    };
    init();
  }, [fetchLatestEvents]);

  /* ── polling: replace events with latest 15-second window ── */
  useEffect(() => {
    const intervalId = setInterval(fetchLatestEvents, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchLatestEvents]);

  /* ── countdown timer (ticks every 1 s) ── */
  useEffect(() => {
    const tick = setInterval(() => {
      setCountdown((c) => (c <= 1 ? POLL_INTERVAL_MS / 1000 : c - 1));
    }, 1000);
    return () => clearInterval(tick);
  }, []);

  /* ── render ── */
  return (
    <div>
      {/* Polling status bar */}
      <div className="flex items-center justify-between text-xs text-gray-500 mb-4">
        <span>
          {lastPoll
            ? `Last updated: ${lastPoll.toLocaleTimeString()}`
            : "Loading…"}
        </span>
        <span className="flex items-center gap-1">
          <span className="relative flex h-2 w-2">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${error ? "bg-red-400" : "bg-green-400"}`}></span>
            <span className={`relative inline-flex rounded-full h-2 w-2 ${error ? "bg-red-500" : "bg-green-500"}`}></span>
          </span>
          Next refresh in {countdown}s
        </span>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 px-4 py-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
          {error}
        </div>
      )}

      {/* Content area */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-800"></div>
        </div>
      ) : events.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <p className="text-4xl mb-3">📭</p>
          <p className="text-lg font-medium">No events yet</p>
          <p className="text-sm mt-1">
            Push, open a PR, or merge on&nbsp;
            <span className="font-semibold">action-repo</span> to see events here.
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          {events.map((evt) => (
            <EventCard key={evt._id} event={evt} />
          ))}
        </div>
      )}
    </div>
  );
}
