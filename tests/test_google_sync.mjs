import assert from "node:assert/strict";
import test from "node:test";
import { fetchGoogleItems, normalizeCalendarEvent, normalizeGoogleTask } from "../web/google-sync.js";

test("calendar events keep dates and omit cancelled or ended entries", () => {
  const now = new Date("2026-10-09T00:00:00Z");
  const event = {
    id: "meeting", summary: "Project review",
    start: { dateTime: "2026-10-10T10:00:00Z" },
    end: { dateTime: "2026-10-10T11:00:00Z" },
    htmlLink: "https://calendar.google.com/calendar/event?eid=meeting",
  };
  const result = normalizeCalendarEvent(event, "Work", now);
  assert.equal(result.name, "Project review");
  assert.equal(result.source, "Work");
  assert.equal(result.start.toISOString(), "2026-10-10T10:00:00.000Z");
  assert.equal(normalizeCalendarEvent({ ...event, status: "cancelled" }, "Work", now), null);
  assert.equal(normalizeCalendarEvent({ ...event, end: { dateTime: "2026-10-08T11:00:00Z" } }, "Work", now), null);
  const allDay = normalizeCalendarEvent({
    id: "holiday", summary: "Holiday", start: { date: "2026-10-10" }, end: { date: "2026-10-11" },
  }, "Personal", now);
  assert.equal(allDay.allDay, true);
  assert.equal(allDay.start.getDate(), 10);
});

test("tasks include undated items and omit completed items", () => {
  const task = normalizeGoogleTask({ id: "t1", title: "Revise lesson", due: "2026-10-10T00:00:00.000Z" }, "Study");
  assert.equal(task.name, "Revise lesson");
  assert.equal(task.source, "Study");
  assert.equal(task.start.getFullYear(), 2026);
  assert.equal(normalizeGoogleTask({ id: "t2", title: "Someday" }, "Study").start, null);
  assert.equal(normalizeGoogleTask({ id: "t3", status: "completed" }, "Study"), null);
});

test("sync reads separate calendars and task lists with a memory-only bearer token", async () => {
  const seen = [];
  const mockFetch = async (url, options) => {
    seen.push({ url, authorization: options.headers.Authorization });
    const path = new URL(url).pathname;
    let items;
    if (path.endsWith("/calendarList")) items = [{ id: "primary", summary: "Personal" }];
    else if (path.endsWith("/users/@me/lists")) items = [{ id: "list-1", title: "Tasks" }];
    else if (path.endsWith("/events")) items = [{
      id: "meeting", summary: "Appointment", start: { dateTime: "2026-10-10T10:00:00Z" },
      end: { dateTime: "2026-10-10T11:00:00Z" },
    }];
    else items = [{ id: "task-1", title: "Homework", due: "2026-10-11T00:00:00.000Z" }];
    return { ok: true, json: async () => ({ items }) };
  };
  const items = await fetchGoogleItems("test-token", new Date("2026-10-09T00:00:00Z"), mockFetch);
  assert.deepEqual(items.map((item) => item.name), ["Appointment", "Homework"]);
  assert.equal(seen.length, 4);
  assert.ok(seen.every((call) => call.authorization === "Bearer test-token"));
});

test("sync rejects missing tokens before contacting Google", async () => {
  await assert.rejects(fetchGoogleItems("", new Date("2026-10-09T00:00:00Z"), () => {
    throw new Error("request should not run");
  }), /Connect Google/);
});
