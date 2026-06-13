import sqlite3
import threading


class Database:
    def __init__(self, path: str = "bomberman.db"):
        self.path = path
        self.lock = threading.Lock()

        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                name   TEXT PRIMARY KEY,
                points INTEGER NOT NULL DEFAULT 0,
                wins   INTEGER NOT NULL DEFAULT 0,
                games  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def add_points(self, name: str, delta: int, won: bool = False) -> int:
        with self.lock:
            cur = self.conn.execute(
                "SELECT points, wins, games FROM players WHERE name=?", (name,)
            )
            row = cur.fetchone()
            if row is None:
                points, wins, games = 0, 0, 0
                self.conn.execute(
                    "INSERT INTO players(name, points, wins, games) VALUES (?,0,0,0)",
                    (name,),
                )
            else:
                points, wins, games = row
            points = max(0, points + delta)
            wins += 1 if won else 0
            games += 1
            self.conn.execute(
                "UPDATE players SET points=?, wins=?, games=? WHERE name=?",
                (points, wins, games, name),
            )
            self.conn.commit()
            return points

    def leaderboard(self, limit: int = 10):
        with self.lock:
            cur = self.conn.execute(
                "SELECT name, points, wins, games FROM players "
                "ORDER BY points DESC, wins DESC, games ASC LIMIT ?",
                (limit,),
            )
            return [
                {"name": n, "points": p, "wins": w, "games": g}
                for (n, p, w, g) in cur.fetchall()
            ]

    def close(self):
        with self.lock:
            self.conn.close()
