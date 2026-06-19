"use strict";

const TILE = 40,
    MARGIN = 10,
    TOP = 50,
    BOTTOM = 40,
    GRID = 13,
    BOARD = GRID * TILE,
    W = 540,
    H = 610;
const COL = {
    bg: "#090624",
    panel: "#17114a",
    panelHi: "#31258b",
    free: "#14285e",
    freeAlt: "#19306d",
    breakable: "#a64b35",
    breakTop: "#f08a4b",
    unbreak: "#5b4aa8",
    unbreakTop: "#9a86e8",
    text: "#fff6d2",
    muted: "#aaa4d6",
    accent: "#ffd447",
    good: "#55e68a",
    warn: "#ff9f43",
    bad: "#ff5d73",
    bomb: "#090914",
    fireOut: "#ff5d3d",
    fireIn: "#ffe66d",
};
const SLOT = ["#ff5d73", "#4cc9f0", "#55e68a", "#ffd447"];
const SLOT_LABEL = ["P1", "P2", "P3", "P4"];
const DELTA = { UP: [0, -1], DOWN: [0, 1], LEFT: [-1, 0], RIGHT: [1, 0] };
const MOVE_REPEAT = 0.12,
    RECONNECT_WINDOW = 30;
const FREE = 0,
    BREAKABLE = 1,
    UNBREAKABLE = 2;

const now = () => performance.now() / 1000;

const S = {
    screen: "connecting",
    playerId: null,
    name: "Player",
    snapshot: null,
    roomCode: null,
    mapId: 1,
    mapName: "",
    lobby: null,
    isHost: false,
    queueInfo: null,
    results: null,
    leaderboard: null,
    rttMs: null,
    held: [],
    lastMoveSent: 0,
    rejectFlashUntil: 0,
    reconnecting: false,
    reconnectUntil: 0,
};

let ws = null;

function wsURL() {
    return (
        (location.protocol === "https:" ? "wss" : "ws") +
        "://" +
        location.host +
        "/ws"
    );
}
function send(obj) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

function connect(isReconnect) {
    ws = new WebSocket(wsURL());
    ws.onopen = () => {
        if (isReconnect)
            send({ type: "RECONNECT", player_id: S.playerId, name: S.name });
        else send({ type: "HELLO", name: S.name });
    };
    ws.onmessage = (ev) => {
        let m;
        try {
            m = JSON.parse(ev.data);
        } catch (e) {
            return;
        }
        handleMsg(m);
    };
    ws.onclose = () => onClose();
    ws.onerror = () => {
        try {
            ws.close();
        } catch (e) { }
    };
}

function onClose() {
    if (S.reconnecting) return;
    if (S.screen === "game" && S.playerId) startReconnect();
}

function startReconnect() {
    if (S.reconnecting) return;
    S.reconnecting = true;
    S.reconnectUntil = now() + RECONNECT_WINDOW;
    const attempt = () => {
        if (now() >= S.reconnectUntil) {
            S.reconnecting = false;
            return;
        }
        connect(true);
    };
    const watch = setInterval(() => {
        if (!S.reconnecting) {
            clearInterval(watch);
            return;
        }
        if (ws && ws.readyState === 1) {
        } else if (!ws || ws.readyState === 3) {
            if (now() < S.reconnectUntil) attempt();
        }
    }, 1500);
    attempt();
}

function handleMsg(m) {
    const t = m.type;
    if (t === "WELCOME") {
        S.playerId = m.player_id;
        S.name = m.name || S.name;
        if (S.screen === "connecting") show("menu");
        if (S.avatar) {
            send({ type: "SET_AVATAR", data: S.avatar });
            avatarCache[S.playerId] = S._avatarImg || null;
        }
    } else if (t === "RECONNECT_OK") {
        S.reconnecting = false;
        S.roomCode = m.room;
        S.mapId = m.map_id;
        S.mapName = m.map_name;
        toast("Tersambung kembali!");
    } else if (t === "RECONNECT_FAIL") {
        S.reconnecting = false;
        S.snapshot = null;
        show("menu");
        toast("Gagal menyambung ulang");
    } else if (t === "JOIN_ERROR") {
        $("joinErr").textContent = m.reason || "Tidak bisa join";
        $("menuErr").textContent = "";
    } else if (t === "QUEUE_JOINED") {
        const c = m.count != null ? m.count : m.position || 1;
        S.queueInfo = { count: c, needed: m.needed || 4 };
        renderQueue();
        show("queue");
    } else if (t === "MATCH_FOUND") {
        S.roomCode = m.room;
        toast("Pemain lengkap! Memulai...");
    } else if (t === "LOBBY_UPDATE") {
        S.lobby = m;
        S.roomCode = m.room;
        S.mapId = m.map_id;
        S.mapName = m.map_name;
        S.isHost = m.is_host;
        loadAvatars(m.players);
        renderLobby();
        show("lobby");
    } else if (t === "GAME_START") {
        S.playerId = m.your_id || S.playerId;
        S.roomCode = m.room;
        S.mapId = m.map_id;
        S.mapName = m.map_name;
        S.snapshot = m.snapshot;
        S.held = [];
        S.results = null;
        if (m.avatars) {
            Object.entries(m.avatars).forEach(([pid, data]) => {
                if (data) {
                    const i = new Image();
                    i.src = data;
                    avatarCache[pid] = i;
                }
            });
        }
        show("game");
    } else if (t === "STATE") {
        S.snapshot = m.snapshot;
    } else if (t === "MOVE_REJECT") {
        S.rejectFlashUntil = now() + 0.25;
    } else if (t === "PONG") {
        if (typeof m.t === "number")
            S.rttMs = Math.max(0, Math.round((now() - m.t) * 1000));
    } else if (t === "MATCH_OVER") {
        S.results = m.results || [];
        S.leaderboard = m.leaderboard || [];
        renderPost();
        show("post");
    } else if (t === "INFO") {
        toast(m.message || "");
    } else if (t === "LEFT_ROOM") {
        S.lobby = null;
        S.roomCode = null;
        S.snapshot = null;
        S.queueInfo = null;
        show("menu");
    }
}

const $ = (id) => document.getElementById(id);

function show(name) {
    S.screen = name;
    document
        .querySelectorAll(".screen")
        .forEach((s) => s.classList.remove("active"));
    $("screen-" + name).classList.add("active");
    $("pad").classList.toggle("on", name === "game" && hasTouch);
    if (name === "game" && !hasTouch && !document.fullscreenElement)
        toast("Tekan F untuk fullscreen");
}

let toastTimer = null;
function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.style.display = "none"), 2800);
}

function myPlayer() {
    if (!S.snapshot) return null;
    return S.snapshot.players.find((p) => p.id === S.playerId) || null;
}

function sendMove(dir) {
    const mp = myPlayer();
    if (!mp || !mp.alive || mp.spectator) return;
    const d = DELTA[dir];
    send({ type: "MOVE", col: mp.col + d[0], row: mp.row + d[1] });
    S.lastMoveSent = now();
}
function plantBomb() {
    const mp = myPlayer();
    if (!mp || !mp.alive || mp.spectator) return;
    send({ type: "PLANT_BOMB" });
}

const KEYDIR = {
    ArrowUp: "UP",
    ArrowDown: "DOWN",
    ArrowLeft: "LEFT",
    ArrowRight: "RIGHT",
    w: "UP",
    s: "DOWN",
    a: "LEFT",
    d: "RIGHT",
    W: "UP",
    S: "DOWN",
    A: "LEFT",
    D: "RIGHT",
};
addEventListener("keydown", (e) => {
    if (e.key === "f" || e.key === "F") {
        toggleFullscreen();
        return;
    }
    if (S.screen !== "game") return;
    const dir = KEYDIR[e.key];
    if (dir) {
        e.preventDefault();
        if (!S.held.includes(dir)) S.held.push(dir);
        sendMove(dir);
    } else if (e.key === " ") {
        e.preventDefault();
        plantBomb();
    }
});
addEventListener("keyup", (e) => {
    if (S.screen !== "game") return;
    const dir = KEYDIR[e.key];
    if (dir) {
        const i = S.held.indexOf(dir);
        if (i >= 0) S.held.splice(i, 1);
    }
});

addEventListener("keydown", (e) => {
    if (S.screen === "lobby" && S.isHost && "1234".includes(e.key))
        changeMap(+e.key);
});

const hasTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
document.querySelectorAll(".pbtn").forEach((b) => {
    const dir = b.dataset.dir;
    const dn = (e) => {
        e.preventDefault();
        if (!S.held.includes(dir)) S.held.push(dir);
        sendMove(dir);
    };
    const up = (e) => {
        e.preventDefault();
        const i = S.held.indexOf(dir);
        if (i >= 0) S.held.splice(i, 1);
    };
    b.addEventListener("pointerdown", dn);
    b.addEventListener("pointerup", up);
    b.addEventListener("pointerleave", up);
    b.addEventListener("pointercancel", up);
});
$("bombBtn").addEventListener("pointerdown", (e) => {
    e.preventDefault();
    plantBomb();
});

const nameInput = $("nameInput");
$("btnHost").onclick = () => {
    S.name = nameInput.value.trim() || "Player";
    resendName();
    send({ type: "HOST_GAME", map_id: 1 });
};
$("btnJoin").onclick = () => {
    S.name = nameInput.value.trim() || "Player";
    resendName();
    $("joinErr").textContent = "";
    $("codeInput").value = "";
    show("join");
};
$("btnQuick").onclick = () => {
    S.name = nameInput.value.trim() || "Player";
    resendName();
    send({ type: "QUICK_MATCH" });
};

function resendName() {
    if (S.playerId) send({ type: "SET_NAME", name: S.name });
}

function doJoin() {
    const c = $("codeInput").value.replace(/\D/g, "").slice(0, 6);
    if (c.length === 6) send({ type: "JOIN_GAME", code: c });
    else $("joinErr").textContent = "Kode harus 6 digit";
}
$("btnJoinGo").onclick = doJoin;
$("btnJoinBack").onclick = () => show("menu");
$("codeInput").addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6);
});
$("codeInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        doJoin();
    }
});
$("mapPrev").onclick = () => changeMap(((S.mapId + 2) % 4) + 1);
$("mapNext").onclick = () => changeMap((S.mapId % 4) + 1);
$("btnStart").onclick = () => send({ type: "START_GAME" });
$("btnLeaveLobby").onclick = () => send({ type: "LEAVE_ROOM" });
$("btnQueueCancel").onclick = () => {
    send({ type: "LEAVE_ROOM" });
    S.queueInfo = null;
    show("menu");
};
$("btnPostBack").onclick = () => {
    send({ type: "LEAVE_ROOM" });
    S.results = null;
    show("menu");
};

function changeMap(id) {
    if (id !== S.mapId) {
        S.mapId = id;
        send({ type: "SET_MAP", map_id: id });
    }
}

function toggleFullscreen() {
    const el = document.documentElement;
    if (!document.fullscreenElement)
        (
            el.requestFullscreen ||
            el.webkitRequestFullscreen ||
            (() => { })
        ).call(el);
    else
        (
            document.exitFullscreen ||
            document.webkitExitFullscreen ||
            (() => { })
        ).call(document);
}
$("fsBtn").onclick = toggleFullscreen;

document.addEventListener("fullscreenchange", () => {
    $("fsBtn").textContent = document.fullscreenElement
        ? "✕ Exit Fullscreen"
        : "⛶ Fullscreen";
});
document.addEventListener("webkitfullscreenchange", () => {
    $("fsBtn").textContent = document.webkitFullscreenElement
        ? "✕ Exit Fullscreen"
        : "⛶ Fullscreen";
});

function renderLobby() {
    const L = S.lobby || {};
    $("lobbyCode").textContent = S.roomCode || "------";
    $("lobbySub").textContent = L.hidden ? "Quick Match" : "";

    const wrap = $("lobbyPlayers");
    wrap.innerHTML = "";
    const players = L.players || [],
        maxp = L.max_players || 4;

    players.forEach((p) => {
        const row = document.createElement("div");
        row.className = "pslot" + (p.id === S.playerId ? " me" : "");
        const dot = document.createElement("span");
        dot.className = "pdot";
        dot.style.background = SLOT[(p.slot || 0) % 4];
        const nm = document.createElement("span");
        nm.className = "pname";
        nm.textContent = p.name;
        const tags = [];
        if (p.host) tags.push("HOST");
        if (p.id === S.playerId) tags.push("Kamu");
        const tg = document.createElement("span");
        tg.className = "ptag";
        tg.textContent = tags.length ? "(" + tags.join(", ") + ")" : "";
        row.append(dot, nm, tg);
        wrap.append(row);
    });
    for (let i = players.length; i < maxp; i++) {
        const row = document.createElement("div");
        row.className = "pslot";
        const dot = document.createElement("span");
        dot.className = "pdot empty";
        const nm = document.createElement("span");
        nm.style.cssText = "font-size:13px;color:var(--muted);";
        nm.textContent = "Menunggu pemain...";
        row.append(dot, nm);
        wrap.append(row);
    }

    $("lobbyMap").textContent = "Map " + S.mapId + ": " + (S.mapName || "");
    drawMini(L.preview);

    document
        .querySelectorAll(".hostonly")
        .forEach((e) => (e.style.display = S.isHost ? "" : "none"));
    document
        .querySelectorAll(".guestonly")
        .forEach((e) => (e.style.display = S.isHost ? "none" : ""));

    const start = $("btnStart"),
        can = players.length >= 2;
    start.disabled = !can;
    start.textContent = can ? "▶  MULAI GAME" : "Minimal 2 pemain mpruy";
}

function drawMini(preview) {
    const cv = $("mapMini"),
        ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, cv.width, cv.height);
    if (!preview) return;
    const cell = cv.width / GRID;
    for (let r = 0; r < GRID; r++)
        for (let c = 0; c < GRID; c++) {
            ctx.fillStyle =
                preview[r][c] === UNBREAKABLE ? COL.unbreak : COL.free;
            ctx.fillRect(c * cell, r * cell, cell + 1, cell + 1);
        }
    [
        [1, 1],
        [11, 11],
        [11, 1],
        [1, 11],
    ].forEach((s, i) => {
        ctx.fillStyle = SLOT[i];
        ctx.beginPath();
        ctx.arc(
            s[0] * cell + cell / 2,
            s[1] * cell + cell / 2,
            cell / 2.5,
            0,
            7,
        );
        ctx.fill();
    });
}

function renderQueue() {
    const q = S.queueInfo || { count: 0, needed: 4 };
    $("queueCount").textContent = q.count + " / " + q.needed + " pemain";
    const bars = $("queueBars");
    bars.innerHTML = "";
    for (let i = 0; i < q.needed; i++) {
        const d = document.createElement("div");
        d.className = "q-slot";
        if (i < q.count) {
            d.style.background = SLOT[i % 4];
            d.style.borderColor = "transparent";
        }
        bars.append(d);
    }
}

function renderPost() {
    const medal = { 1: "#ffd700", 2: "#c8c8d2", 3: "#be825a" };
    const rt = $("postResults");
    rt.innerHTML = "";
    (S.results || [])
        .slice()
        .sort((a, b) => a.rank - b.rank)
        .forEach((r) => {
            const d = r.points_delta,
                ds = (d >= 0 ? "+" : "") + d,
                dc = d > 0 ? COL.good : d < 0 ? COL.bad : COL.muted;
            const tr = document.createElement("tr");
            tr.innerHTML =
                `<td style="color:${medal[r.rank] || COL.text};font-weight:700;">${r.rank}. ${esc(r.name)}</td>` +
                `<td class="right" style="color:${dc};font-weight:700;">${ds}</td>` +
                `<td class="right muted">total ${r.total_points}</td>`;
            rt.append(tr);
        });
    const lb = $("postLeaderboard");
    lb.innerHTML = "";
    (S.leaderboard || []).forEach((e, i) => {
        const tr = document.createElement("tr");
        tr.innerHTML =
            `<td>${i + 1}. ${esc(e.name)}</td>` +
            `<td class="right" style="color:var(--accent);font-weight:700;">${e.points} pts</td>` +
            `<td class="right muted">W:${e.wins} G:${e.games}</td>`;
        lb.append(tr);
    });
}
function esc(s) {
    return String(s).replace(
        /[<>&]/g,
        (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c],
    );
}

function copyRoomCode() {
    const code = S.roomCode;
    if (!code) return;
    navigator.clipboard
        .writeText(code)
        .then(() => toast("Kode " + code + " disalin!"))
        .catch(() => {
            const ta = document.createElement("textarea");
            ta.value = code;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            toast("Kode " + code + " disalin!");
        });
}

const avatarCache = {};

function loadAvatars(players) {
    (players || []).forEach((p) => {
        if (!p.avatar) return;
        const ex = avatarCache[p.id];
        if (!ex || ex._src !== p.avatar) {
            const img = new Image();
            img.src = p.avatar;
            img._src = p.avatar;
            avatarCache[p.id] = img;
        }
    });
}

$("btnAvatar").onclick = () => $("avatarInput").click();
$("avatarPreview").onclick = () => $("avatarInput").click();

$("avatarInput").onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
        const raw = new Image();
        raw.onload = () => {
            const c2 = document.createElement("canvas");
            c2.width = c2.height = 96;
            const x2 = c2.getContext("2d");
            const side = Math.min(raw.width, raw.height);
            const sx = (raw.width - side) / 2,
                sy = (raw.height - side) / 2;
            x2.drawImage(raw, sx, sy, side, side, 0, 0, 96, 96);
            const data = c2.toDataURL("image/jpeg", 0.75);
            S.avatar = data;
            const img = new Image();
            img.src = data;
            img._src = data;
            S._avatarImg = img;
            if (S.playerId) {
                avatarCache[S.playerId] = img;
                send({ type: "SET_AVATAR", data });
            }
            const prev = $("avatarPreview");
            const ph = $("avatarPlaceholder");
            if (ph) ph.remove();
            prev.style.cssText = `width:62px;height:62px;border-radius:50%;border:3px solid var(--accent);overflow:hidden;flex-shrink:0;cursor:pointer;background:var(--panel3);`;
            prev.innerHTML = `<img src="${data}" style="width:100%;height:100%;object-fit:cover;">`;
        };
        raw.src = ev.target.result;
    };
    reader.readAsDataURL(file);
};

const cv = $("board"),
    ctx = cv.getContext("2d");

function rrect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.rect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}
function text(
    str,
    x,
    y,
    {
        size = 16,
        color = COL.text,
        align = "left",
        baseline = "alphabetic",
        bold = true,
    } = {},
) {
    ctx.font =
        (bold ? "bold " : "") + size + 'px "Courier New",Courier,monospace';
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.textBaseline = baseline;
    ctx.fillText(str, x, y);
}

function drawGame() {
    ctx.fillStyle = COL.bg;
    ctx.fillRect(0, 0, W, H);
    const snap = S.snapshot;
    if (!snap) {
        text("Memuat arena...", W / 2, H / 2, {
            size: 22,
            color: COL.accent,
            align: "center",
        });
        return;
    }

    ctx.fillStyle = COL.panel;
    ctx.fillRect(0, 0, W, TOP);
    text("ROOM " + (S.roomCode || ""), MARGIN, 18, {
        size: 12,
        color: COL.muted,
        bold: false,
    });
    text(S.mapName || "", MARGIN, 34, {
        size: 11,
        color: COL.muted,
        bold: false,
    });
    const mp = myPlayer();
    if (mp) {
        const line = "💣 " + (mp.max_bombs || 1) + "   🔥 " + (mp.range || 2);
        text(line, W / 2, 26, {
            size: 16,
            color: COL.accent,
            align: "center",
        });
    }
    const rtt = S.rttMs == null ? "—" : S.rttMs + "ms";
    const rc =
        S.rttMs == null
            ? COL.muted
            : S.rttMs < 80
                ? COL.good
                : S.rttMs < 200
                    ? COL.warn
                    : COL.bad;
    text(rtt, W - MARGIN, 18, { size: 12, color: rc, align: "right" });
    const alive = snap.players.filter((p) => p.alive).length;
    text("hidup: " + alive, W - MARGIN, 34, {
        size: 11,
        color: COL.muted,
        align: "right",
        bold: false,
    });

    drawBoard(snap);

    ctx.fillStyle = COL.panel;
    ctx.fillRect(0, TOP + BOARD, W, BOTTOM);
    let hint = "WASD / ↑↓←→ : gerak     Space : bom",
        hcol = COL.muted;
    if (mp && mp.spectator) {
        hint = "SPECTATOR — menonton pertandingan";
        hcol = COL.warn;
    }
    text(hint, MARGIN, TOP + BOARD + 24, {
        size: 12,
        color: hcol,
        bold: false,
    });
    text(
        (snap.elapsed || 0).toFixed(0) + "s",
        W - MARGIN,
        TOP + BOARD + 24,
        { size: 12, color: COL.muted, align: "right", bold: false },
    );

    if (now() < S.rejectFlashUntil) {
        ctx.strokeStyle = COL.bad;
        ctx.lineWidth = 4;
        ctx.strokeRect(MARGIN + 2, TOP + 2, BOARD - 4, BOARD - 4);
    }
    if (mp && mp.spectator) {
        ctx.fillStyle = "rgba(255,215,64,.09)";
        ctx.fillRect(0, TOP + 4, W, 32);
        text("SPECTATOR", W / 2, TOP + 26, {
            size: 15,
            color: COL.warn,
            align: "center",
        });
    }
}

function drawBoard(snap) {
    const ox = MARGIN,
        oy = TOP,
        g = snap.grid;
    for (let r = 0; r < GRID; r++)
        for (let c = 0; c < GRID; c++) {
            const x = ox + c * TILE,
                y = oy + r * TILE,
                v = g[r][c];
            if (v === UNBREAKABLE) {
                ctx.fillStyle = COL.unbreak;
                ctx.fillRect(x, y, TILE, TILE);
                ctx.fillStyle = COL.unbreakTop;
                ctx.fillRect(x + 3, y + 3, TILE - 6, 6);
                ctx.fillStyle = "#30276b";
                ctx.fillRect(x + 3, y + TILE - 7, TILE - 6, 4);
                ctx.strokeStyle = "#090624";
                ctx.lineWidth = 2;
                ctx.strokeRect(x + 1, y + 1, TILE - 2, TILE - 2);
            } else if (v === BREAKABLE) {
                ctx.fillStyle = COL.breakable;
                ctx.fillRect(x + 3, y + 3, TILE - 6, TILE - 6);
                ctx.fillStyle = COL.breakTop;
                ctx.fillRect(x + 6, y + 6, TILE - 12, 6);
                ctx.fillStyle = "#6f2d30";
                ctx.fillRect(x + 6, y + TILE - 10, TILE - 12, 5);
                ctx.strokeStyle = "#54213c";
                ctx.lineWidth = 2;
                ctx.strokeRect(x + 3, y + 3, TILE - 6, TILE - 6);
            } else {
                ctx.fillStyle = (r + c) % 2 === 0 ? COL.free : COL.freeAlt;
                ctx.fillRect(x, y, TILE, TILE);
                ctx.fillStyle = "rgba(255,255,255,.035)";
                ctx.fillRect(x + 4, y + 4, 4, 4);
            }
        }

    const t = now();
    (snap.powerups || []).forEach((pu) =>
        drawPowerup(ox + pu.col * TILE, oy + pu.row * TILE, pu.kind, t),
    );

    (snap.bombs || []).forEach((b) => {
        const cx = ox + b.col * TILE + TILE / 2,
            cy = oy + b.row * TILE + TILE / 2;
        const pulse = 0.5 + 0.5 * Math.abs(((t * 3) % 2) - 1);
        const rad = TILE * 0.3 + TILE * 0.07 * pulse;
        ctx.fillStyle = "rgba(0,0,0,.35)";
        ctx.beginPath();
        ctx.ellipse(cx, cy + rad + 2, rad * 0.85, rad * 0.28, 0, 0, 7);
        ctx.fill();
        ctx.fillStyle = COL.bomb;
        ctx.beginPath();
        ctx.arc(cx, cy, rad, 0, 7);
        ctx.fill();
        ctx.strokeStyle = COL.bad;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = "rgba(255,255,255,.12)";
        ctx.beginPath();
        ctx.arc(cx - rad * 0.28, cy - rad * 0.28, rad * 0.3, 0, 7);
        ctx.fill();
        ctx.strokeStyle = COL.warn;
        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(cx + 2, cy - rad);
        ctx.quadraticCurveTo(cx + 10, cy - rad - 6, cx + 7, cy - rad - 15);
        ctx.stroke();
        ctx.lineCap = "butt";
        if (Math.sin(t * 18) > 0.3) {
            ctx.fillStyle = "#fff";
            ctx.beginPath();
            ctx.arc(cx + 7, cy - rad - 15, 2.5, 0, 7);
            ctx.fill();
        }
        if (b.fuse != null)
            text(b.fuse.toFixed(1), cx, cy + rad + 16, {
                size: 10,
                color: COL.warn,
                align: "center",
                bold: true,
            });
    });

    (snap.explosions || []).forEach((cell) => {
        const x = ox + cell[0] * TILE,
            y = oy + cell[1] * TILE;
        ctx.fillStyle = "rgba(255,112,67,.25)";
        ctx.fillRect(x, y, TILE, TILE);
        ctx.fillStyle = COL.fireOut;
        ctx.fillRect(x + 2, y + 2, TILE - 4, TILE - 4);
        ctx.fillStyle = COL.fireIn;
        ctx.fillRect(x + 10, y + 10, TILE - 20, TILE - 20);
    });

    snap.players.forEach((p) => {
        if (!p.alive) return;
        const cx2 = ox + p.col * TILE + TILE / 2,
            cy2 = oy + p.row * TILE + TILE / 2;
        const r = TILE / 2 - 3;
        let col = SLOT[(p.slot || 0) % 4];
        const disc = !p.connected;
        if (disc) col = dim(col, 0.45);

        if (p.id === S.playerId) {
            ctx.strokeStyle = "rgba(255,255,255,.5)";
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.arc(cx2, cy2, r + 5, 0, Math.PI * 2);
            ctx.stroke();
        }

        const aImg = avatarCache[p.id];
        const hasAvatar = aImg && aImg.complete && aImg.naturalWidth > 0;
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx2, cy2, r, 0, Math.PI * 2);
        ctx.clip();
        if (hasAvatar) {
            if (disc) ctx.globalAlpha = 0.45;
            ctx.drawImage(aImg, cx2 - r, cy2 - r, r * 2, r * 2);
            ctx.globalAlpha = 1;
        } else {
            ctx.fillStyle = col;
            ctx.fillRect(cx2 - r, cy2 - r, r * 2, r * 2);
            ctx.fillStyle = "rgba(255,255,255,.2)";
            ctx.fillRect(cx2 - r, cy2 - r, r * 2, r * 0.35);
        }
        ctx.restore();

        ctx.strokeStyle = col;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(cx2, cy2, r, 0, Math.PI * 2);
        ctx.stroke();

        if (!hasAvatar)
            text(SLOT_LABEL[(p.slot || 0) % 4], cx2, cy2 + 4, {
                size: 11,
                color: "rgba(0,0,0,.75)",
                align: "center",
            });
        if (disc)
            text("zZ", cx2 + r - 1, cy2 - r + 8, {
                size: 9,
                color: COL.warn,
                align: "right",
            });

        if (p.id === S.playerId) {
            const nm = p.name.slice(0, 10);
            ctx.font = '10px "Courier New",Courier,monospace';
            const tw = ctx.measureText(nm).width + 10;
            const tx = Math.max(
                MARGIN,
                Math.min(cx2 - tw / 2, W - MARGIN - tw),
            );
            ctx.fillStyle = "rgba(0,0,0,.65)";
            ctx.fillRect(tx, cy2 - r - 17, tw, 13);
            text(nm, tx + tw / 2, cy2 - r - 7, {
                size: 10,
                color: "#fff",
                align: "center",
                bold: false,
            });
        }
    });
}

function drawPowerup(x, y, kind, t) {
    const pulse = 0.5 + 0.5 * Math.abs(((t * 2) % 2) - 1),
        pad = 7 + 2 * pulse;
    const bx = x + pad,
        by = y + pad,
        bw = TILE - 2 * pad,
        bh = TILE - 2 * pad,
        cx = bx + bw / 2,
        cy = by + bh / 2;
    if (kind === "range") {
        ctx.fillStyle = "#3a1e10";
        rrect(bx, by, bw, bh, 7);
        ctx.fill();
        ctx.strokeStyle = COL.fireOut;
        ctx.lineWidth = 2;
        rrect(bx, by, bw, bh, 7);
        ctx.stroke();
        ctx.fillStyle = COL.fireOut;
        ctx.beginPath();
        ctx.moveTo(cx, cy - 8);
        ctx.bezierCurveTo(cx + 6, cy - 4, cx + 5, cy + 2, cx + 3, cy + 6);
        ctx.lineTo(cx - 3, cy + 6);
        ctx.bezierCurveTo(cx - 5, cy + 2, cx - 6, cy - 4, cx, cy - 8);
        ctx.fill();
        ctx.fillStyle = COL.fireIn;
        ctx.beginPath();
        ctx.moveTo(cx, cy - 3);
        ctx.bezierCurveTo(cx + 3, cy, cx + 2, cy + 4, cx, cy + 5);
        ctx.bezierCurveTo(cx - 2, cy + 4, cx - 3, cy, cx, cy - 3);
        ctx.fill();
    } else {
        ctx.fillStyle = "#111a30";
        rrect(bx, by, bw, bh, 7);
        ctx.fill();
        ctx.strokeStyle = "#5c8fe8";
        ctx.lineWidth = 2;
        rrect(bx, by, bw, bh, 7);
        ctx.stroke();
        ctx.fillStyle = "#12161e";
        ctx.beginPath();
        ctx.arc(cx, cy + 2, 7, 0, 7);
        ctx.fill();
        ctx.strokeStyle = "#5c8fe8";
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(cx, cy - 5);
        ctx.lineTo(cx + 4, cy - 9);
        ctx.stroke();
    }
    text("+", bx + bw - 2, by + 2, {
        size: 10,
        color: "#fff",
        align: "right",
        baseline: "top",
        bold: true,
    });
}

function dim(hex, f) {
    const n = parseInt(hex.slice(1), 16);
    return `rgb(${(((n >> 16) & 255) * f) | 0},${(((n >> 8) & 255) * f) | 0},${((n & 255) * f) | 0})`;
}

function frame() {
    if (
        S.screen === "game" &&
        S.held.length &&
        now() - S.lastMoveSent >= MOVE_REPEAT
    )
        sendMove(S.held[S.held.length - 1]);
    if (S.screen === "game") drawGame();
    requestAnimationFrame(frame);
}
setInterval(() => {
    if (ws && ws.readyState === 1) send({ type: "PING", t: now() });
}, 1000);

nameInput.value = S.name;
connect(false);
requestAnimationFrame(frame);