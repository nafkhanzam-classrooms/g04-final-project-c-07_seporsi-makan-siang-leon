import time
import random

from maps import (
    GRID_W, GRID_H, FREE, BREAKABLE, UNBREAKABLE,
    SPAWN_POINTS, build_map, scatter_breakables,
)


BOMB_FUSE = 2.5
EXPLOSION_DURATION = 0.5
BOMB_RANGE = 1
MOVE_COOLDOWN = 0.12
MAX_BOMBS = 1


POWERUP_DROP_CHANCE = 0.80
POWERUP_KINDS = ("range", "bomb")

DIRS_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))


POINTS_TABLE = {1: 100, 2: 50, 3: 0, 4: -30}


class Bomb:
    def __init__(self, owner_id, col, row, now, rng=BOMB_RANGE):
        self.owner_id = owner_id
        self.col = col
        self.row = row
        self.explode_at = now + BOMB_FUSE
        self.range = rng
        self.exploded = False


class Explosion:
    def __init__(self, cells, now):
        self.cells = cells
        self.expire_at = now + EXPLOSION_DURATION


class Player:
    def __init__(self, pid, name, slot, col, row):
        self.id = pid
        self.name = name
        self.slot = slot
        self.col = col
        self.row = row
        self.alive = True
        self.spectator = False
        self.connected = True
        self.last_move = 0.0
        self.death_order = None
        self.bombs_active = 0
        self.max_bombs = MAX_BOMBS
        self.range = BOMB_RANGE


class GameState:
    def __init__(self, map_id, player_infos, seed=None):
        self.map_id = map_id
        self.rng = random.Random(seed)
        self.grid, keep_open = build_map(map_id)
        scatter_breakables(self.grid, self.rng, keep_open)

        self.players = {}
        self.bombs = []
        self.explosions = []
        self.powerups = {}
        self.finished = False
        self.start_time = time.time()
        self.death_sequence = []
        self.final_standings = None

        for slot, (pid, name) in enumerate(player_infos[:4]):
            sc, sr = SPAWN_POINTS[slot]
            self.players[pid] = Player(pid, name, slot, sc, sr)


    def alive_players(self):
        return [p for p in self.players.values() if p.alive and not p.spectator]

    def active_explosion_cells(self):
        cells = set()
        for ex in self.explosions:
            cells.update(ex.cells)
        return cells

    def bomb_at(self, col, row):
        for b in self.bombs:
            if not b.exploded and b.col == col and b.row == row:
                return b
        return None


    def handle_move(self, pid, col, row, now):
        p = self.players.get(pid)
        if not p or not p.alive or p.spectator:
            return "ignore", None
        if now - p.last_move < MOVE_COOLDOWN:
            return "ignore", (p.col, p.row)

        dist = abs(col - p.col) + abs(row - p.row)
        if dist == 0:
            return "ignore", (p.col, p.row)
        if dist > 1:
            return "invalid", (p.col, p.row)
        if not (0 <= col < GRID_W and 0 <= row < GRID_H):
            return "invalid", (p.col, p.row)
        if self.grid[row][col] != FREE:
            return "invalid", (p.col, p.row)
        if self.bomb_at(col, row):
            return "invalid", (p.col, p.row)

        p.col, p.row = col, row
        p.last_move = now
        self._collect_powerup(p)
        return "ok", (col, row)

    def handle_plant(self, pid, now):
        p = self.players.get(pid)
        if not p or not p.alive or p.spectator:
            return False
        if p.bombs_active >= p.max_bombs:
            return False
        if self.bomb_at(p.col, p.row):
            return False
        self.bombs.append(Bomb(pid, p.col, p.row, now, p.range))
        p.bombs_active += 1
        return True

    def force_eliminate(self, pid, now=None):
        p = self.players.get(pid)
        if p and p.alive and not p.spectator:
            self._kill(p)
            self._check_winner()


    def tick(self, now):
        if self.finished:
            return

        self.explosions = [e for e in self.explosions if e.expire_at > now]


        queue = [b for b in self.bombs if not b.exploded and b.explode_at <= now]
        newly = []
        while queue:
            b = queue.pop()
            if b.exploded:
                continue
            cells = self._compute_blast(b)
            b.exploded = True
            newly.append((b, cells))
            for other in self.bombs:
                if not other.exploded and (other.col, other.row) in cells:
                    other.explode_at = now
                    queue.append(other)
        for b, cells in newly:
            owner = self.players.get(b.owner_id)
            if owner and owner.bombs_active > 0:
                owner.bombs_active -= 1
            self.explosions.append(Explosion(cells, now))
        self.bombs = [b for b in self.bombs if not b.exploded]


        fire = self.active_explosion_cells()
        for p in self.players.values():
            if p.alive and not p.spectator and (p.col, p.row) in fire:
                self._kill(p)


        self._check_winner()

    def _compute_blast(self, bomb):
        cells = [(bomb.col, bomb.row)]
        for dc, dr in DIRS_4:
            for step in range(1, bomb.range + 1):
                c = bomb.col + dc * step
                r = bomb.row + dr * step
                if not (0 <= c < GRID_W and 0 <= r < GRID_H):
                    break
                tile = self.grid[r][c]
                if tile == UNBREAKABLE:
                    break
                cells.append((c, r))
                if tile == BREAKABLE:
                    self.grid[r][c] = FREE
                    self._maybe_drop_powerup(c, r)
                    break
        return cells


    def _maybe_drop_powerup(self, col, row):

        if self.rng.random() < POWERUP_DROP_CHANCE:
            self.powerups[(col, row)] = self.rng.choice(POWERUP_KINDS)

    def _collect_powerup(self, p):
        kind = self.powerups.pop((p.col, p.row), None)
        if kind == "range":
            p.range += 1
        elif kind == "bomb":
            p.max_bombs += 1
        return kind

    def _kill(self, p):
        p.alive = False
        p.spectator = True
        self.death_sequence.append(p.id)
        p.death_order = len(self.death_sequence)

    def _check_winner(self):
        total = len(self.players)
        alive = self.alive_players()
        if total >= 2 and len(alive) <= 1:
            self._finish(alive)
        elif total == 1 and len(alive) == 0:
            self._finish(alive)

    def _finish(self, alive):
        if self.finished:
            return
        self.finished = True

        order = [p.id for p in alive] + list(reversed(self.death_sequence))
        seen, ranked = set(), []
        for pid in order:
            if pid not in seen:
                seen.add(pid)
                ranked.append(pid)
        self.final_standings = []
        for rank, pid in enumerate(ranked, start=1):
            p = self.players[pid]
            self.final_standings.append({
                "id": pid,
                "name": p.name,
                "rank": rank,
                "points_delta": POINTS_TABLE.get(rank, 0),
            })


    def snapshot(self, now):
        return {
            "grid": self.grid,
            "players": [
                {
                    "id": p.id, "name": p.name, "slot": p.slot,
                    "col": p.col, "row": p.row,
                    "alive": p.alive, "spectator": p.spectator,
                    "connected": p.connected,
                    "range": p.range, "max_bombs": p.max_bombs,
                }
                for p in self.players.values()
            ],
            "bombs": [
                {"col": b.col, "row": b.row, "owner": b.owner_id,
                 "fuse": max(0.0, round(b.explode_at - now, 2))}
                for b in self.bombs if not b.exploded
            ],
            "explosions": [list(c) for c in self.active_explosion_cells()],
            "powerups": [
                {"col": c, "row": r, "kind": k}
                for (c, r), k in self.powerups.items()
            ],
            "finished": self.finished,
            "elapsed": round(now - self.start_time, 1),
        }
