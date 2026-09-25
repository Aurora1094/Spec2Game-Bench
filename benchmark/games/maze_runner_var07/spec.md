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
  "difficulty": "easy",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Maze Runner",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "maze_runner",
  "variant_id": "var07",
  "instance_id": "maze_runner_var07"
}
---

# Game Specification

## Game Name
Maze Runner

---

# 1. Game Overview
Maze Runner is a single-screen, time-limited spatial navigation game. The player moves through a fixed grid maze and must reach the exit before the 30-second countdown expires.

The entire maze is visible from the beginning. The player must examine the wall and pathway layout, plan a route, and navigate from the starting cell to the exit as quickly as possible.

The game uses a fixed map. The maze is not randomly generated, the map does not scroll, and no part of the map is hidden.

Movement is grid-based rather than continuous. The player uses the arrow keys to move between adjacent cells.

For every movement attempt:
- If the target cell is a pathway or the exit, the movement succeeds.
- If the target cell is a wall or outside the map boundary, the player remains in the current cell and Time is reduced by an additional 1 second.

The player wins by entering the exit while Time is still above 0. If Time reaches 0 before the exit has been successfully reached, the player loses.

A custom rule in this game is held-key movement. When an arrow key changes from not pressed to pressed, one movement attempt occurs immediately. If the same key remains held, additional movement attempts occur at fixed 0.15-second intervals rather than every frame.

---

# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into three areas:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area
The top information area displays the remaining Time on the left and the number of successful Steps on the right:

`Time: X`
`Steps: X`

At the start of the game:
`Time: 30`
`Steps: 0`

Both text elements use a font size of 40 px and must have sufficient spacing so that they do not overlap.

Time is displayed as a non-negative whole number. Decimal and negative values are never shown.

## 2.2 Main Gameplay Area
The main gameplay area has a size of 600 × 600 px and covers:
- Top-left: `(0, 100)`
- Bottom-right: `(600, 700)`

The maze uses a fixed 15 × 15 grid. Each cell measures 40 × 40 px, so the grid exactly fills the gameplay area.

The fixed maze is:

```text
###############
#P    #       #
### # # ##### #
#   # #     # #
# ### ##### # #
# #     #   # #
# # ### # ### #
#   # # #     #
##### # ##### #
#     #     # #
# ######### # #
#       #   # #
# ##### # ### #
#     #     E #
###############
```

The map legend is:

| Symbol | Meaning |
|---|---|
| `#` | Wall; cannot be entered |
| Space | Pathway; can be entered |
| `P` | Player starting cell; treated as a pathway after initialization |
| `E` | Exit; entering this cell while Time > 0 triggers victory |

Grid coordinates use `(row, col)`, with `(0, 0)` at the top-left and `(14, 14)` at the bottom-right.

For a cell at `(row, col)`, its top-left window coordinate is:
`x = col × 40`
`y = 100 + row × 40`

The player's initial grid position is `(row=1, col=1)`, corresponding to cell center `(60, 160)`.

The exit is located at `(row=13, col=12)`, corresponding to cell center `(500, 640)`.

The player is displayed as a blue or green circle with a radius of 15 px and is always centered within the current grid cell.

Walls use dark-gray or black blocks, pathways use a light-colored background, and the exit is displayed as a green block or door-shaped icon and may show the letter `E`. Light-gray grid lines should remain visible.

## 2.3 Bottom Instruction Area
While the game is in the `running` state, the bottom instruction area displays:
`Move: ↑ / ↓ / ← / →`
`Invalid move: -1s    Restart: R`

Both lines use a font size of 28 px and should be centered.

After the player wins, it displays:
`You Escaped!`
`Press R to Restart`

After the player loses, it displays:
`Game Over`
`Press R to Restart`

`You Escaped!` and `Game Over` use a font size of 40 px. `Press R to Restart` uses a font size of 28 px.

The top information area and bottom instruction area use a light-gray background. The gameplay area uses light-colored pathways and dark-colored walls. All text should use a dark or otherwise high-contrast color.

---

# 3. Game Objects & States
The main game objects and state variables include the fixed maze, player, exit, Time, Steps, held-key repeat state, and game state.

## 3.1 Maze Map
The game uses one fixed 15 × 15 map. It is not randomly generated, does not change during gameplay, does not scroll, and is fully visible from the beginning.

Enterable cells are:
- Pathway cells
- `P`
- `E`

Non-enterable positions are:
- `#`
- Any position outside the map

## 3.2 Player
The player:
- Starts at `(row=1, col=1)`.
- Uses a circular visual representation with a radius of 15 px.
- Always remains centered within a grid cell.
- Uses grid-based rather than continuous movement.
- Can move only in the four cardinal directions.

Every successful movement advances exactly one grid cell.

## 3.3 Exit
The exit is fixed at `(row=13, col=12)` and is an enterable cell.

If the player successfully enters the exit while Time is still above 0, the game immediately enters `won`.

## 3.4 Time
The initial value is:
`Time = 30`

Time decreases according to actual elapsed time while the game state is `running`.

In addition to the normal countdown, each movement attempt into a wall or outside the map immediately reduces Time by an additional 1 second.

The displayed Time:
- Uses whole seconds only.
- Never becomes negative.
- Has a minimum displayed value of 0.

If an invalid movement penalty reduces Time to 0 or below, displayed Time is set to 0 and the game immediately enters `lost`.

After the game enters `won` or `lost`, Time stops changing.

## 3.5 Steps
The initial value is:
`Steps = 0`

Steps counts successful movements only.

Whenever the player successfully enters a pathway cell or the exit:
`Steps += 1`

Steps does not increase when the target cell is a wall, outside the map, or when directional input occurs after the game has ended.

Invalid movement penalties affect Time only and never increase Steps.

Steps is informational only and does not otherwise affect victory or failure.

## 3.6 Game State
The game contains three states:
- `running`
- `won`
- `lost`

During `running`, player movement is enabled, Time decreases, and Steps may increase.

In `won`, the player has reached the exit before Time expired; movement stops, Time stops, and Steps no longer changes.

In `lost`, Time has reached 0 either through the normal countdown or an invalid-movement penalty before a successful exit movement was completed. Movement stops, Time remains 0, and Steps no longer changes.

---

# 4. Player Interaction
The player uses the four arrow keys and R.

## 4.1 Directional Movement
The controls are:
- ↑: move one cell upward
- ↓: move one cell downward
- ←: move one cell left
- →: move one cell right

Movement is strictly grid-based and diagonal movement is not supported.

For each movement attempt:
1. Determine the adjacent target cell.
2. Check whether it lies within the map.
3. Check whether the target cell is enterable.
4. If valid, move the player into the target cell.
5. If invalid, leave the player in the current cell and reduce Time by 1 second.

A successful move increases Steps by 1. A failed move does not change Steps.

## 4.2 Key Press & Hold Behavior
When an arrow key changes from not pressed to pressed, one movement attempt occurs immediately.

If the same arrow key remains held, the game waits 0.15 seconds after the initial attempt and then performs additional movement attempts at fixed 0.15-second intervals.

Movement attempts do not occur every frame.

Every repeated attempt independently checks whether the target cell is enterable.

Therefore, holding a direction against a wall produces repeated failed movement attempts at 0.15-second intervals. Each failed attempt leaves the player in place, does not increase Steps, and reduces Time by an additional 1 second.

## 4.3 Invalid Movement
If the target cell is a wall or outside the map boundary:
- The player remains in the current cell.
- Steps does not increase.
- Time is immediately reduced by an additional 1 second.
- The player is not returned to the starting position.

If Time remains above 0 after the penalty, the game continues.

If the penalty causes Time to reach 0 or below:
- Set displayed Time to 0.
- Immediately enter `lost`.
- Do not process any further movement outcome during that update.

## 4.4 Restart
R is effective in all three states: `running`, `won`, and `lost`.

Pressing R fully restarts the game:
- Player returns to `(row=1, col=1)`.
- Time returns to 30.
- Steps returns to 0.
- Held-key repeat state is reset.
- Game state returns to `running`.
- The same fixed map is restored.
- Normal gameplay instructions are displayed.

After entering `won` or `lost`, arrow-key input has no effect.

---

# 5. Core Rules & Mechanics

## 5.1 Grid Movement
The maze contains 15 × 15 cells. Each movement attempt changes the player's position by exactly one adjacent cell if the target is valid.

Possible movement deltas are:
- Up: `(-1, 0)`
- Down: `(1, 0)`
- Left: `(0, -1)`
- Right: `(0, 1)`

The player cannot move diagonally.

## 5.2 Cell Validation
Before movement is applied, the target cell must be validated.

A target cell is enterable if it contains:
- Pathway space
- `P`
- `E`

A target cell is not enterable if it contains `#` or lies outside the 15 × 15 grid.

Only successful movement changes the player's position.

Every non-enterable target causes the invalid-movement penalty defined in Section 5.5.

## 5.3 Movement Repeat Timing
Movement timing follows two stages:
1. A newly pressed arrow key triggers one immediate movement attempt.
2. If the same key remains held, subsequent attempts occur every 0.15 seconds.

The 0.15-second interval remains fixed throughout the game and does not change according to remaining Time, Steps, or player position.

Each repeated attempt is treated as a separate movement attempt. Therefore, every repeated invalid attempt independently applies the 1-second Time penalty.

## 5.4 Step Counting
Steps counts only completed movement into another valid cell.

Successful movement:
`Steps += 1`

Failed movement:
`Steps unchanged`

Entering the exit also counts as one successful movement, so Steps increases by 1 when the exit is successfully reached.

## 5.5 Countdown & Invalid-Movement Penalty
The game uses a 30-second countdown based on actual elapsed time.

Time decreases continuously while:
`game_state = running`

In addition, every invalid movement attempt causes:
`Time -= 1 second`

An invalid movement attempt is any attempt whose target:
- Contains `#`, or
- Lies outside the 15 × 15 grid.

The penalty is applied once per invalid movement attempt.

After applying the penalty:
- If Time > 0, gameplay continues.
- If Time ≤ 0, set displayed Time to 0 and immediately enter `lost`.

The displayed Time is always clamped to a minimum of 0.

## 5.6 Time, Victory & Failure Priority
Normal countdown expiration has priority over new movement outcomes in the frame in which the countdown reaches 0.

At the beginning of each gameplay update, the normal countdown is advanced. If Time reaches 0 during that update:
1. Set displayed Time to 0.
2. Immediately enter `lost`.
3. Do not process any new movement attempt for that frame.
4. Do not increase Steps.
5. Do not allow an exit entry during that frame to trigger `won`.

If Time remains above 0, movement input may be processed.

For an invalid movement attempt:
1. Leave the player in the current cell.
2. Leave Steps unchanged.
3. Reduce Time by 1 second.
4. If Time reaches 0, immediately enter `lost`.

For a successful movement:
1. Move the player into the target cell.
2. Increase Steps by 1.
3. If the target is `E` and Time remains above 0, immediately enter `won`.

## 5.7 Excluded Mechanics
The game does not include HP, enemies, traps, keys, collectibles, items, random maze generation, hidden visibility, map scrolling, increasing difficulty, or multiple levels.

---

# 6. Game Flow & Progression
At initialization, the game creates the interface, fixed maze, player, exit, Time, Steps, held-key repeat state, and game state.

The initial state is:
- Player: `(row=1, col=1)`
- Exit: `(row=13, col=12)`
- Time: 30
- Steps: 0
- Game state: `running`

The complete maze is visible immediately.

While `running`, each update first advances Time according to actual elapsed time.

If Time reaches 0, the game immediately enters `lost` and no new player movement or exit event is processed during that frame.

If Time remains above 0, the game processes newly pressed arrow keys and held-key repeats.

For each movement attempt, it calculates the target cell and checks map boundaries and cell validity.

If the target is valid:
- The player moves into the target cell.
- Steps increases by 1.
- If the target is `E`, the game immediately enters `won`.

If the target is invalid:
- The player remains in place.
- Steps does not increase.
- Time is reduced by 1 second.
- If Time reaches 0, the game immediately enters `lost`.

After entering `won`:
- Player movement stops.
- Time stops.
- Steps stops changing.
- The bottom instruction area displays `You Escaped!` and `Press R to Restart`.

After entering `lost`:
- Player movement stops.
- Time remains at 0.
- Steps stops changing.
- The bottom instruction area displays `Game Over` and `Press R to Restart`.

Pressing R completely reinitializes the game.

The maze layout, initial duration of 30 seconds, invalid-movement penalty of 1 second, movement-repeat interval of 0.15 seconds, player starting position, and exit position remain fixed for every run.

---

# 7. Goal, Feedback & Termination
The player's only objective is to move from the starting position to the exit before Time reaches 0.

The game does not require collecting items, defeating enemies, or completing secondary objectives.

The top information area displays `Time: X` and `Steps: X`.

Time starts at 30, decreases according to actual elapsed time, loses an additional 1 second after every invalid movement attempt, and never displays below 0.

Steps starts at 0 and increases only after successful movement.

Movement feedback is immediate:
- Valid target cell → player moves one cell and Steps increases by 1.
- Wall → player remains in place, Steps does not change, and Time decreases by 1 second.
- Outside map → player remains in place, Steps does not change, and Time decreases by 1 second.

During `running`, the bottom instruction area displays:
`Move: ↑ / ↓ / ← / →`
`Invalid move: -1s    Restart: R`

Victory occurs when the player successfully enters the exit while Time is greater than 0. The game enters `won` and displays:
`You Escaped!`
`Press R to Restart`

Failure occurs when Time reaches 0 either through the normal countdown or an invalid-movement penalty. The game enters `lost` and displays:
`Game Over`
`Press R to Restart`

Normal countdown expiration is checked before new movement outcomes in each update.

R is available in `running`, `won`, and `lost` and restores the entire game to its initial state.

---

# 8. Functional Checkpoints
