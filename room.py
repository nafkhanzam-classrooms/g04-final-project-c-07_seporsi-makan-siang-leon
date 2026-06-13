import random
import time

from game import GameState

ROOM_LOBBY = "LOBBY"
ROOM_PLAYING = "PLAYING"
ROOM_FINISHED = "FINISHED"

MAX_PLAYERS = 4
RECONNECT_TIMEOUT = 30.0
FINISHED_LINGER = 30.0


class Room:
    def __init__(self, code, host_id, map_id=1, hidden=False):
        self.code = code
        self.host_id = host_id
        self.map_id = map_id
        self.hidden = hidden
        self.status = ROOM_LOBBY
        self.members = []
        self.state = None
        self.created_at = time.time()
        self.finished_at = None

    def is_full(self):
        return len(self.members) >= MAX_PLAYERS


class RoomManager:
    def __init__(self, names_lookup):
        self.rooms = {}
        self.queue = []
        self.names = names_lookup


    def _new_code(self):
        while True:
            code = str(random.randint(100000, 999999))
            if code not in self.rooms:
                return code


    def create_room(self, host_id, map_id=1, hidden=False):
        code = self._new_code()
        room = Room(code, host_id, map_id, hidden)
        room.members.append(host_id)
        self.rooms[code] = room
        return room

    def join_room(self, code, pid):
        room = self.rooms.get(code)
        if not room:
            return None, "Room tidak ditemukan"
        if room.status != ROOM_LOBBY:
            return None, "Permainan sudah dimulai"
        if room.is_full():
            return None, "Room penuh"
        if pid not in room.members:
            room.members.append(pid)
        return room, None

    def start_game(self, room):
        infos = [(pid, self.names(pid)) for pid in room.members]
        room.state = GameState(room.map_id, infos)
        room.status = ROOM_PLAYING
        return room.state

    def room_of(self, pid):
        for room in self.rooms.values():
            if pid in room.members:
                return room
        return None

    def leave(self, pid):
        if pid in self.queue:
            self.queue.remove(pid)
        room = self.room_of(pid)
        if room and pid in room.members:
            if room.status == ROOM_PLAYING and room.state:
                room.state.force_eliminate(pid)
            room.members.remove(pid)
            if room.host_id == pid and room.members:
                room.host_id = room.members[0]
        return room


    def enqueue(self, pid):
        if pid not in self.queue:
            self.queue.append(pid)

    def try_matchmake(self):
        formed = []
        while len(self.queue) >= MAX_PLAYERS:
            group = [self.queue.pop(0) for _ in range(MAX_PLAYERS)]
            room = self.create_room(group[0], map_id=random.randint(1, 4), hidden=True)
            for pid in group[1:]:
                room.members.append(pid)
            self.start_game(room)
            formed.append(room)
        return formed


    def cleanup(self, now):
        drop = []
        for code, room in self.rooms.items():
            if room.status == ROOM_FINISHED and room.finished_at \
                    and now - room.finished_at > FINISHED_LINGER:
                drop.append(code)
            elif not room.members:
                drop.append(code)
        for code in drop:
            del self.rooms[code]
        return drop
