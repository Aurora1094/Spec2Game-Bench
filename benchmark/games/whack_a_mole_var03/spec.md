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
  "d4_operation_policy": {
    "mode": "target_specific",
    "identity": "control_plus_target",
    "operations": [
      {
        "id": "click_normal_mole",
        "control": "left_mouse_button",
        "target": "normal_mole",
        "description": "Click a visible Normal Mole with the left mouse button."
      },
      {
        "id": "click_golden_mole",
        "control": "left_mouse_button",
        "target": "golden_mole",
        "description": "Click a visible Golden Mole with the left mouse button."
      }
    ],
    "d43_source_checkpoint_ids": [
      "whack_a_mole_var03.D2.2.01",
      "whack_a_mole_var03.D2.2.02",
      "whack_a_mole_var03.D2.2.03"
    ]
  },
  "game_name": "Whack-a-Mole",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "whack_a_mole",
  "variant_id": "var03",
  "instance_id": "whack_a_mole_var03"
}
---

# Game Specification

## Game Name
Whack-a-Mole

---

# 1. Game Overview
Whack-a-Mole is a single-player real-time reaction and clicking game. The player uses the left mouse button to click moles that randomly appear from a fixed 3 × 3 set of holes within a 30-second time limit.

At any time, at most one mole is visible. A mole appears at one of the 9 fixed holes and remains visible for a limited duration. Clicking a visible mole awards points according to its type, immediately removes the mole, and starts a short waiting period before the next mole appears.

The game contains two mole types:
- Normal Mole: worth 1 point and visible for 1.0 second.
- Golden Mole: worth 3 points and visible for 0.6 seconds.

Each new mole is independently generated as a Normal Mole with 80% probability or a Golden Mole with 20% probability. The player's goal is to achieve the highest possible score before the 30-second countdown reaches 0.

The game has no fixed victory score, victory state, level transition, score penalty, or increasing difficulty.

---

# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into three areas:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area
The top information area displays the current score on the left using `Score: X` and the remaining time on the right using `Time: T`.

At the start of the game, the display is:
`Score: 0`
`Time: 30`

Both text elements use a font size of 40 px and must have sufficient spacing so that they do not overlap.

T is displayed as a non-negative whole number of seconds. Decimal values and negative values are not shown.

## 2.2 Main Gameplay Area
The main gameplay area is located below the top information area and covers window coordinates from `(0, 100)` to `(600, 700)`. It uses continuous pixel coordinates and does not require visible grid lines.

The area contains 9 fixed holes arranged in 3 rows × 3 columns:

| Hole | Center Coordinate |
|---:|---|
| 1 | `(150, 240)` |
| 2 | `(300, 240)` |
| 3 | `(450, 240)` |
| 4 | `(150, 400)` |
| 5 | `(300, 400)` |
| 6 | `(450, 400)` |
| 7 | `(150, 560)` |
| 8 | `(300, 560)` |
| 9 | `(450, 560)` |

Each hole is a dark-brown or very-dark-brown oval with a size of 100 × 70 px. For a hole centered at `(cx, cy)`, its oval bounding rectangle is `(cx - 50, cy - 35, 100, 70)`.

A mole appears above the center of its selected hole. Both mole types have a visual size of 60 × 60 px. Normal Moles are brown, while Golden Moles are gold.

The mole may be drawn as a circle or simple head shape, but click detection always uses a 60 × 60 px rectangular area. For a hole centered at `(cx, cy)`, the mole's top-left coordinate is `(cx - 30, cy - 60)`.

## 2.3 Bottom Instruction Area
While the game is in the `playing` state, the bottom instruction area displays:
`Click the mole`
`Restart: R`

Both lines use a font size of 28 px and should be centered.

After the game enters `game_over`, the bottom instruction area displays:
`Game Over`
`Press R to Restart`

`Game Over` uses a font size of 40 px, and `Press R to Restart` uses a font size of 28 px.

The top information area and bottom instruction area use a light-gray background, while the main gameplay area uses a light-green or light-beige background. Text should use a dark or black color, and the holes, Normal Moles, and Golden Moles must remain visually distinguishable.

At the start of the game, all 9 holes are visible, no mole is visible, Score is 0, Time is 30, and the game waits 0.15 seconds before spawning the first mole.

---

# 3. Game Objects & States
The main game objects and state variables include the 9 holes, Normal Mole, Golden Mole, current mole, score, countdown, mole-related timers, and game state.

## 3.1 Holes
The game contains exactly 9 fixed holes arranged in a 3 × 3 layout. Each hole has a size of 100 × 70 px and remains at its fixed position throughout the game.

Holes do not move, disappear, change size, or award points. Clicking an empty hole has no effect on the score.

## 3.2 Mole Types
A Normal Mole has a size of 60 × 60 px, remains visible for at most 1.0 second, and awards 1 point when successfully clicked.

A Golden Mole has the same size, remains visible for at most 0.6 seconds, and awards 3 points when successfully clicked.

If a visible mole is clicked within its active duration, the corresponding score is awarded, the mole disappears immediately, and a 0.15-second waiting period begins.

If its appearance duration expires without a successful click, the mole disappears without changing the score and the same 0.15-second waiting period begins.

## 3.3 Current Mole
At most one mole may be visible at any time. The current mole stores its type, selected hole, position, and remaining appearance time.

The hole is randomly selected from all 9 fixed holes. Two consecutive moles are allowed to appear at the same hole; the previous hole is not excluded from the next selection.

## 3.4 Score
Score starts at 0.

The scoring rules are:
- Normal Mole clicked: +1
- Golden Mole clicked: +3
- Empty hole, background, or UI area clicked: +0
- Click while no mole is visible: +0
- Missed mole: +0

The game does not use negative scores or record a separate high score.

## 3.5 Countdown
The total game duration is fixed at 30 seconds. The countdown includes the initial waiting period, mole appearance periods, and waiting periods between moles.

The UI displays the remaining time as a non-negative whole number only.

When the countdown reaches 0, the game immediately enters `game_over`. The current mole disappears, no new mole is spawned, no further click can change the score, and the display remains at `Time: 0`.

## 3.6 Game State
The game contains two states:
- `playing`
- `game_over`

The initial state is `playing`. The game enters `game_over` when the countdown reaches 0.

After entering `game_over`, mouse clicks no longer affect gameplay and only R is accepted to restart.

---

# 4. Player Interaction
The player uses the left mouse button and R.

## 4.1 Clicking a Mole
A mole is successfully clicked only when a left-mouse-button down event occurs within the current mole's 60 × 60 px clickable rectangle while that mole is active.

A successful click on a Normal Mole adds 1 point, while a successful click on a Golden Mole adds 3 points. The clicked mole then disappears immediately and a 0.15-second waiting period begins.

## 4.2 Invalid Clicks & Missed Moles
Clicks on empty holes, the gameplay background, the top information area, the bottom instruction area, or any location while no mole is visible have no effect.

Clicks during the 0.15-second waiting period also have no effect. Invalid clicks never increase or decrease the score.

If a Normal Mole remains unclicked for 1.0 second, or a Golden Mole remains unclicked for 0.6 seconds, it disappears automatically. Missing a mole does not reduce the score or create any other penalty.

## 4.3 Restart
After the game enters `game_over`, mouse clicks have no effect. Pressing R restarts the game.

Restart resets the score, countdown, current mole, all mole-related timers, interface state, and game state. A new 0.15-second initial waiting period begins before the first mole appears.

---

# 5. Core Rules & Mechanics

## 5.1 Mole Spawn Cycle
The game always uses the same 9-hole layout. Hole positions never change during gameplay.

The mole cycle is:
1. Wait 0.15 seconds.
2. Randomly select one of the 9 holes.
3. Independently select the mole type.
4. Display the mole for its defined maximum duration.
5. End the appearance when the mole is successfully clicked or its duration expires.
6. Remove the mole.
7. Begin the next 0.15-second waiting period.

The initial game state begins with Step 1. At most one mole may exist at any time.

## 5.2 Mole-Type Selection & Timing
Each mole spawn independently uses the following probabilities:
- Normal Mole: 80%
- Golden Mole: 20%

The 20% Golden Mole probability does not imply exactly one Golden Mole in every five spawns.

Normal Mole appearance duration is fixed at 1.0 second, Golden Mole appearance duration is fixed at 0.6 seconds, and the waiting period between moles is fixed at 0.15 seconds. These values do not change according to score, elapsed time, or the number of previously spawned moles.

## 5.3 Click Detection
Logical click detection always uses the current mole's 60 × 60 px rectangular clickable area, regardless of its visual shape.

A click succeeds if the mouse-down position lies within this rectangle while the mole is active. Pixel-perfect shape detection is not required.

## 5.4 Countdown Priority
The 30-second countdown has priority over mole clicks, appearance timers, and spawn timers.

If the countdown reaches 0 during the current frame, the game immediately enters `game_over` before any new gameplay outcome from that frame is accepted.

Therefore:
- A click occurring in the same frame in which Time reaches 0 does not award points.
- A mole whose appearance timer also expires in that frame is simply removed as part of game termination.
- If a waiting period also ends in that frame, no new mole is spawned.
- Score remains fixed at the value reached before Time became 0.

## 5.5 Excluded Mechanics
The game does not include HP, score penalties, combos, bomb moles, items, level transitions, increasing difficulty, or a victory state.

---

# 6. Game Flow & Progression
At initialization, the game creates the interface and 9 fixed holes, sets Score to 0 and Time to 30, clears the current mole, initializes all mole-related timers, enters `playing`, and starts a 0.15-second initial waiting period.

While `playing`, the countdown continuously decreases. At the beginning of each frame update, the game updates the countdown and first checks whether Time has reached 0. If so, it immediately enters `game_over` and does not process new click, mole-expiration, or mole-spawn outcomes for that frame.

If Time remains above 0, the game updates the current mole cycle. During a waiting period, the waiting timer advances until one mole is spawned. While a mole is visible, its appearance timer advances and valid mouse clicks are processed. A successful click updates the score, removes the mole, and starts a new 0.15-second waiting period. If the appearance duration expires first, the mole is removed without changing the score and the same waiting period begins.

After entering `game_over`, the current mole is removed, no new mole can spawn, mouse clicks no longer affect gameplay, Score remains fixed, Time remains 0, and the bottom instruction area displays `Game Over` and `Press R to Restart`.

Pressing R fully reinitializes the game and starts a new 0.15-second initial waiting period.

The game contains no difficulty progression. Total duration remains 30 seconds, both initial and between-mole waiting periods remain 0.15 seconds, Normal Mole duration remains 1.0 second, Golden Mole duration remains 0.6 seconds, and Golden Mole probability remains 20%.

---

# 7. Goal, Feedback & Termination
The player's goal is to click as many moles as possible within 30 seconds and achieve the highest possible score. The game has no fixed victory score, victory state, or level-completion condition.

The top information area displays `Score: X`, starting from `Score: 0`. A Normal Mole awards +1 and a Golden Mole awards +3. Missed moles and invalid clicks do not change the score.

The remaining time is displayed as `Time: T`, starting from `Time: 30` and ending at `Time: 0`. T is always displayed as a non-negative whole number.

During `playing`, the bottom instruction area displays `Click the mole` and `Restart: R`.

When Time reaches 0, the game enters `game_over`, the current mole disappears, Score stops changing, and the bottom area displays `Game Over` and `Press R to Restart`.

The Time = 0 termination takes priority over any click occurring during the same frame, so no additional score can be earned once the countdown has expired.

After entering `game_over`, pressing R restores Score to 0, Time to 30, clears the current mole and all mole timers, restores the normal gameplay instructions, returns the state to `playing`, and begins a new 0.15-second initial waiting period.

---

# 8. Functional Checkpoints
