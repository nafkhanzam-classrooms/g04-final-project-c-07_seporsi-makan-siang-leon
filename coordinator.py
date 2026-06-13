import time
import uuid

from room import (
    RoomManager, ROOM_LOBBY, ROOM_PLAYING, ROOM_FINISHED,
    MAX_PLAYERS, RECONNECT_TIMEOUT,
)
from database import Database
from maps import MAP_NAMES, build_map


def log(level, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


class PlayerSession:
    def __init__(self, pid, name):
        self.id = pid
        self.name = name
        self.conn = None
        self.connected = True
        self.disconnected_at = None
        self.avatar = None


class GameCoordinator:
    def __init__(self):
        self.players = {}
        self.db = Database()
        self.rooms = RoomManager(self._name_of)

    def _name_of(self, pid):
        p = self.players.get(pid)
        return p.name if p else "Player"


    def send_pid(self, pid, msg):
        p = self.players.get(pid)
        if p and p.conn is not None:
            p.conn.send(msg)

    def broadcast_room(self, room, msg, exclude=None):
        for pid in room.members:
            if pid != exclude:
                self.send_pid(pid, msg)

    def _lobby_payload(self, room, recipient_pid):
        return {
            "type": "LOBBY_UPDATE",
            "room": room.code,
            "hidden": room.hidden,
            "host_id": room.host_id,
            "is_host": recipient_pid == room.host_id,
            "map_id": room.map_id,
            "map_name": MAP_NAMES.get(room.map_id, ""),
            "preview": build_map(room.map_id)[0],
            "players": [
                {"id": pid, "name": self._name_of(pid), "slot": i,
                 "host": pid == room.host_id,
                 "avatar": self.players[pid].avatar if self.players.get(pid) else None}
                for i, pid in enumerate(room.members)
            ],
            "max_players": MAX_PLAYERS,
        }

    def broadcast_lobby(self, room):
        for pid in room.members:
            self.send_pid(pid, self._lobby_payload(room, pid))

    def broadcast_queue(self):
        total = len(self.rooms.queue)
        for i, pid in enumerate(self.rooms.queue):
            self.send_pid(pid, {
                "type": "QUEUE_JOINED", "position": i + 1,
                "count": total, "needed": MAX_PLAYERS,
            })

    def send_game_start(self, room):
        now = time.time()
        snap = room.state.snapshot(now)
        avatars = {pid: self.players[pid].avatar
                   for pid in room.members
                   if self.players.get(pid) and self.players[pid].avatar}
        for pid in room.members:
            self.send_pid(pid, {
                "type": "GAME_START", "your_id": pid, "room": room.code,
                "map_id": room.map_id, "map_name": MAP_NAMES.get(room.map_id, ""),
                "snapshot": snap, "avatars": avatars,
            })


    def on_message(self, conn, msg):
        if not isinstance(msg, dict):
            log("WARN", "Pesan diabaikan karena bukan object JSON")
            return
        t = msg.get("type")
        if not isinstance(t, str):
            log("WARN", "Pesan diabaikan karena type tidak valid")
            return
        handler = {
            "HELLO": self._h_hello,
            "RECONNECT": self._h_reconnect,
            "SET_NAME": self._h_set_name,
            "SET_AVATAR": self._h_set_avatar,
            "HOST_GAME": self._h_host,
            "JOIN_GAME": self._h_join,
            "QUICK_MATCH": self._h_quick,
            "SET_MAP": self._h_set_map,
            "START_GAME": self._h_start,
            "LEAVE_ROOM": self._h_leave,
            "MOVE": self._h_move,
            "PLANT_BOMB": self._h_plant,
            "PING": self._h_ping,
        }.get(t)
        if handler:
            handler(conn, msg)
        else:
            log("WARN", f"Tipe pesan tak dikenal: {t}")

    def _h_ping(self, conn, msg):
        conn.send({"type": "PONG", "t": msg.get("t")})

    def _h_set_name(self, conn, msg):
        pid = conn.player_id
        p = self.players.get(pid) if pid else None
        if not p:
            return
        p.name = (msg.get("name") or p.name).strip()[:16] or p.name
        room = self.rooms.room_of(pid)
        if room and room.status == ROOM_LOBBY:
            self.broadcast_lobby(room)

    def _h_set_avatar(self, conn, msg):
        pid = conn.player_id
        p = self.players.get(pid) if pid else None
        if not p:
            return
        data = msg.get("data", "")
        # max ~20 KB base64 (≈ 64×64 JPEG)
        if isinstance(data, str) and len(data) <= 30000:
            p.avatar = data
        room = self.rooms.room_of(pid)
        if room and room.status == ROOM_LOBBY:
            self.broadcast_lobby(room)

    def _h_hello(self, conn, msg):
        name = (msg.get("name") or "Player").strip()[:16] or "Player"
        existing = self.players.get(conn.player_id)
        if existing:
            conn.send({"type": "WELCOME", "player_id": existing.id,
                       "name": existing.name})
            return
        pid = uuid.uuid4().hex[:12]
        p = PlayerSession(pid, name)
        p.conn = conn
        self.players[pid] = p
        conn.player_id = pid
        conn.send({"type": "WELCOME", "player_id": pid, "name": name})
        log("INFO", f"Player '{name}' terhubung (id={pid})")

    def _h_reconnect(self, conn, msg):
        pid = msg.get("player_id")
        name = (msg.get("name") or "Player").strip()[:16] or "Player"
        p = self.players.get(pid)
        room = self.rooms.room_of(pid) if pid else None
        now = time.time()
        ok = (p and room and room.status == ROOM_PLAYING and not p.connected
              and p.disconnected_at and now - p.disconnected_at <= RECONNECT_TIMEOUT)
        if ok:
            p.conn = conn
            p.connected = True
            p.disconnected_at = None
            conn.player_id = pid
            if room.state and pid in room.state.players:
                room.state.players[pid].connected = True
            conn.send({
                "type": "RECONNECT_OK", "player_id": pid, "room": room.code,
                "map_id": room.map_id, "map_name": MAP_NAMES.get(room.map_id, ""),
            })
            conn.send({
                "type": "GAME_START", "your_id": pid, "room": room.code,
                "map_id": room.map_id, "map_name": MAP_NAMES.get(room.map_id, ""),
                "snapshot": room.state.snapshot(now),
            })
            log("INFO", f"Player {p.name} reconnect ke Room {room.code}")
        else:
            conn.send({"type": "RECONNECT_FAIL"})
            self._h_hello(conn, {"name": name})

    def _h_host(self, conn, msg):
        pid = conn.player_id
        if not pid:
            return
        self.rooms.leave(pid)
        map_id = int(msg.get("map_id", 1))
        if map_id not in MAP_NAMES:
            map_id = 1
        room = self.rooms.create_room(pid, map_id=map_id, hidden=False)
        log("INFO", f"Player {self._name_of(pid)} membuat Room {room.code} (host)")
        self.broadcast_lobby(room)

    def _h_join(self, conn, msg):
        pid = conn.player_id
        if not pid:
            return
        code = str(msg.get("code", "")).strip()
        self.rooms.leave(pid)
        room, err = self.rooms.join_room(code, pid)
        if err:
            conn.send({"type": "JOIN_ERROR", "reason": err})
            log("INFO", f"Player {self._name_of(pid)} gagal join Room {code}: {err}")
            return
        log("INFO", f"Player {self._name_of(pid)} joined Room {room.code}")
        self.broadcast_lobby(room)

    def _h_quick(self, conn, msg):
        pid = conn.player_id
        if not pid:
            return
        self.rooms.leave(pid)
        self.rooms.enqueue(pid)
        log("INFO", f"Player {self._name_of(pid)} masuk antrean Quick Match "
                    f"({len(self.rooms.queue)}/{MAX_PLAYERS})")
        self.broadcast_queue()

    def _h_set_map(self, conn, msg):
        pid = conn.player_id
        room = self.rooms.room_of(pid)
        if not room or room.status != ROOM_LOBBY or room.host_id != pid:
            return
        map_id = int(msg.get("map_id", room.map_id))
        if map_id in MAP_NAMES:
            room.map_id = map_id
            self.broadcast_lobby(room)

    def _h_start(self, conn, msg):
        pid = conn.player_id
        room = self.rooms.room_of(pid)
        if not room or room.status != ROOM_LOBBY or room.host_id != pid:
            return
        if len(room.members) < 2:
            conn.send({"type": "INFO", "message": "Butuh minimal 2 pemain untuk memulai"})
            return
        self.rooms.start_game(room)
        log("INFO", f"Match started in Room {room.code} "
                    f"(map {room.map_id} '{MAP_NAMES.get(room.map_id)}', "
                    f"{len(room.members)} pemain)")
        self.send_game_start(room)

    def _h_leave(self, conn, msg):
        pid = conn.player_id
        if not pid:
            return
        room = self.rooms.leave(pid)
        if room and room.status == ROOM_LOBBY:
            self.broadcast_lobby(room)
        self.broadcast_queue()
        conn.send({"type": "LEFT_ROOM"})

    def _h_move(self, conn, msg):
        pid = conn.player_id
        room = self.rooms.room_of(pid)
        if not room or room.status != ROOM_PLAYING or not room.state:
            return
        col = int(msg.get("col", -1))
        row = int(msg.get("row", -1))
        result, pos = room.state.handle_move(pid, col, row, time.time())
        if result == "invalid":
            log("WARN", f"Invalid move request from {self._name_of(pid)} in Room {room.code}")
            conn.send({"type": "MOVE_REJECT", "col": pos[0], "row": pos[1]})

    def _h_plant(self, conn, msg):
        pid = conn.player_id
        room = self.rooms.room_of(pid)
        if not room or room.status != ROOM_PLAYING or not room.state:
            return
        room.state.handle_plant(pid, time.time())


    def on_disconnect(self, conn):
        pid = conn.player_id
        if not pid:
            return
        p = self.players.get(pid)
        if not p:
            return
        if p.conn is conn:
            p.conn = None
        room = self.rooms.room_of(pid)
        now = time.time()
        if room and room.status == ROOM_PLAYING:

            p.connected = False
            p.disconnected_at = now
            if room.state and pid in room.state.players:
                room.state.players[pid].connected = False
            log("WARN", f"Player {p.name} terputus dari Room {room.code} "
                        f"(idle, jendela reconnect {int(RECONNECT_TIMEOUT)}s)")
        else:
            left = self.rooms.leave(pid)
            if left and left.status == ROOM_LOBBY:
                self.broadcast_lobby(left)
            self.broadcast_queue()
            self.players.pop(pid, None)
            log("INFO", f"Player {p.name} terputus")


    def tick(self, now):

        formed = self.rooms.try_matchmake()
        for room in formed:
            log("INFO", f"Quick Match membentuk Room {room.code} "
                        f"({len(room.members)} pemain, map {room.map_id})")
            for pid in room.members:
                self.send_pid(pid, {"type": "MATCH_FOUND", "room": room.code})
            self.send_game_start(room)
        if formed:
            self.broadcast_queue()


        for room in list(self.rooms.rooms.values()):
            if room.status == ROOM_PLAYING and room.state:
                room.state.tick(now)
                self.broadcast_room(room, {"type": "STATE",
                                           "snapshot": room.state.snapshot(now)})
                if room.state.finished:
                    self.finish_match(room, now)

        self._expire_disconnects(now)
        self.rooms.cleanup(now)

    def finish_match(self, room, now):
        room.status = ROOM_FINISHED
        room.finished_at = now
        results = []
        for s in (room.state.final_standings or []):
            total = self.db.add_points(s["name"], s["points_delta"],
                                       won=(s["rank"] == 1))
            results.append({
                "name": s["name"], "rank": s["rank"],
                "points_delta": s["points_delta"], "total_points": total,
            })
        self.broadcast_room(room, {
            "type": "MATCH_OVER", "room": room.code,
            "results": results, "leaderboard": self.db.leaderboard(10),
        })
        log("INFO", f"Match ended in Room {room.code}")

    def _expire_disconnects(self, now):
        for pid, p in list(self.players.items()):
            if (not p.connected) and p.disconnected_at \
                    and now - p.disconnected_at > RECONNECT_TIMEOUT:
                room = self.rooms.room_of(pid)
                if room and room.status == ROOM_PLAYING and room.state:
                    room.state.force_eliminate(pid, now)
                    log("INFO", f"Player idle {p.name} dieliminasi di Room {room.code} "
                                f"(melewati batas reconnect)")
                self.rooms.leave(pid)
                self.players.pop(pid, None)

    def close(self):
        self.db.close()
