---
{
  "checkpoints": [
    {
      "desc": "Dimension D2.1 functional requirements",
      "id": "d2_1",
      "weight": 1
    },
    {
      "desc": "Dimension D2.2 functional requirements",
      "id": "d2_2",
      "weight": 1
    },
    {
      "desc": "Dimension D2.3 functional requirements",
      "id": "d2_3",
      "weight": 1
    },
    {
      "desc": "Dimension D2.4 functional requirements",
      "id": "d2_4",
      "weight": 1
    },
    {
      "desc": "Dimension D2.5 functional requirements",
      "id": "d2_5",
      "weight": 1
    }
  ],
  "difficulty": "medium",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Tetris",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "tetris",
  "variant_id": "var01",
  "instance_id": "tetris_var01"
}
---

# Game Specification

## Game Name
Tetris

---

# 1. Game Overview
Tetris is a grid-based logic puzzle game. The player controls continuously falling tetrominoes within a fixed board, moving them left or right, rotating them clockwise, and performing soft drops so that the pieces stack at the bottom of the board or on top of existing fixed blocks.

Whenever an entire row is filled, that row is cleared, all rows above it move downward, and the player earns points.

The game uses a fixed 10 × 20 grid board. Each tetromino consists of exactly 4 blocks, and both the currently falling piece and all fixed blocks must remain aligned with the board grid.

The game includes the 7 standard tetrominoes: I, O, T, S, Z, J, and L.

The interface uses a left-right layout. The board is displayed on the left, while the information area on the right displays Score, Lines, the Next piece preview, control instructions, and Game Over feedback.

During initialization, both the current piece and the Next piece are randomly generated. After the current piece is locked and row-clearing processing is completed, the Next piece becomes the new current piece and a new Next piece is generated.

The game has no victory state. The player's objective is to achieve the highest possible Score and clear as many Lines as possible before reaching Game Over.

The game does not include hard drop, Hold, ghost pieces, wall kicks, a level system, increasing speed, combo rewards, T-spin scoring, multiple levels, special pieces, items, or a time limit.

---

# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a left-right partitioned layout. It does not use separate top information or bottom instruction areas.

## 2.1 Board Area
The board area has:
- Top-left coordinate: `(60, 80)`
- Size: 300 × 600 px
- Bottom-right coordinate: `(360, 680)`
- Grid: 10 columns × 20 rows
- Cell size: 30 × 30 px

The board uses grid coordinates `(row, col)`:
- Top-left cell: `(0, 0)`
- Bottom-right cell: `(19, 9)`

For a cell at `(row, col)`, its top-left window coordinate is:
`x = 60 + col × 30`
`y = 80 + row × 30`

The board background uses a dark color such as `#111111`. Grid lines may use dark gray such as `#444444`, and the board should have a clearly visible white or light-gray outer border.

## 2.2 Information Area
The information area has:
- Top-left coordinate: `(390, 80)`
- Size: 160 × 600 px

It uses a light-gray or white background such as `#EDEDED` or `#F7F7F7`, with dark text such as `#222222`.

During `playing`, the information area displays:

| Element | Suggested Position | Font / Size |
|---|---|---|
| `Score: X` | `(400, 100)` | 32 px |
| `Lines: X` | `(400, 145)` | 32 px |
| `Next` | `(400, 220)` | 32 px |
| Next Preview Box | `(420, 260)` | 4 × 4 cells, each 25 × 25 px |
| `Move: ← / →` | `(400, 410)` | 22 px |
| `Rotate: ↑` | `(400, 440)` | 22 px |
| `Soft Drop: ↓` | `(400, 470)` | 22 px |
| `Restart: R` | `(400, 500)` | 22 px |

## 2.3 Next Preview
The Next preview uses a 4 × 4 grid:
- Top-left coordinate: `(420, 260)`
- Total size: 100 × 100 px
- Preview cell size: 25 × 25 px

The Next piece is drawn according to its original 4 × 4 local matrix. No additional scaling, rotation, or shape redesign is required.

## 2.4 Game Over Display
After the game enters `game_over`, the information area continues to display the final Score, Lines, and Next piece.

It additionally displays:
`Game Over`
`Press R to Restart`

Suggested placement begins near `(400, 540)`.

Font sizes:
- `Game Over`: 32 px
- `Press R to Restart`: 22 px

## 2.5 Tetromino Colors
The 7 tetrominoes use the following fixed colors:

| Tetromino | Color |
|---|---|
| I | Cyan `#00CFFF` |
| O | Yellow `#FFD500` |
| T | Purple `#A259FF` |
| S | Green `#2ECC71` |
| Z | Red `#E74C3C` |
| J | Blue `#2D7FF9` |
| L | Orange `#F39C12` |

All tetromino blocks are displayed as filled colored squares aligned with the board grid. The current piece and fixed blocks use the same color rule according to tetromino type.

At the start of the game:
- Board: empty
- Score: 0
- Lines: 0
- `current_piece`: randomly generated
- `next_piece`: randomly generated
- Current piece spawn position: top center of the board
- Next piece: displayed in the preview area

---

# 3. Game Objects & States
The main game objects and state variables include the board, current piece, Next piece, fixed blocks, Score, Lines, automatic fall timer, and game state.

## 3.1 Board
The board contains 10 columns × 20 visible rows, for a total of 200 visible cells.

Each cell is either empty or occupied by a fixed block.

The board records:
- Rows: 0–19
- Columns: 0–9

The board does not scroll, expand, or randomly change size.

## 3.2 Current Piece
The current piece is the falling tetromino controlled by the player.

Its state includes:
- Tetromino type
- Local 4 × 4 shape
- Board position
- Color
- Current orientation

Each piece contains exactly 4 occupied blocks.

Before locking, the current piece is not part of the board's fixed cells.

The current piece can:
- Move left.
- Move right.
- Move downward.
- Rotate clockwise.

## 3.3 Next Piece
The Next piece is the tetromino that will become the next current piece. It is displayed in the Next preview area and cannot be directly controlled or manually swapped.

After the current piece is successfully locked and row clearing is completed:
1. The existing `next_piece` becomes `current_piece`.
2. The new current piece is placed at the fixed spawn position.
3. A new `next_piece` is randomly generated.
4. The Next preview is updated.

## 3.4 Fixed Blocks
Fixed blocks are tetromino blocks that have been locked into the board.

They no longer move or rotate and participate in collision detection and full-row detection.

## 3.5 Score
Score starts at 0.

Each cleared row increases Score by 100.

Examples:
- 1 cleared row: +100
- 2 cleared rows: +200
- 4 cleared rows: +400

If multiple rows are cleared simultaneously, Score increases according to the actual number of cleared rows.

Soft drop, horizontal movement, rotation, and locking a piece do not directly increase Score.

## 3.6 Lines
Lines starts at 0.

Each cleared row increases Lines by 1.

If multiple rows are cleared simultaneously, Lines increases by the number of rows actually cleared.

## 3.7 Game State
The game contains two internal states:
- `playing`
- `game_over`

During `playing`, the current piece automatically falls and the player can move, rotate, and soft-drop it.

During `game_over`, automatic falling stops, arrow-key input has no effect, and the information area displays `Game Over` and `Press R to Restart`.

R is effective in both states.

## 3.8 Tetromino Representation
All 7 tetrominoes use a 4 × 4 local matrix. Local coordinates use `(r, c)`, where:
`0 ≤ r < 4`
`0 ≤ c < 4`

The initial occupied local coordinates are:

| Tetromino | Initial Local Coordinates |
|---|---|
| I | `(1,0), (1,1), (1,2), (1,3)` |
| O | `(1,1), (1,2), (2,1), (2,2)` |
| T | `(1,1), (2,0), (2,1), (2,2)` |
| S | `(1,1), (1,2), (2,0), (2,1)` |
| Z | `(1,0), (1,1), (2,1), (2,2)` |
| J | `(1,0), (2,0), (2,1), (2,2)` |
| L | `(1,2), (2,0), (2,1), (2,2)` |

The corresponding initial matrices are:

```text
I:
....
XXXX
....
....

O:
....
.XX.
.XX.
....

T:
....
.X..
XXX.
....

S:
....
.XX.
XX..
....

Z:
....
XX..
.XX.
....

J:
....
X...
XXX.
....

L:
....
..X.
XXX.
....
```

`X` indicates an occupied local cell and `.` indicates an empty local cell.

---

# 4. Player Interaction
The player uses the left arrow key, right arrow key, up arrow key, down arrow key, and R.

Space is not used.

## 4.1 Horizontal Movement
The left arrow key attempts to move the current piece 1 cell left.

The right arrow key attempts to move the current piece 1 cell right.

Before either movement is applied, the proposed position must pass the validity check.

If valid, move the current piece by 1 cell. If invalid, leave the piece unchanged.

A failed horizontal movement does not cause the piece to lock.

## 4.2 Rotation
The up arrow key attempts to rotate the current piece 90° clockwise.

If the rotated position is valid, apply the rotation.

If invalid, keep the current position and orientation unchanged.

The O piece remains unchanged after rotation.

The game does not use wall kicks.

## 4.3 Soft Drop
The down arrow key performs an additional attempt to move the current piece downward by 1 cell.

If the downward movement is valid:
- Move the piece downward by 1 cell.

If the downward movement is invalid:
- Immediately begin the locking process.

Soft drop does not increase Score.

A successful soft drop does not reset the 0.45-second automatic fall timer.

## 4.4 Continuous Key Input
For left, right, and down:
- A new key-down immediately triggers one corresponding action.
- If the key remains held, the action may repeat at most once every 0.12 seconds.

For up:
- Rotation occurs only on a new key-down event.
- Holding the key does not repeatedly rotate the piece.

## 4.5 Restart
R is effective in both `playing` and `game_over`.

Restart:
- Clears the board.
- Resets Score to 0.
- Resets Lines to 0.
- Randomly generates new `current_piece` and `next_piece`.
- Spawns the current piece at the fixed spawn position.
- Resets the automatic fall timer.
- Returns the game state to `playing`.
- Restores the normal information display.

---

# 5. Core Rules & Mechanics

## 5.1 Board & Piece Coordinates
The board uses coordinates `(row, col)`:
`0 ≤ row < 20`
`0 ≤ col < 10`

The current piece uses a 4 × 4 local matrix whose top-left position is `(piece_row, piece_col)`.

For an occupied local cell `(r, c)`:
`board_row = piece_row + r`
`board_col = piece_col + c`

## 5.2 Spawn Position
All tetrominoes use the same spawn position:
`spawn_row = -1`
`spawn_col = 3`

Part of a newly spawned piece may initially lie above the visible board.

An occupied block with `board_row < 0` is allowed while the piece is active, is not drawn, and is not considered invalid solely because its row is negative.

## 5.3 Piece Validity
A proposed position is valid only if every occupied block satisfies:
1. `0 ≤ board_col < 10`
2. `board_row < 20`
3. If `board_row ≥ 0`, the corresponding board cell is not already occupied by a fixed block.

Negative `board_row` values are allowed.

## 5.4 Automatic Falling
The current piece automatically attempts to move downward by 1 cell every 0.45 seconds.

If the downward position is valid, the piece moves down by 1 cell.

If it is invalid, the piece immediately enters the locking process.

The game does not use a lock delay.

## 5.5 Lock Trigger
A piece enters the locking process only when a downward movement attempt fails.

This includes:
- Failed automatic fall.
- Failed soft drop.

The following do not cause locking:
- Failed left movement.
- Failed right movement.
- Failed rotation.

## 5.6 Clockwise Rotation
Except for O, all tetrominoes rotate clockwise using the 4 × 4 local matrix.

Each occupied local coordinate transforms as:
`(r, c) → (c, 3 - r)`

The O piece remains unchanged after rotation.

If the rotated position would extend beyond the left or right board boundary, extend below the board, or overlap a fixed block, the rotation fails.

No wall kick or automatic positional adjustment is applied.

## 5.7 Locking Above the Board
When a downward movement fails and the piece enters the locking process, all 4 occupied blocks are checked first.

If any occupied block satisfies:
`board_row < 0`

then:
- Immediately enter `game_over`.
- Do not write the piece into the board.
- Do not clear rows.
- Do not promote the Next piece.
- Do not generate a new Next piece.

## 5.8 Writing a Piece into the Board
If all 4 occupied blocks satisfy:
`0 ≤ board_row < 20`

the blocks are written into the board and become fixed.

After locking, the piece can no longer move or rotate.

## 5.9 Row Clearing
Immediately after a piece is written into the board:
1. Check all 20 rows.
2. Identify every row whose 10 cells are occupied.
3. Clear all full rows simultaneously.
4. Move all rows above them downward by the corresponding number of cleared rows.
5. Insert the same number of empty rows at the top.
6. Update Score and Lines.

For each cleared row:
- Score += 100
- Lines += 1

If multiple rows are cleared at once, all are processed together.

## 5.10 Next Piece Promotion
After row clearing:
1. Promote `next_piece` to `current_piece`.
2. Place the new current piece at `spawn_row = -1, spawn_col = 3`.
3. Randomly generate a new `next_piece`.
4. Update the Next preview.

The player cannot manually exchange the current piece and Next piece.

## 5.11 Spawn Collision
After the new current piece is placed at the spawn position, check only its visible occupied cells against existing fixed blocks.

If any occupied cell with:
`board_row ≥ 0`

overlaps an existing fixed block, immediately enter `game_over`.

Occupied cells with `board_row < 0` are excluded from this spawn-overlap check.

## 5.12 Failure Conditions
The game enters `game_over` if either condition occurs:
1. A piece needs to lock while at least one occupied block still has `board_row < 0`.
2. A newly spawned current piece has at least one visible occupied block overlapping a fixed block.

`game_over` is the only terminal state.

## 5.13 Excluded Mechanics
The game does not include a time limit, level system, increasing speed, hard drop, Hold, ghost piece, wall kick, combo rewards, T-spin scoring, multiple levels, special pieces, or items.

---

# 6. Game Flow & Progression
At initialization, the game creates the 600 × 800 px window, board area, information area, empty 10 × 20 board, Score, Lines, current piece, Next piece, automatic fall timer, and game state.

The initial state is:
- Board: empty
- Score: 0
- Lines: 0
- `current_piece`: randomly generated
- `next_piece`: randomly generated
- Current piece position: `spawn_row = -1, spawn_col = 3`
- Game state: `playing`

While `playing`, the current piece automatically attempts to fall once every 0.45 seconds.

The player may also move it left or right, rotate it clockwise, or perform soft drops. Every proposed move or rotation is validated before being applied.

If a horizontal movement or rotation is invalid, the operation is ignored.

If an automatic fall or soft-drop attempt fails, the current piece immediately enters the locking process.

During locking:
1. Check whether any occupied block remains above the visible board.
2. If so, enter `game_over`.
3. Otherwise, write all 4 blocks into the board.
4. Detect and clear all full rows.
5. Update Score and Lines.
6. Promote `next_piece` to `current_piece`.
7. Spawn the new current piece at the fixed spawn position.
8. Generate a new `next_piece`.
9. Update the Next preview.
10. Check the new current piece for visible-cell overlap with fixed blocks.
11. If such an overlap exists, enter `game_over`.

A successful soft drop does not reset the automatic fall timer.

After entering `game_over`:
- Automatic falling stops.
- The current piece stops moving and rotating.
- Soft drop has no effect.
- Arrow-key input has no effect.
- Final Score remains visible.
- Final Lines remains visible.
- The Next preview remains visible.
- `Game Over` and `Press R to Restart` are displayed.

Pressing R fully resets the board, Score, Lines, current piece, Next piece, automatic fall timer, and game state.

The automatic fall interval remains fixed at 0.45 seconds throughout the game.

Board dimensions, cell size, tetromino types and colors, spawn position, rotation rule, row-clearing rule, and failure conditions remain fixed.

---

# 7. Goal, Feedback & Termination
The player's goal is to control continuously falling tetrominoes, stack them efficiently, clear complete rows, and achieve the highest possible Score and Lines count.

The game has no victory endpoint.

The information area displays:
`Score: X`
`Lines: X`

Score starts at 0 and increases by 100 for each cleared row.

Lines starts at 0 and increases by 1 for each cleared row.

Input feedback includes:
- `←`: attempt to move 1 cell left.
- `→`: attempt to move 1 cell right.
- `↑`: attempt to rotate 90° clockwise.
- `↓`: attempt one additional downward movement.

Invalid horizontal movement or rotation has no effect.

A failed downward movement immediately begins the locking process.

Every 0.45 seconds, the current piece automatically attempts to move downward by 1 cell.

When one or more full rows are cleared, those rows disappear, rows above move downward, empty rows are inserted at the top, and Score and Lines update immediately.

The Next preview always displays the upcoming tetromino.

After a successful lock and row-clear process, the previous Next piece becomes the current piece and a new Next piece is generated.

The game enters `game_over` if:
- A piece must lock while at least one occupied block remains above the visible board.
- A newly spawned current piece has a visible occupied block overlapping a fixed block.

After Game Over:
`Game Over`
`Press R to Restart`

All active gameplay stops and only R is used to restart.

Restart clears the board, resets Score and Lines to 0, generates new current and Next pieces, resets the automatic fall timer, and returns the game state to `playing`.

---

# 8. Functional Checkpoints
