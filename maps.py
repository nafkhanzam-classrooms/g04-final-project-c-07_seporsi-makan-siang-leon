FREE = 0
BREAKABLE = 1
UNBREAKABLE = 2

GRID_W = 13
GRID_H = 13
CENTER = GRID_W // 2


SPAWN_POINTS = [
    (1, 1),
    (GRID_W - 2, GRID_H - 2),
    (GRID_W - 2, 1),
    (1, GRID_H - 2),
]

MAP_NAMES = {
    1: "Classic",
    2: "Open ga mas?",
    3: "The Kumbang",
    4: "X aja",
}

BREAKABLE_DENSITY = 0.70


def _blank_grid():
    g = [[FREE for _ in range(GRID_W)] for _ in range(GRID_H)]
    for c in range(GRID_W):
        g[0][c] = UNBREAKABLE
        g[GRID_H - 1][c] = UNBREAKABLE
    for r in range(GRID_H):
        g[r][0] = UNBREAKABLE
        g[r][GRID_W - 1] = UNBREAKABLE
    return g


def _map_classic():
    g = _blank_grid()
    for r in range(2, GRID_H - 1, 2):
        for c in range(2, GRID_W - 1, 2):
            g[r][c] = UNBREAKABLE
    return g, set()


def _map_open_center():
    g = _blank_grid()
    lo, hi = 3, 9
    keep_open = set()
    for r in range(lo, hi + 1):
        for c in range(lo, hi + 1):
            on_frame = (r in (lo, hi)) or (c in (lo, hi))
            if on_frame:
                g[r][c] = UNBREAKABLE
            else:
                keep_open.add((c, r))

    g[lo][CENTER] = FREE
    g[hi][CENTER] = FREE
    g[CENTER][lo] = FREE
    g[CENTER][hi] = FREE
    return g, keep_open


def _map_kumbang():
    g = _blank_grid()
    cells = set()

    def add_sym(c, r):

        for cc in {c, GRID_W - 1 - c}:
            for rr in {r, GRID_H - 1 - r}:
                cells.add((cc, rr))

    add_sym(6, 3)
    add_sym(6, 4)
    add_sym(6, 5)
    add_sym(6, 6)
    add_sym(5, 4)
    add_sym(5, 5)
    add_sym(5, 6)
    add_sym(5, 3)
    add_sym(4, 5)
    add_sym(4, 3)

    for (c, r) in cells:
        g[r][c] = UNBREAKABLE
    return g, set()


def _map_cross():
    g = _blank_grid()
    for r in range(2, GRID_H - 2):
        for c in range(2, GRID_W - 2):
            if c == r or c == (GRID_W - 1 - r):
                g[r][c] = UNBREAKABLE
    return g, set()


_BUILDERS = {
    1: _map_classic,
    2: _map_open_center,
    3: _map_kumbang,
    4: _map_cross,
}


def build_map(map_id: int):
    builder = _BUILDERS.get(map_id, _map_classic)
    return builder()


def spawn_clear_cells():
    clear = set()
    for (sc, sr) in SPAWN_POINTS:
        clear.add((sc, sr))

        dc = 1 if sc < CENTER else -1
        dr = 1 if sr < CENTER else -1
        clear.add((sc + dc, sr))
        clear.add((sc, sr + dr))
    return clear


def scatter_breakables(grid, rng, keep_open=None):
    protected = spawn_clear_cells()
    if keep_open:
        protected |= keep_open
    for r in range(GRID_H):
        for c in range(GRID_W):
            if grid[r][c] != FREE:
                continue
            if (c, r) in protected:
                continue
            if rng.random() < BREAKABLE_DENSITY:
                grid[r][c] = BREAKABLE
    return grid
