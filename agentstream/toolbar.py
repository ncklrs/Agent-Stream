"""AgentStream Mac Toolbar — menu bar app with notifications and web panel.

macOS menu bar companion for AgentStream that:
- Watches active Claude/Codex sessions in the background
- Sends native macOS notifications for key events
- Provides a dropdown with live session info
- Opens an expandable web panel for detailed event viewing

Usage:
    agentstream --toolbar              # Menu bar with watch mode
    agentstream --toolbar --demo       # Menu bar with demo data
    agentstream-toolbar                # Direct entry point

Requires: pip install 'agentstream[toolbar]'
"""

import asyncio
import http.server
import json
import os
import queue
import socket
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import ThreadingHTTPServer

try:
    import rumps
    _RumpsApp = rumps.App
except ImportError:
    rumps = None
    _RumpsApp = object

from agentstream.events import Agent, ActionType, AgentEvent, SessionInfo
from agentstream.streams import watch_stream, demo_stream
from agentstream.theme import session_color

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PANEL_PORT_RANGE = range(7891, 7901)
_MAX_BUFFER = 2000
_MENU_POLL_SEC = 2.0
_NOTIFY_COOLDOWN_SEC = 5.0

# Events that trigger macOS notifications
_NOTIFY_ACTIONS = frozenset({
    ActionType.ERROR,
    ActionType.RESULT,
    ActionType.STREAM_START,
    ActionType.STREAM_END,
    ActionType.TURN_COMPLETE,
    ActionType.TURN_FAILED,
})


# ---------------------------------------------------------------------------
# Panel HTML (self-contained web UI)
# ---------------------------------------------------------------------------

PANEL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentStream</title>
<style>
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
:root {
    --bg: #0f0f17; --bg-panel: #13131f; --bg-bar: #1a1a2e; --bg-hover: #1e1e30;
    --sep: #2a2a3c; --accent: #818cf8;
    --claude: #a78bfa; --claude-dim: #7c6bc4;
    --codex: #4ade80; --codex-dim: #34a65d;
    --system: #64748b;
    --text: #e2e8f0; --text-dim: #94a3b8; --text-muted: #475569;
}
body {
    font-family: 'SF Mono','Menlo','Monaco','Consolas',monospace;
    background: var(--bg); color: var(--text);
    overflow: hidden; height: 100vh; font-size: 12px; line-height: 1.5;
}
.app {
    display: grid; grid-template-rows: 40px 1fr;
    grid-template-columns: 220px 1fr; height: 100vh;
}
.header {
    grid-column: 1/-1; background: var(--bg-bar);
    display: flex; align-items: center; padding: 0 16px;
    border-bottom: 1px solid var(--sep); gap: 12px;
}
.logo { color: var(--accent); font-weight: bold; font-size: 13px; }
.badge {
    padding: 2px 8px; border-radius: 3px; font-size: 10px;
    font-weight: bold; text-transform: uppercase;
}
.badge.ok { background: #059669; color: #fff; }
.badge.warn { background: #d97706; color: #fff; }
.badge.err { background: #b91c1c; color: #fff; }
.stats { color: var(--text-muted); font-size: 11px; margin-left: auto; }
.sidebar {
    background: var(--bg-panel); border-right: 1px solid var(--sep);
    overflow-y: auto; display: flex; flex-direction: column;
}
.sh { color: var(--accent); font-size: 10px; font-weight: bold;
    padding: 10px 12px 6px; text-transform: uppercase; letter-spacing: .08em; }
.sl { flex: 1; }
.ss {
    padding: 6px 12px; cursor: pointer; display: flex;
    align-items: center; gap: 8px; transition: background .15s;
    border-left: 2px solid transparent;
}
.ss:hover { background: var(--bg-hover); }
.ss.filtered { opacity: .35; }
.ss .dot { font-size: 8px; flex-shrink: 0; }
.ss .inf { flex: 1; min-width: 0; }
.ss .an { font-size: 10px; text-transform: uppercase; font-weight: bold; }
.ss .sn { font-size: 11px; color: var(--text-dim);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ss .ct { color: var(--text-muted); font-size: 10px; flex-shrink: 0; }
.events { overflow-y: auto; padding: 2px 0; }
.ev {
    padding: 1px 12px; display: flex; white-space: nowrap;
    min-height: 18px; align-items: baseline;
}
.ev:hover { background: rgba(255,255,255,.02); }
.ev-ts { color: var(--text-muted); width: 66px; flex-shrink: 0; }
.ev-sp { color: var(--sep); width: 10px; flex-shrink: 0; text-align: center; }
.ev-ic { width: 20px; flex-shrink: 0; font-weight: bold; }
.ev-ag { width: 52px; flex-shrink: 0; font-weight: bold; }
.ev-ac { width: 88px; flex-shrink: 0; color: var(--claude-dim); }
.ev-co { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.sep-line { padding: 0 12px; color: var(--sep); height: 14px; line-height: 14px; font-size: 11px; }
.ag-claude { color: var(--claude); } .ag-codex { color: var(--codex); } .ag-system { color: var(--system); }
.c-error,.c-turn_fail { color: #ef4444; }
.c-tool_use,.c-mcp_tool { color: #fbbf24; }
.c-tool_result { color: #a3a3a3; }
.c-command { color: #f97316; }
.c-file_edit { color: #22d3ee; }
.c-result,.c-turn_done { color: #34d399; }
.c-thinking,.c-reasoning { color: #6b7280; }
.c-search,.c-user_prompt { color: #60a5fa; }
.c-stream,.c-stream_end,.c-compact { color: var(--system); }
.scroll-btn {
    position: fixed; bottom: 12px; right: 20px; background: var(--accent);
    color: #fff; border: none; padding: 6px 14px; border-radius: 6px;
    font-size: 11px; font-family: inherit; cursor: pointer;
    display: none; box-shadow: 0 2px 8px rgba(0,0,0,.4); z-index: 10;
}
.scroll-btn.vis { display: block; }
.scroll-btn:hover { opacity: .9; }
.empty { display: flex; align-items: center; justify-content: center;
    height: 100%; color: var(--text-muted); font-size: 13px; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #3a3a5a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #5a5a7a; }
</style>
</head>
<body>
<div class="app">
    <div class="header">
        <span class="logo">\u26a1 AgentStream</span>
        <span class="badge warn" id="badge">CONNECTING</span>
        <span class="stats" id="stats"></span>
    </div>
    <div class="sidebar">
        <div class="sh">Sessions</div>
        <div class="sl" id="sessions">
            <div style="padding:12px;color:var(--text-muted);font-size:11px">
                Waiting for sessions\u2026
            </div>
        </div>
    </div>
    <div class="events" id="events">
        <div class="empty" id="empty">Waiting for events\u2026</div>
    </div>
</div>
<button class="scroll-btn" id="sbtn" onclick="toBottom()">\u2193 New events</button>
<script>
const IC={text:'>>',text_delta:'>>',thinking:'<>',reasoning:'<>',tool_use:'{}',
tool_result:'<-',command:'$ ',file_edit:'+-',error:'!!',init:'->',result:'==',
msg_start:'->',msg_stop:'[]',stream:'::',stream_end:'::',thread:'->',turn:'~~',
turn_done:'OK',turn_fail:'!!',message:'>>',mcp_tool:'{}',search:'??',
compact:'..',task:'>>',user_prompt:'U>',ping:'..',unknown:'  '};
const SEP=new Set(['init','msg_start','thread','turn','result','user_prompt']);
let S={},hidden=new Set(),auto=true,total=0,last=null;
const eEl=document.getElementById('events'),sEl=document.getElementById('sessions'),
stEl=document.getElementById('stats'),sb=document.getElementById('sbtn'),
bg=document.getElementById('badge'),em=document.getElementById('empty');

eEl.addEventListener('scroll',()=>{
    auto=eEl.scrollHeight-eEl.scrollTop-eEl.clientHeight<50;
    sb.classList.toggle('vis',!auto);
});
function toBottom(){eEl.scrollTop=eEl.scrollHeight;auto=true;sb.classList.remove('vis');}
function esc(t){const d=document.createElement('span');d.textContent=t;return d.innerHTML;}

function updS(){
    const e=Object.entries(S);
    if(!e.length){sEl.innerHTML='<div style="padding:12px;color:var(--text-muted);font-size:11px">Waiting\u2026</div>';return;}
    sEl.innerHTML='';
    for(const[id,i]of e){
        const d=document.createElement('div');
        d.className='ss'+(hidden.has(id)?' filtered':'');
        d.innerHTML='<span class="dot" style="color:'+i.color+'">\\u25cf</span>'+
            '<div class="inf"><div class="an" style="color:'+i.color+'">'+esc(i.agent)+'</div>'+
            '<div class="sn">'+esc(i.name)+'</div></div>'+
            '<span class="ct">'+i.n+'</span>';
        d.onclick=()=>{hidden.has(id)?hidden.delete(id):hidden.add(id);updS();};
        sEl.appendChild(d);
    }
}

function updStats(){
    const c=Object.keys(S).length;
    stEl.textContent=c?c+' session'+(c!==1?'s':'')+' \\u00b7 '+total+' events':'';
}

function add(d){
    if(em&&em.parentNode)em.remove();
    if(d.session_id){
        if(!S[d.session_id]){
            const m=d.metadata||{};
            S[d.session_id]={
                agent:d.agent,
                name:m.slug?m.slug.split('-').pop():(m.project_name||m.cwd_project||d.session_id.slice(0,8)),
                n:0, color:d.agent==='claude'?'var(--claude)':d.agent==='codex'?'var(--codex)':'var(--system)'
            };
        }
        S[d.session_id].n++;
    }
    total++;
    if(d.session_id&&hidden.has(d.session_id)){updStats();return;}
    if(d.action==='ping'){updStats();return;}
    if(SEP.has(d.action)&&last&&last!=='stream'){
        const s=document.createElement('div');s.className='sep-line';
        s.textContent='\\u2500'.repeat(80);eEl.appendChild(s);
    }
    const el=document.createElement('div');el.className='ev';
    const ts=d.timestamp?new Date(d.timestamp).toLocaleTimeString('en-US',{hour12:false}):'';
    const ic=IC[d.action]||'  ';
    el.innerHTML='<span class="ev-ts">'+ts+'</span><span class="ev-sp">|</span>'+
        '<span class="ev-ic c-'+d.action+'">'+ic+'</span>'+
        '<span class="ev-ag ag-'+d.agent+'">'+esc(d.agent.toUpperCase())+'</span>'+
        '<span class="ev-sp">|</span><span class="ev-ac">'+esc(d.action)+'</span>'+
        '<span class="ev-co c-'+d.action+'">'+esc(d.content||'')+'</span>';
    eEl.appendChild(el);last=d.action;
    while(eEl.children.length>3000)eEl.removeChild(eEl.firstChild);
    if(auto)requestAnimationFrame(()=>{eEl.scrollTop=eEl.scrollHeight;});
    if(total%5===0||total<20){updS();updStats();}
}

fetch('/api/history').then(r=>r.json()).then(ev=>{
    ev.forEach(add);updS();updStats();toBottom();go();
}).catch(()=>go());

function go(){
    const src=new EventSource('/events');
    src.onopen=()=>{bg.textContent='STREAMING';bg.className='badge ok';};
    src.onmessage=e=>{try{add(JSON.parse(e.data));}catch{}};
    src.onerror=()=>{bg.textContent='RECONNECTING';bg.className='badge err';src.close();setTimeout(go,2000);};
}

setInterval(()=>{
    fetch('/api/sessions').then(r=>r.json()).then(d=>{
        for(const[id,i]of Object.entries(d)){
            if(S[id]){S[id].color=i.color||S[id].color;S[id].n=i.event_count;S[id].name=i.display_name;}
        }
        updS();updStats();
    }).catch(()=>{});
},5000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# EventBuffer — thread-safe shared state
# ---------------------------------------------------------------------------

class EventBuffer:
    """Thread-safe buffer shared between watcher thread, menu bar, and panel."""

    def __init__(self, maxlen: int = _MAX_BUFFER):
        self._events: deque[tuple[int, AgentEvent]] = deque(maxlen=maxlen)
        self._sessions: dict[str, SessionInfo] = {}
        self._counter = 0
        self._lock = threading.Lock()
        self._sse_queues: list[queue.Queue] = []

    def append(self, event: AgentEvent) -> None:
        with self._lock:
            self._counter += 1
            seq = self._counter
            self._events.append((seq, event))

            sid = event.session_id
            if sid and sid not in self._sessions:
                self._register_session(event)
            if sid and sid in self._sessions:
                self._sessions[sid].event_count += 1
                if event.metadata and event.metadata.get("total_cost_usd"):
                    self._sessions[sid].total_cost += event.metadata["total_cost_usd"]

        for q in self._sse_queues[:]:
            try:
                q.put_nowait((seq, event))
            except queue.Full:
                pass

    def _register_session(self, event: AgentEvent) -> None:
        sid = event.session_id
        meta = event.metadata or {}

        if sid.startswith("demo-"):
            name = "Demo"
        elif meta.get("slug"):
            name = meta["slug"].rsplit("-", 1)[-1]
        elif meta.get("project_name"):
            name = meta["project_name"]
        elif meta.get("cwd_project"):
            name = meta["cwd_project"]
        else:
            name = sid[:8]

        primary, dim = session_color(sid)
        self._sessions[sid] = SessionInfo(
            session_id=sid,
            agent=event.agent,
            display_name=name,
            color=primary,
            color_dim=dim,
        )

    @property
    def counter(self) -> int:
        with self._lock:
            return self._counter

    def get_sessions(self) -> dict[str, SessionInfo]:
        with self._lock:
            return dict(self._sessions)

    def get_events_since(self, since: int) -> list[tuple[int, AgentEvent]]:
        with self._lock:
            return [(s, e) for s, e in self._events if s > since]

    def get_all_events(self) -> list[AgentEvent]:
        with self._lock:
            return [e for _, e in self._events]

    def subscribe_sse(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        self._sse_queues.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue) -> None:
        try:
            self._sse_queues.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Background watcher thread
# ---------------------------------------------------------------------------

def _run_watcher(
    buf: EventBuffer,
    stop: threading.Event,
    demo: bool = False,
) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _watch() -> None:
        while not stop.is_set():
            try:
                stream = demo_stream() if demo else watch_stream()
                async for event in stream:
                    if stop.is_set():
                        return
                    buf.append(event)
            except asyncio.CancelledError:
                return
            except Exception as e:
                buf.append(AgentEvent(
                    agent=Agent.SYSTEM,
                    action=ActionType.ERROR,
                    content=f"Watcher error: {e}",
                ))
                for _ in range(50):
                    if stop.is_set():
                        return
                    await asyncio.sleep(0.1)

    try:
        loop.run_until_complete(_watch())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Panel HTTP server
# ---------------------------------------------------------------------------

def _event_to_dict(event: AgentEvent) -> dict:
    return {
        "agent": event.agent.value,
        "action": event.action.value,
        "content": event.content or "",
        "timestamp": event.timestamp.isoformat(),
        "session_id": event.session_id,
        "metadata": event.metadata or {},
    }


def _make_handler(buf: EventBuffer, stop: threading.Event):
    """Build a request handler class with closure over buffer and stop event."""

    class Handler(http.server.BaseHTTPRequestHandler):

        def do_GET(self):
            routes = {
                "/": self._panel,
                "/events": self._sse,
                "/api/sessions": self._sessions,
                "/api/history": self._history,
            }
            handler = routes.get(self.path)
            if handler:
                handler()
            else:
                self.send_error(404)

        def _panel(self):
            body = PANEL_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = buf.subscribe_sse()
            try:
                while not stop.is_set():
                    try:
                        _, event = q.get(timeout=15)
                        data = json.dumps(_event_to_dict(event))
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                buf.unsubscribe_sse(q)

        def _sessions(self):
            sessions = buf.get_sessions()
            data = {}
            for sid, info in sessions.items():
                data[sid] = {
                    "session_id": info.session_id,
                    "agent": info.agent.value,
                    "display_name": info.display_name,
                    "event_count": info.event_count,
                    "status": info.status,
                    "total_cost": info.total_cost,
                    "color": info.color,
                }
            self._json_response(data)

        def _history(self):
            events = buf.get_all_events()
            self._json_response([_event_to_dict(e) for e in events])

        def _json_response(self, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass  # silence request logs

    return Handler


def _find_port(port_range) -> int | None:
    for port in port_range:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def _run_server(buf: EventBuffer, stop: threading.Event, port: int) -> None:
    handler = _make_handler(buf, stop)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.timeout = 0.5
    server.daemon_threads = True

    while not stop.is_set():
        server.handle_request()

    server.server_close()


# ---------------------------------------------------------------------------
# Menu Bar Application
# ---------------------------------------------------------------------------

class AgentStreamToolbar(_RumpsApp):
    """macOS menu bar app for AgentStream."""

    def __init__(self, demo: bool = False):
        super().__init__("AgentStream", title="\u26a1", quit_button=None)

        self._buf = EventBuffer()
        self._stop = threading.Event()
        self._demo = demo
        self._notifications_on = True
        self._last_notify_time = 0.0
        self._last_notify_seq = 0
        self._panel_port: int | None = None

        # --- Menu ---
        self._sessions_menu = rumps.MenuItem("Scanning for sessions\u2026")

        self.menu = [
            self._sessions_menu,
            None,
            rumps.MenuItem("Open Panel", callback=self._open_panel),
            None,
            rumps.MenuItem("Notifications", callback=self._toggle_notif),
            None,
            rumps.MenuItem("Quit AgentStream", callback=self._quit),
        ]
        self.menu["Notifications"].state = True

        # --- Panel server ---
        self._panel_port = _find_port(_PANEL_PORT_RANGE)

        # --- Background threads ---
        threading.Thread(
            target=_run_watcher,
            args=(self._buf, self._stop, self._demo),
            daemon=True,
            name="as-watcher",
        ).start()

        if self._panel_port:
            threading.Thread(
                target=_run_server,
                args=(self._buf, self._stop, self._panel_port),
                daemon=True,
                name="as-panel",
            ).start()

        # --- Periodic tick ---
        self._timer = rumps.Timer(self._tick, _MENU_POLL_SEC)
        self._timer.start()

    # -- Tick ---------------------------------------------------------------

    def _tick(self, _sender) -> None:
        self._refresh_menu()
        if self._notifications_on:
            self._check_notifications()

    def _refresh_menu(self) -> None:
        sessions = self._buf.get_sessions()

        # Clear submenu
        for key in list(self._sessions_menu.keys()):
            del self._sessions_menu[key]

        if sessions:
            count = len(sessions)
            total = sum(s.event_count for s in sessions.values())
            self._sessions_menu.title = (
                f"{count} session{'s' if count != 1 else ''} \u00b7 {total} events"
            )
            self.title = f"\u26a1{count}"

            for info in sessions.values():
                icon = "\u25c6" if info.agent == Agent.CLAUDE else "\u25cf"
                label = f"{icon} {info.agent.value} \u00b7 {info.display_name} ({info.event_count})"
                item = rumps.MenuItem(label)
                item.set_callback(None)
                self._sessions_menu[label] = item
        else:
            self._sessions_menu.title = "Scanning for sessions\u2026"
            self.title = "\u26a1"

    def _check_notifications(self) -> None:
        new = self._buf.get_events_since(self._last_notify_seq)
        now = time.time()

        for seq, event in new:
            self._last_notify_seq = seq
            if event.action not in _NOTIFY_ACTIONS:
                continue
            if now - self._last_notify_time < _NOTIFY_COOLDOWN_SEC:
                continue

            self._last_notify_time = now
            agent = event.agent.value.title()
            action = event.action.value.replace("_", " ").title()
            content = (event.content or "")[:120]

            rumps.notification(
                title=f"AgentStream \u00b7 {agent}",
                subtitle=action,
                message=content,
            )

    # -- Callbacks ----------------------------------------------------------

    def _open_panel(self, _sender) -> None:
        if self._panel_port:
            webbrowser.open(f"http://127.0.0.1:{self._panel_port}")
        else:
            rumps.notification(
                title="AgentStream",
                subtitle="Error",
                message="Panel server could not start (no free port).",
            )

    def _toggle_notif(self, sender) -> None:
        self._notifications_on = not self._notifications_on
        sender.state = self._notifications_on

    def _quit(self, _sender) -> None:
        self._stop.set()
        rumps.quit_application()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(demo: bool = False) -> None:
    """Launch the AgentStream menu bar app."""
    if sys.platform != "darwin":
        print("The toolbar is only available on macOS.", file=sys.stderr)
        sys.exit(1)

    if rumps is None:
        print("toolbar requires: pip install 'agentstream[toolbar]'", file=sys.stderr)
        sys.exit(1)

    AgentStreamToolbar(demo=demo).run()


if __name__ == "__main__":
    main(demo="AGENTSTREAM_DEMO" in os.environ)
