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
  "game_name": "Simple Platformer",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      800,
      600
    ]
  },
  "schema_version": 1,
  "family_slug": "simple_platformer",
  "variant_id": "var07",
  "instance_id": "simple_platformer_var07"
}
---

# Game Specification

## Game Name
Simple Platformer

---

# 1. Game Overview
Simple Platformer is a single-screen platform game. The player controls a rectangular character that moves left and right, jumps between platforms, avoids spikes and falling hazards, and ultimately reaches the goal flag in the upper-right area of the level.

The player wins by touching the goal flag. The player loses by touching a spike or falling below the bottom boundary of the main gameplay area.

The game uses continuous pixel coordinates rather than a grid. The player is affected by gravity and can jump only while standing on a platform. Double jumping is not allowed.

Platform interaction uses axis-aligned rectangular collision detection. The player must be able to land on top of platforms, be blocked by their sides, and stop upward movement after hitting the underside of a platform.

The entire level is displayed on a single screen. The game does not use camera scrolling, map scrolling, or multiple levels.

Fixed platforms form the main traversal route. The game also includes two horizontally moving platforms. When the player is standing on top of a moving platform, the player is carried horizontally with that platform. Side contact or incidental airborne overlap does not cause the player to be carried.

---

# 2. Game Scene & Interface
The game window is 800 × 600 px and uses a horizontal layout. From top to bottom, the window is divided into:
1. Top information area: 800 × 60 px
2. Main gameplay area: 800 × 480 px
3. Bottom instruction area: 800 × 60 px

## 2.1 Top Information Area
The top information area occupies y = 0–60.

The left side displays one of:
- `Status: Playing`
- `Status: Won`
- `Status: Lost`

The right side displays:
`Goal: Reach the Flag`

At the start of the game:
`Status: Playing`
`Goal: Reach the Flag`

The information text uses a font size of 32 px. The left-side and right-side text must not overlap.

## 2.2 Main Gameplay Area
The main gameplay area occupies:
- Top-left: `(0, 60)`
- Bottom-right: `(800, 540)`

The area uses continuous pixel coordinates and does not display grid lines.

It contains the player, fixed platforms, two moving platforms, spikes, and goal flag.

## 2.3 Visual Style
Recommended colors are:
- Top information area: `#EDEDED`
- Bottom instruction area: `#EDEDED`
- Main gameplay background: `#BFE8FF`
- Player: `#2D7FF9`
- Fixed platforms: `#6B4F2A`
- Moving platforms: `#F2A33A`
- Spikes: `#D62828`
- Flagpole: `#333333`
- Flag cloth: `#2ECC71`
- Text: `#222222`

The player is displayed as a 32 × 40 px blue rectangle.

Both moving platforms use the moving-platform color and remain visually distinguishable from fixed platforms.

Spikes are visually drawn as red triangles inside their defined collision rectangles, but collision detection uses the complete rectangular areas.

The goal is drawn using a flagpole and flag cloth, while victory detection uses the flag's defined rectangular collision area.

## 2.4 Bottom Instruction Area
While the game is in `playing`, the bottom instruction area displays:
`Move: ← / →    Jump: Space`
`Reach the flag    Restart: R`

Both lines use a font size of 24 px and should be centered compactly within the area.

After Victory:
`You Win!`
`Press R to Restart`

After Failure:
`Game Over`
`Press R to Restart`

`You Win!` and `Game Over` use a font size of 40 px. `Press R to Restart` uses a font size of 28 px.

## 2.5 Initial Scene
At the start of the game:
- Player top-left position: `(40, 460)`
- Horizontal velocity: 0 px/s
- Vertical velocity: 0 px/s
- `on_ground = true`
- Moving Platform 1 position: `(300, 315)`
- Moving Platform 1 direction: right
- Moving Platform 2 position: `(500, 280)`
- Moving Platform 2 direction: left
- Game state: `playing`

---

# 3. Game Objects & States
The main game objects and state variables include the player, fixed platforms, two moving platforms, spikes, goal flag, movement state, and game state.

## 3.1 Player
The player:
- Is represented by a 32 × 40 px rectangle.
- Starts at `(40, 460)`.
- Has initial horizontal velocity 0 px/s.
- Has initial vertical velocity 0 px/s.
- Starts with `on_ground = true`.

The player can move left and right, jump, and move horizontally while airborne.

The player is continuously affected by gravity when not supported by a platform.

## 3.2 Fixed Platforms
Fixed platforms are rectangular collision objects. They do not move, disappear, or change size.

| Platform | Top-Left Coordinate | Size |
|---|---|---|
| Starting Platform | `(0, 500)` | `180 × 40 px` |
| Platform 1 | `(230, 455)` | `130 × 20 px` |
| Platform 2 | `(390, 400)` | `130 × 20 px` |
| Platform 3 | `(550, 345)` | `130 × 20 px` |
| Goal Platform | `(650, 255)` | `130 × 20 px` |

The player can land on their top surfaces, be blocked by their sides, and collide with their undersides while moving upward.

## 3.3 Moving Platforms
The game contains exactly two horizontally moving platforms.

Moving Platform 1:
- Initial top-left coordinate: `(300, 315)`
- Size: 110 × 20 px
- Fixed y-coordinate: 315
- Horizontal movement range: x = 260–430
- Speed: 80 px/s
- Initial direction: right

Moving Platform 2:
- Initial top-left coordinate: `(500, 280)`
- Size: 100 × 20 px
- Fixed y-coordinate: 280
- Horizontal movement range: x = 460–620
- Speed: 70 px/s
- Initial direction: left

Both platforms move continuously back and forth while the game is `playing`.

The player is carried horizontally only while standing on top of one of them.

Side contact or airborne overlap does not trigger the carrying effect.

## 3.4 Spikes
Spikes are fixed hazards:

| Hazard | Top-Left Coordinate | Size |
|---|---|---|
| Spike 1 | `(190, 520)` | `40 × 20 px` |
| Spike 2 | `(370, 520)` | `40 × 20 px` |
| Spike 3 | `(535, 520)` | `40 × 20 px` |

If the player rectangle overlaps any spike rectangle, Failure is triggered immediately.

Spikes do not move, disappear, or change position.

## 3.5 Goal Flag
The goal flag collision rectangle has:
- Top-left coordinate: `(720, 195)`
- Size: 30 × 60 px

Its bottom edge is y = 255, exactly touching the top of the Goal Platform.

The player wins by overlapping this rectangle. Standing on the Goal Platform itself is not required.

## 3.6 Game State
The game contains three internal states:
- `playing`
- `won`
- `lost`

During `playing`, player movement, gravity, both moving-platform movements, and collision detection are active.

During `won` or `lost`, player movement, gravity, and moving-platform updates stop. Only R is accepted.

---

# 4. Player Interaction
The player uses the left arrow key, right arrow key, Space, and R.

## 4.1 Horizontal Movement
While the left arrow key is held:
`vx = -220 px/s`

While the right arrow key is held:
`vx = 220 px/s`

If neither direction is held:
`vx = 0`

If both directions are held simultaneously:
`vx = 0`

The player can move horizontally both on the ground and in the air.

The entire player rectangle must remain inside the gameplay area horizontally:
- If `x < 0`, set `x = 0`.
- If `x + 32 > 800`, set `x = 768`.

## 4.2 Jump
Space triggers a jump only when:
`on_ground = true`

On a valid jump:
- Set `vy = -420 px/s`.
- Set `on_ground = false`.

Pressing Space while airborne has no effect. Double jump is not allowed.

Holding Space does not increase jump height or repeatedly trigger jumps. A jump is triggered only on a new Space key-down event.

## 4.3 Restart
R is effective in `playing`, `won`, and `lost`.

Pressing R resets:
- Player position to `(40, 460)`.
- `vx` to 0.
- `vy` to 0.
- `on_ground` to true.
- Moving Platform 1 position to `(300, 315)`.
- Moving Platform 1 direction to right.
- Moving Platform 2 position to `(500, 280)`.
- Moving Platform 2 direction to left.
- Game state to `playing`.
- Top display to `Status: Playing`.
- Bottom instructions to the normal gameplay text.

After entering `won` or `lost`, the arrow keys and Space have no effect.

---

# 5. Core Rules & Mechanics

## 5.1 Player Physics
The fixed movement parameters are:
- Horizontal speed: 220 px/s
- Initial jump velocity: -420 px/s
- Gravity: 900 px/s²
- Maximum falling speed: 600 px/s

While airborne, gravity increases vertical velocity and downward velocity is clamped to a maximum of 600 px/s.

While standing on a platform and not jumping:
`vy = 0`

## 5.2 Collision Model
The player, fixed platforms, both moving platforms, spikes, and goal flag all use axis-aligned rectangular collision detection.

The player collision rectangle is 32 × 40 px.

Visual appearance may differ from logical collision geometry, but gameplay collision always uses the defined rectangles.

## 5.3 Axis-Separated Platform Collision
Player-platform collision is resolved separately along the horizontal and vertical axes:
1. Process horizontal movement and horizontal platform collisions.
2. Process vertical movement and vertical platform collisions.

Both moving platforms participate in platform collision in the same way as the original moving platform.

This distinguishes side collisions, landing, and underside collisions and prevents the player from passing through platforms.

## 5.4 Horizontal Platform Collision
After horizontal movement, if the player overlaps a fixed or moving platform from the side:
- Moving right: place the player's right edge against the platform's left edge.
- Moving left: place the player's left edge against the platform's right edge.

Horizontal side collision prevents passage through the platform but does not set `on_ground = true`.

## 5.5 Vertical Platform Collision
When the player is moving downward and crosses or reaches a platform's top surface from above:
- Place the player's bottom edge exactly on the platform top.
- Set `vy = 0`.
- Set `on_ground = true`.

When the player is moving upward and reaches a platform's underside:
- Place the player's top edge against the platform bottom.
- Set `vy = 0`.
- Keep `on_ground = false`.

The player then begins falling under gravity.

## 5.6 Ground-State Update
The player can stand on a platform only after landing on its top from above. Side contact does not count as standing.

After vertical collision handling:
- If the player's bottom edge is supported by the top of a fixed or moving platform, set `on_ground = true`.
- Otherwise, set `on_ground = false`.

When the player walks off a platform edge, `on_ground` becomes false and gravity causes the player to fall.

## 5.7 Moving Platform Motion
Moving Platform 1 moves horizontally at 80 px/s between x = 260 and x = 430 while remaining at y = 315.

Its direction changes as follows:
- At `x >= 430`, change direction to left.
- At `x <= 260`, change direction to right.

Moving Platform 2 moves horizontally at 70 px/s between x = 460 and x = 620 while remaining at y = 280.

Its direction changes as follows:
- At `x >= 620`, change direction to left.
- At `x <= 460`, change direction to right.

Neither moving platform moves vertically.

## 5.8 Moving Platform Carrying
At the beginning of each frame, determine whether the player was standing on top of a moving platform in the previous frame.

Then:
1. Update both moving-platform positions.
2. Compute each platform's horizontal displacement.
3. If the player was standing on Moving Platform 1, move the player horizontally by Moving Platform 1's `dx`.
4. If the player was standing on Moving Platform 2, move the player horizontally by Moving Platform 2's `dx`.
5. Apply the gameplay area's horizontal boundary constraints.
6. Process the player's own horizontal input and platform collisions.

The player can be carried by only the moving platform on whose top surface the player was standing in the previous frame.

The displacement of the other moving platform is not applied to the player.

Side contact or airborne overlap with either moving platform does not trigger carrying.

## 5.9 Spike Collision
If the player rectangle overlaps any spike rectangle, Failure is triggered.

Spike collision does not reduce HP, provide invulnerability, reset the player position, or allow gameplay to continue.

## 5.10 Falling Failure
The bottom boundary of the main gameplay area is:
`y = 540`

Failure occurs when the player's bottom edge becomes greater than 540:
`player_y + 40 > 540`

The player does not need to completely leave the screen.

## 5.11 Goal Collision
Victory is triggered when the player rectangle overlaps the flag collision rectangle.

Standing on the Goal Platform is not required.

## 5.12 Terminal Priority
After gameplay movement and collision updates for the frame, determine all applicable terminal conditions.

Failure conditions are:
- Player overlaps any spike rectangle.
- Player bottom edge is greater than y = 540.

Victory condition:
- Player overlaps the goal flag rectangle.

Terminal conditions are resolved in this priority:
1. Failure
2. Victory
3. Continue

Therefore, if a flag collision and any Failure condition occur during the same frame, the game enters `lost` rather than `won`.

## 5.13 Excluded Mechanics
The game does not include a time limit, score, Lives, enemies, coins, collectibles, attacks, double jump, map scrolling, camera following, multiple levels, or increasing difficulty.

---

# 6. Game Flow & Progression
At initialization, the game creates the interface, player, fixed platforms, two moving platforms, spikes, goal flag, and game state.

The initial state is:
- Player position: `(40, 460)`
- `vx = 0`
- `vy = 0`
- `on_ground = true`
- Moving Platform 1 position: `(300, 315)`
- Moving Platform 1 direction: right
- Moving Platform 2 position: `(500, 280)`
- Moving Platform 2 direction: left
- Game state: `playing`

The complete level is immediately visible.

While `playing`, each frame:
1. Read left/right movement input and any new Space key-down event.
2. Start a jump if Space was newly pressed while `on_ground = true`.
3. Update both moving platforms and determine their horizontal displacements.
4. If the player was standing on one moving platform in the previous frame, apply only that platform's displacement to the player.
5. Process the player's horizontal movement and horizontal platform collisions.
6. Apply gravity and clamp falling speed to 600 px/s.
7. Process vertical movement and vertical platform collisions.
8. Update `on_ground`.
9. Detect spike collision, falling failure, and flag collision.
10. Resolve terminal conditions using Failure-before-Victory priority.
11. Update the Status and instruction displays.

If Failure is triggered, the game enters `lost`. Player movement, gravity, and both moving-platform motions stop, the top display changes to `Status: Lost`, and the bottom area displays `Game Over` and `Press R to Restart`.

If no Failure condition is present but the flag is reached, the game enters `won`. Player movement, gravity, and both moving-platform motions stop, the top display changes to `Status: Won`, and the bottom area displays `You Win!` and `Press R to Restart`.

Pressing R restores the initial player and both moving-platform states and returns the game to `playing`.

The following values remain fixed:
- Horizontal speed: 220 px/s
- Jump velocity: -420 px/s
- Gravity: 900 px/s²
- Maximum falling speed: 600 px/s
- Moving Platform 1 speed: 80 px/s
- Moving Platform 1 range: x = 260–430
- Moving Platform 2 speed: 70 px/s
- Moving Platform 2 range: x = 460–620
- Platform positions
- Spike positions
- Flag position

---

# 7. Goal, Feedback & Termination
The player's goal is to traverse the single-screen platform layout and touch the goal flag in the upper-right area.

The game does not require collecting items, defeating enemies, or completing the level within a time limit.

The top information area displays one of:
- `Status: Playing`
- `Status: Won`
- `Status: Lost`

The right side continuously displays:
`Goal: Reach the Flag`

Movement feedback includes left/right movement, jumping while grounded, gravity while airborne, landing on platform tops, side blocking, underside collision, and falling after walking off a platform.

While standing on either moving platform, the player is carried horizontally with that platform. Side contact or airborne overlap does not cause carrying.

Failure occurs if:
- The player overlaps any spike rectangle.
- `player_y + 40 > 540`

After Failure:
`Game Over`
`Press R to Restart`

Victory occurs if the player overlaps the goal flag rectangle and no Failure condition is satisfied in the same frame.

After Victory:
`You Win!`
`Press R to Restart`

During `playing`, the bottom instruction area displays:
`Move: ← / →    Jump: Space`
`Reach the flag    Restart: R`

If Victory and Failure conditions occur in the same frame, Failure takes priority.

After either terminal state, gameplay updates stop and only R is accepted to restart.

---

# 8. Functional Checkpoints
