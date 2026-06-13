import time
import uuid

from room import RoomManager, ROOM_LOBBY, ROOM_PLAYING, ROOM_FINISHED, MAX_PLAYERS
from maps import MAP_NAMES, build_map


def log(level, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


class PlayerSession:
    def __init__(self, pid, name):
        self.id = pid
        self.name = name
        self.conn = None


class GameCoordinator:
    def __init__(self):
        self.players = {}
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
            "is_host": recipient_pid == room.host_id,
            "map_id": room.map_id,
            "map_name": MAP_NAMES.get(room.map_id, ""),
            "players": [
                {"id": pid, "name": self._name_of(pid), "slot": i,
                 "host": pid == room.host_id}
                for i, pid in enumerate(room.members)
            ],
            "max_players": MAX_PLAYERS,
        }

    def broadcast_lobby(self, room):
        for pid in room.members:
            self.send_pid(pid, self._lobby_payload(room, pid))

    def send_game_start(self, room):
        now = time.time()
        snap = room.state.snapshot(now)
        for pid in room.members:
            self.send_pid(pid, {
                "type": "GAME_START", "your_id": pid, "room": room.code,
                "map_id": room.map_id, "map_name": MAP_NAMES.get(room.map_id, ""),
                "snapshot": snap,
            })

    def on_message(self, conn, msg):
        if not isinstance(msg, dict):
            return
        t = msg.get("type")
        if not isinstance(t, str):
            return
        handler = {
            "HELLO":      self._h_hello,
            "SET_NAME":   self._h_set_name,
            "HOST_GAME":  self._h_host,
            "JOIN_GAME":  self._h_join,
            "START_GAME": self._h_start,
            "LEAVE_ROOM": self._h_leave,
            "MOVE":       self._h_move,
            "PLANT_BOMB": self._h_plant,
        }.get(t)
        if handler:
            handler(conn, msg)

    def _h_hello(self, conn, msg):
        name = (msg.get("name") or "Player").strip()[:16] or "Player"
        pid = uuid.uuid4().hex[:12]
        p = PlayerSession(pid, name)
        p.conn = conn
        self.players[pid] = p
        conn.player_id = pid
        conn.send({"type": "WELCOME", "player_id": pid, "name": name})
        log("INFO", f"Player '{name}' terhubung (id={pid})")

    def _h_set_name(self, conn, msg):
        pid = conn.player_id
        p = self.players.get(pid) if pid else None
        if not p:
            return
        p.name = (msg.get("name") or p.name).strip()[:16] or p.name
        room = self.rooms.room_of(pid)
        if room and room.status == ROOM_LOBBY:
            self.broadcast_lobby(room)

    def _h_host(self, conn, msg):
        pid = conn.player_id
        if not pid:
            return
        self.rooms.leave(pid)
        room = self.rooms.create_room(pid, map_id=1, hidden=False)
        log("INFO", f"Player {self._name_of(pid)} membuat Room {room.code}")
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
            return
        log("INFO", f"Player {self._name_of(pid)} bergabung ke Room {room.code}")
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
        log("INFO", f"Game dimulai di Room {room.code} ({len(room.members)} pemain)")
        self.send_game_start(room)

    def _h_leave(self, conn, msg):
        pid = conn.player_id
        if not pid:
            return
        room = self.rooms.leave(pid)
        if room and room.status == ROOM_LOBBY:
            self.broadcast_lobby(room)
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
        p = self.players.pop(pid, None)
        if not p:
            return
        room = self.rooms.leave(pid)
        if room and room.status == ROOM_LOBBY:
            self.broadcast_lobby(room)
        log("INFO", f"Player {p.name} terputus")

    def tick(self, now):
        for room in list(self.rooms.rooms.values()):
            if room.status == ROOM_PLAYING and room.state:
                room.state.tick(now)
                self.broadcast_room(room, {"type": "STATE",
                                           "snapshot": room.state.snapshot(now)})
                if room.state.finished:
                    self._finish_match(room, now)
        self.rooms.cleanup(now)

    def _finish_match(self, room, now):
        room.status = ROOM_FINISHED
        room.finished_at = now
        results = [
            {"name": s["name"], "rank": s["rank"],
             "points_delta": s["points_delta"], "total_points": 0}
            for s in (room.state.final_standings or [])
        ]
        self.broadcast_room(room, {
            "type": "MATCH_OVER", "room": room.code,
            "results": results, "leaderboard": [],
        })
        log("INFO", f"Match selesai di Room {room.code}")

    def close(self):
        pass
