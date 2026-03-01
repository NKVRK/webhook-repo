/**
 * EventList.jsx
 * -------------
 * Core polling component that:
 *   1. Fetches ALL events on mount  (GET /webhook/events/all)
 *   2. Every 15 seconds, fetches only NEW events created after the
 *      most-recent timestamp  (GET /webhook/events?after=<ts>)
 *   3. Prepends new events to the list so the UI always shows
 *      the latest activity first, with no duplicates.
 */

import { useEffect, useRef, useState } from "react";
import EventCard from "./EventCard";

/** Polling interval in milliseconds */
const POLL_INTERVAL_MS = 15_000;

export default function EventList() {
  const [events, setEvents] = useState([]);          // all displayed events
  const [loading, setLoading] = useState(true);       // initial load spinner
  const [lastPoll, setLastPoll] = useState(null);     // Date of last successful poll
  const [countdown, setCountdown] = useState(POLL_INTERVAL_MS / 1000);
  const latestTimestamp = useRef(null);                // newest event ts (for `after` param)

  /* ── helper: update latest timestamp tracker ── */
  const updateLatestTs = (eventList) => {
    if (eventList.length > 0) {
      // Events are sorted newest-first from the API
      latestTimestamp.current = eventList[0].timestamp;
    }
  };

  /* ── initial fetch: load every stored event ── */
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const res = await fetch("/webhook/events/all");
        const data = await res.json();
        setEvents(data.events);
        updateLatestTs(data.events);
      } catch (err) {
        console.error("Failed to fetch initial events:", err);
      } finally {
        setLoading(false);
        setLastPoll(new Date());
      }
    };

    fetchAll();
  }, []);

  /* ── incremental polling: only new events after latest ts ── */
  useEffect(() => {
    const poll = async () => {
      try {
        const url = latestTimestamp.current
          ? `/webhook/events?after=${encodeURIComponent(latestTimestamp.current)}`
          : "/webhook/events/all";

        const res = await fetch(url);
        const data = await res.json();

        if (data.events.length > 0) {
          setEvents((prev) => {
            // De-duplicate by _id just in case
            const existingIds = new Set(prev.map((e) => e._id));
            const fresh = data.events.filter((e) => !existingIds.has(e._id));
            return [...fresh, ...prev];
          });
          updateLatestTs(data.events);
        }
      } catch (err) {
        console.error("Polling error:", err);
      } finally {
        setLastPoll(new Date());
        setCountdown(POLL_INTERVAL_MS / 1000); // reset countdown
      }
    };

    const intervalId = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, []);

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
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
          </span>
          Next refresh in {countdown}s
        </span>
      </div>

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
