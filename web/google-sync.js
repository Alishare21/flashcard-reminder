import { GOOGLE_CLIENT_ID } from "./google-config.js";

export const GOOGLE_SCOPES = [
  "https://www.googleapis.com/auth/calendar.events.readonly",
  "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
  "https://www.googleapis.com/auth/tasks.readonly",
];

function localDay(dateText) {
  return new Date(`${dateText.slice(0, 10)}T00:00:00`);
}

export function normalizeCalendarEvent(event, calendarName, now = new Date()) {
  if (!event || event.status === "cancelled" || !event.start) return null;
  const allDay = Boolean(event.start.date);
  const start = allDay ? localDay(event.start.date) : new Date(event.start.dateTime);
  const end = event.end?.date
    ? localDay(event.end.date) : event.end?.dateTime ? new Date(event.end.dateTime) : start;
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= now) return null;
  return {
    id: `event:${event.id || event.iCalUID || start.toISOString()}`,
    name: String(event.summary || "Untitled event").slice(0, 120),
    start,
    allDay,
    source: calendarName || "Google Calendar",
    kind: "event",
    detail: [event.location, event.description].filter(Boolean).join(" · ").slice(0, 300),
    url: typeof event.htmlLink === "string" && event.htmlLink.startsWith("https://calendar.google.com/")
      ? event.htmlLink : "https://calendar.google.com/calendar/u/0/r",
  };
}

export function normalizeGoogleTask(task, listName) {
  if (!task || task.deleted || task.status === "completed") return null;
  const start = task.due ? localDay(task.due) : null;
  if (start && Number.isNaN(start.getTime())) return null;
  return {
    id: `task:${task.id || task.title || "untitled"}`,
    name: String(task.title || "Untitled task").slice(0, 120),
    start,
    allDay: true,
    source: listName || "Google Tasks",
    kind: "task",
    detail: String(task.notes || "").slice(0, 300),
    url: "https://tasks.google.com/",
  };
}

async function googleGet(url, token, fetcher) {
  const response = await fetcher(url, { headers: { Authorization: `Bearer ${token}` } });
  if (response.status === 401) throw new Error("Google access expired. Connect again.");
  if (!response.ok) throw new Error("Google could not load this calendar or task list. Check API access in Google Cloud.");
  return response.json();
}

async function paged(url, token, fetcher) {
  const items = [];
  let next = url;
  for (let page = 0; next && page < 20; page += 1) {
    const data = await googleGet(next, token, fetcher);
    items.push(...(Array.isArray(data.items) ? data.items : []));
    if (!data.nextPageToken) return items;
    const following = new URL(url);
    following.searchParams.set("pageToken", data.nextPageToken);
    next = following.toString();
  }
  throw new Error("Google returned too many pages. Narrow the calendar selection.");
}

export async function fetchGoogleItems(token, now = new Date(), fetcher = fetch) {
  if (!token) throw new Error("Connect Google before syncing.");
  const from = now.toISOString();
  const until = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000).toISOString();
  const calendars = await paged(
    "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=250", token, fetcher,
  );
  const taskLists = await paged(
    "https://tasks.googleapis.com/tasks/v1/users/@me/lists?maxResults=100", token, fetcher,
  );
  const results = [];
  for (const calendar of calendars) {
    if (!calendar.id || calendar.accessRole === "freeBusyReader") continue;
    const url = new URL(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendar.id)}/events`);
    url.searchParams.set("timeMin", from);
    url.searchParams.set("timeMax", until);
    url.searchParams.set("singleEvents", "true");
    url.searchParams.set("orderBy", "startTime");
    url.searchParams.set("maxResults", "2500");
    const events = await paged(url.toString(), token, fetcher);
    events.forEach((event) => {
      const item = normalizeCalendarEvent(event, calendar.summary, now);
      if (item) results.push(item);
    });
  }
  for (const list of taskLists) {
    if (!list.id) continue;
    const url = new URL(`https://tasks.googleapis.com/tasks/v1/lists/${encodeURIComponent(list.id)}/tasks`);
    url.searchParams.set("maxResults", "100");
    url.searchParams.set("showCompleted", "false");
    url.searchParams.set("showDeleted", "false");
    const tasks = await paged(url.toString(), token, fetcher);
    tasks.forEach((task) => {
      const item = normalizeGoogleTask(task, list.title);
      if (item) results.push(item);
    });
  }
  return results.sort((a, b) => (a.start?.getTime() ?? Infinity) - (b.start?.getTime() ?? Infinity));
}

let gisLoading;
function loadGoogleIdentity() {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (!gisLoading) gisLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = resolve;
    script.onerror = () => {
      gisLoading = null;
      script.remove();
      reject(new Error("Google sign-in could not load."));
    };
    document.head.append(script);
  });
  return gisLoading;
}

export function createGoogleConnector(onItems, onStatus) {
  let accessToken = null;
  let client = null;
  let syncing = false;
  const configured = /^[\w-]+\.apps\.googleusercontent\.com$/.test(GOOGLE_CLIENT_ID);

  async function refresh() {
    if (!accessToken || syncing) return;
    syncing = true;
    onStatus("Syncing your Google Calendar and Tasks…");
    try {
      const items = await fetchGoogleItems(accessToken);
      onItems(items);
      onStatus(`Connected · ${items.length} Google item${items.length === 1 ? "" : "s"} loaded for the next 30 days.`);
    } catch (error) {
      if (String(error.message).includes("expired")) {
        accessToken = null;
        onItems([]);
      }
      onStatus(error.message);
    } finally { syncing = false; }
  }

  async function connect() {
    if (!configured) {
      onStatus("Google connection is awaiting its Web OAuth client setup.");
      return;
    }
    try {
      await loadGoogleIdentity();
      if (!client) client = window.google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: GOOGLE_SCOPES.join(" "),
        callback: async (response) => {
          if (response.error || !response.access_token) {
            onStatus("Google connection was not approved.");
            return;
          }
          const granted = new Set(String(response.scope || "").split(/\s+/));
          if (!GOOGLE_SCOPES.every((scope) => granted.has(scope))) {
            onStatus("Calendar and Tasks read access are both needed to show Google items.");
            return;
          }
          accessToken = response.access_token;
          await refresh();
        },
      });
      client.requestAccessToken({ prompt: accessToken ? "" : "consent" });
    } catch (error) { onStatus(error.message || "Google connection failed."); }
  }

  function disconnect() {
    if (accessToken && window.google?.accounts?.oauth2) {
      window.google.accounts.oauth2.revoke(accessToken, () => {});
    }
    accessToken = null;
    onItems([]);
    onStatus("Disconnected. Google items were cleared from this page.");
  }

  return { configured, connected: () => Boolean(accessToken), connect, refresh: () => accessToken ? refresh() : connect(), disconnect };
}
