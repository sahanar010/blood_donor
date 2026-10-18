import { useEffect, useRef, useState } from "react";
import { BASE, stored } from "./api";

/** Keeps a WebSocket open (auto-reconnect, 30 s heartbeat). Calls onEvent on every server event
 *  and on every (re)connect, because REST is the source of truth and missed events must be re-fetched. */
export function useRealtime(onEvent: () => void): boolean {
  const [live, setLive] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    const a = stored();
    if (!a) return;
    let ws: WebSocket | null = null, ping = 0, retry = 0, stop = false;
    const open = () => {
      ws = new WebSocket(`${BASE.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(a.token)}`);
      ws.onopen = () => {
        setLive(true); cb.current();
        ping = window.setInterval(() => ws?.readyState === 1 && ws.send("ping"), 30000);
      };
      ws.onmessage = (e) => { if (JSON.parse(e.data).type !== "pong") cb.current(); };
      ws.onclose = () => { setLive(false); clearInterval(ping); if (!stop) retry = window.setTimeout(open, 2000); };
    };
    open();
    return () => { stop = true; clearTimeout(retry); clearInterval(ping); ws?.close(); };
  }, []);
  return live;
}
