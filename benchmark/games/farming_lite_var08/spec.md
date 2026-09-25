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
  "difficulty": "hard",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Farming-lite",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      800,
      600
    ]
  },
  "schema_version": 1,
  "family_slug": "farming_lite",
  "variant_id": "var08",
  "instance_id": "farming_lite_var08"
}
---

# Game Specification

## Game Name

Farming-lite

---

# 1. Game Overview

Farming-lite is a simplified farming management game with a fixed 8-day operating cycle.

The player buys seeds, plants crops, waters them, waits for them to grow, harvests mature crops, and earns Gold.

The game does not use traditional Victory or Failure conditions. The player's objective is to manage the farm efficiently across 8 days, accumulate Gold, and increase the number of harvested crops.

After Day 8 ends, the game enters a settlement state and displays the final Gold amount together with the total numbers of Carrots and Corn harvested.

The game contains two crops:

- Carrot: cheaper, matures faster, lower harvest value.
- Corn: more expensive than Carrot, has a medium growth cycle, and provides a higher harvest value.

A custom rule is that crops do not grow continuously with real time and do not grow immediately when watered.

Growth occurs only during the unified end-of-day settlement.

For each planted immature crop:

- If it was watered during the current Day, it grows by exactly 1 stage.
- If it was not watered, its stage does not change.
- Unwatered crops do not die or regress.
- Each plot can receive at most one effective watering per Day.

---

# 2. Game Scene & Interface

The game window is 800 × 600 px and uses a horizontal layout. From top to bottom, it is divided into:

1. Top information area: 800 × 80 px
2. Main farm area: 800 × 440 px
3. Bottom control area: 800 × 80 px

## 2.1 Top Information Area

The first line uses a font size of 24 px and displays:

- `Gold: X`
- `Day: D/8`
- `Time: Ts`

Simple supporting icons may be used, but the text and numbers must remain clearly readable.

The second line uses a font size of 20 px and displays:

`Harvested: N`

N is the cumulative number of harvested crops, including both manually harvested crops and mature crops automatically harvested during the Day 8 final settlement.

## 2.2 Main Farm Area

The farmland uses a fixed 6 × 4 grid:

- Total plots: 24
- Plot size: 70 × 70 px
- Grid size: 420 × 280 px
- Grid top-left coordinate: `(190, 140)`

Each plot should have a clearly visible border or spacing.

Plot appearance:

- Empty: light-brown or brown soil.
- Planted, not watered: normal soil with the crop's current growth stage.
- Watered: crop remains visible while the soil becomes darker or a blue water-drop marker is added.
- Mature: crop is clearly larger or otherwise visually distinct from immature stages.

The watered state is an overlay and must not replace or obscure the crop graphic.

At the start of each new Day, all watered markers are cleared.

## 2.3 Crop Visual Stages

Carrot has 3 stages:

- Stage 0: small green sprout with 1–2 leaves; no visible orange root.
- Stage 1: larger green leaf cluster; still no clear Carrot body.
- Stage 2: mature; orange Carrot body with green leaves.

Corn has 4 stages:

- Stage 0: small green sprout.
- Stage 1: taller green stalk with several leaves.
- Stage 2: a small yellow Corn cob begins to appear on the stalk.
- Stage 3: mature; a clearly visible yellow Corn cob with green husk.

Mature crops must be clearly distinguishable from immature crops.

Only mature crops can be harvested.

## 2.4 Bottom Control Area

The first line uses a font size of 24 px and displays:

- Carrot seed icon + `1` + `8`
- Corn seed icon + `2` + `14`
- Watering can icon + `W`
- Harvest tool icon + `H`

The Corn seed icon should use a yellow-and-green Corn-style appearance clearly distinguishable from the Carrot icon.

The current selection is indicated only by a highlighted border around the corresponding icon.

No `Selected: ...` text is displayed.

The second line uses a font size of 20 px and normally displays:

`Left Click: Use Right Click: Cancel`

Operation feedback temporarily replaces this line for approximately 1 second.

Error feedback uses red or dark-red text.

Harvest feedback uses gold or yellow text.

---

# 3. Game Objects & States

The main game objects and state variables include farmland plots, crops, Gold, Day, remaining Time, current selection, harvest statistics, and game state.

## 3.1 Farmland Plots

The farmland contains 24 plots arranged in a 6 × 4 grid.

Each plot records:

- Whether it is empty.
- Crop type, if planted.
- Current growth stage.
- Whether it has been watered during the current Day.
- Whether the crop is mature.

Crop type, growth stage, maturity, and watered state are logically separate properties.

An empty plot retains none of these crop-related states.

After harvesting, the plot immediately becomes empty and all previous crop state is cleared.

## 3.2 Crops

The crop parameters are:

| Crop | Seed Price | Growth Events to Mature | Mature Stage | Harvest Value |
|---|---:|---:|---:|---:|
| Carrot | 8 Gold | 2 | Stage 2 | 18 Gold |
| Corn | 14 Gold | 3 | Stage 3 | 36 Gold |

Both crops begin at Stage 0.

Each effective end-of-day growth event:

`stage += 1`

A Carrot becomes mature at Stage 2.

Corn becomes mature at Stage 3.

Growth stages never increase beyond the crop's mature stage.

## 3.3 Gold

The player starts with:

`Gold = 80`

Gold changes as follows:

- Plant Carrot: -8
- Plant Corn: -14
- Water crop: 0
- Harvest mature Carrot: +18
- Harvest mature Corn: +36

Mature crops automatically harvested during Day 8 final settlement provide the same normal harvest value.

If Gold is insufficient for the selected seed, planting fails and no Gold is deducted.

## 3.4 Time & Day

The game lasts exactly 8 Days.

Each Day lasts:

`30 seconds`

Time decreases automatically while the game is `running`.

The player cannot manually skip or end a Day.

When the current Day reaches Time = 0:

- Normal player actions for that Day stop.
- End-of-day settlement begins.

For Days 1–7, the game then advances to the next Day and resets Time to 30 seconds.

For Day 8, the game proceeds to final settlement.

## 3.5 Current Selection

Possible selections are:

- `none`
- `carrot_seed`
- `corn_seed`
- `watering_can`
- `harvest_tool`

The selection remains active after successful or failed operations.

Only right-clicking cancels it.

## 3.6 Harvest Statistics

The game records:

- Total harvested crops
- Carrots harvested
- Corn harvested

Both manual and Day 8 automatic harvests count toward these totals.

The top information area displays:

`Harvested: N`

The final settlement displays separate Carrot and Corn counts.

## 3.7 Game State

The game contains two states:

- `running`
- `settlement`

During `running`, Time decreases and the player may plant, water, and harvest.

After the Day 8 final settlement is completed, the game enters `settlement`.

During `settlement`:

- Time stops.
- Planting has no effect.
- Watering has no effect.
- Harvesting has no effect.
- Only R is accepted to restart.

---

# 4. Player Interaction

The player uses the keyboard and mouse.

## 4.1 Selecting an Operation

Controls:

- `1`: select Carrot seed
- `2`: select Corn seed
- `W`: select watering can
- `H`: select harvest tool
- Right mouse button: cancel selection

The corresponding icon is highlighted while selected.

A seed may still be selected even if the player currently lacks enough Gold.

Gold is checked only when planting is attempted.

## 4.2 Planting

When a seed is selected, left-clicking a plot attempts to plant that crop.

Planting succeeds only if:

1. The plot is empty.
2. The player has enough Gold.

On success:

- Create the selected crop at Stage 0.
- Deduct the seed price.
- Keep the current selection active.

Failure is checked in this order:

1. Plot occupancy.
2. Gold availability.

Feedback:

- Occupied plot → `Tile is not empty`
- Insufficient Gold → `Not enough gold`

Failed planting does not deduct Gold.

## 4.3 Watering

When the watering can is selected, left-clicking a plot attempts to water it.

Watering is free.

Each planted immature crop can receive at most one effective watering during the current Day.

Watering succeeds only if:

1. A crop exists.
2. The crop is not mature.
3. The plot has not already been watered that Day.

On success:

- Set the plot's watered state for the current Day.
- Keep the current selection active.

Watering does not immediately change crop stage.

Failure handling:

- Empty plot → `No crop here`
- Mature crop → no effect and no error feedback
- Already watered immature crop → `Already watered today`

## 4.4 Harvesting

When the harvest tool is selected, left-clicking a plot attempts to harvest.

Only mature crops can be harvested.

On successful harvest:

- Add the crop's harvest value to Gold.
- Increase total harvested count by 1.
- Increase the corresponding crop-type count by 1.
- Clear all crop state from the plot.
- Return the plot to empty.
- Keep Harvest selected.

Feedback:

- Carrot → `Harvested Carrot +18`
- Corn → `Harvested Corn +36`

Failure is checked in this order:

1. Crop existence.
2. Maturity.

Feedback:

- Empty plot → `No crop here`
- Immature crop → `Crop is not mature`

## 4.5 Canceling Selection

Right-clicking cancels the current selection.

After cancellation:

- No operation icon is highlighted.
- The default mouse instruction remains displayed.

With no selection, left-clicking a plot:

- Performs no operation.
- Displays no error.
- Does not deduct Gold.
- Does not change the plot.

## 4.6 Restart

R is accepted after the game enters `settlement`.

Restart resets:

- Gold to 80
- Day to 1
- Time to 30 seconds
- All plots to empty
- All crop states
- Selection to `none`
- Total harvested count to 0
- Carrot harvested count to 0
- Corn harvested count to 0
- Game state to `running`

After Restart, the available crop types are again Carrot and Corn.

No crop or harvest state from the previous run continues.

---

# 5. Core Rules & Mechanics

## 5.1 Crop Growth

Crops do not grow continuously over real time and do not grow immediately when watered.

Growth occurs only during end-of-day settlement.

For each planted immature crop:

- Watered during current Day → stage +1
- Not watered → stage unchanged
- If the new stage reaches the mature stage → mark mature

Carrot progression is:

`Stage 0 → Stage 1 → Stage 2 (Mature)`

Corn progression is:

`Stage 0 → Stage 1 → Stage 2 → Stage 3 (Mature)`

Therefore:

- Carrot requires exactly 2 effective growth events to mature.
- Corn requires exactly 3 effective growth events to mature.

After settlement, all watered states are cleared.

Unwatered crops do not die or regress.

A crop may be planted and watered during the same Day.

If so, it receives one normal growth event when that Day ends.

Once a crop reaches its mature stage, its stage no longer changes.

## 5.2 Daily Settlement

Each Day lasts 30 seconds.

When Time reaches 0, normal player actions for the current Day stop and settlement occurs in this fixed order:

1. Check all planted immature crops.
2. Increase the stage of each watered immature crop by 1.
3. Leave each unwatered immature crop unchanged.
4. Mark Carrots reaching Stage 2 as mature.
5. Mark Corn reaching Stage 3 as mature.
6. Clear the watered state of every plot.
7. If the current Day is Day 1–7, increase Day by 1 and reset Time to 30 seconds.
8. If the current Day is Day 8, proceed directly to final settlement.

Time continues automatically during `running`.

Player operations do not pause the timer.

## 5.3 Final Settlement

When the Day 8 countdown reaches 0, final settlement is executed exactly once.

The fixed order is:

1. Perform the normal Day 8 growth settlement.
2. Mark Carrots reaching Stage 2 as mature.
3. Mark Corn reaching Stage 3 as mature.
4. Identify all crops that are mature after that growth settlement.
5. Automatically harvest all mature crops.
6. Add each harvested crop's normal value to Gold.
7. Increase total harvested count.
8. Increase the corresponding Carrot or Corn count.
9. Clear all automatically harvested plots.
10. Leave immature crops without final earnings.
11. Enter `settlement`.

Therefore:

- A Carrot that changes from Stage 1 to Stage 2 during Day 8 settlement is automatically harvested.
- Corn that changes from Stage 2 to Stage 3 during Day 8 settlement is automatically harvested.

## 5.4 Planting & Resource Rules

Planting requires:

- An empty plot.
- Sufficient Gold.

Seed prices:

- Carrot: 8 Gold
- Corn: 14 Gold

A newly planted crop begins at Stage 0.

After manual harvesting, the plot becomes empty immediately and may be replanted during the same Day.

If the newly planted crop is watered before that Day ends, it can still receive that Day's growth event.

A newly planted Carrot requires 2 effective growth events to mature.

Newly planted Corn requires 3 effective growth events to mature.

## 5.5 Watering Rules

Watering costs no Gold.

Each planted immature plot receives at most one effective watering per Day.

The watered state lasts until the Day ends.

Repeated watering:

- Does not produce additional growth.
- Does not shorten maturation time.
- Does not change the current stage.

Mature crops do not require watering and are unaffected by it.

## 5.6 Harvest Rules

Only mature crops can be harvested.

A Carrot is mature at Stage 2.

Corn is mature at Stage 3.

Harvest values:

- Mature Carrot: 18 Gold
- Mature Corn: 36 Gold

After a successful harvest:

- Gold updates immediately.
- Harvest statistics update immediately.
- The plot becomes empty and reusable.

Immature crops cannot be harvested.

## 5.7 Settlement & Termination

The game has no traditional Victory or Failure state.

The farming session terminates only after completing the 8-day cycle.

After final settlement, the main farm area displays:

`Season Complete`

`Final Gold: X`

Carrot graphic + `A`

Corn graphic + `B`

`Press R to Restart`

where:

- X = final Gold
- A = total Carrots harvested
- B = total Corn harvested

Display sizes:

- `Season Complete`: 48 px
- `Final Gold: X`: 32 px
- Carrot and Corn counts: 28 px
- `Press R to Restart`: 28 px

`Season Complete` may use a more prominent visual style, such as bold text, a light outline, subtle shadow, or gold-colored text.

---

# 6. Game Flow & Progression

At initialization, the game creates the interface areas, 24 farmland plots, Gold, Day, Time, selection state, harvest statistics, and game state.

The initial state is:

- Gold: 80
- Day: 1
- Time: 30 seconds
- Plots: 24 empty plots
- Selection: `none`
- Total harvested: 0
- Carrots harvested: 0
- Corn harvested: 0
- Game state: `running`

While `running`, Time continuously decreases.

The player may select seeds or tools using `1`, `2`, `W`, and `H`, use left-click to perform the selected operation, and use right-click to cancel selection.

Planting deducts Gold and creates a Stage 0 Carrot or Corn crop.

Watering marks an immature crop as watered for the current Day.

At end-of-day settlement:

- A watered immature crop advances exactly one stage.
- A Carrot becomes mature at Stage 2.
- Corn becomes mature at Stage 3.

Harvesting a mature crop adds its corresponding Gold value, updates harvest statistics, and clears the plot.

When Time reaches 0:

1. Stop new player operations for the current Day.
2. Perform the daily growth settlement.
3. Update crop maturity.
4. Clear all watered states.

For Days 1–7:

- Advance to the next Day.
- Reset Time to 30 seconds.
- Continue `running`.

For Day 8:

- Complete the Day 8 growth settlement.
- Automatically harvest all Carrots and Corn that are mature after that settlement.
- Update Gold and harvest statistics.
- Ignore immature crops for final earnings.
- Enter `settlement`.

During `settlement`, the main farm area displays:

`Season Complete`

`Final Gold: X`

Carrot graphic + `A`

Corn graphic + `B`

`Press R to Restart`

Only R remains active.

Pressing R fully restores the initial game state and begins again from Day 1.

---

# 7. Goal, Feedback & Termination

The player's goal is to manage the 8-day farming cycle effectively by purchasing Carrot and Corn seeds, planting crops, watering them, and harvesting mature crops to accumulate Gold and increase crop harvest counts.

The top information area provides:

- Current Gold
- Current Day
- Remaining Time
- Total harvested count

Plot feedback visually distinguishes:

- Empty plots
- Planted Carrots
- Planted Corn
- Growth stages
- Mature crops
- Watered state

The current operation is indicated only by the highlighted icon.

The bottom line normally displays:

`Left Click: Use Right Click: Cancel`

Error feedback includes:

- `Not enough gold`
- `Tile is not empty`
- `No crop here`
- `Already watered today`
- `Crop is not mature`

Successful harvest feedback includes:

- `Harvested Carrot +18`
- `Harvested Corn +36`

The game has no Victory, Failure, Game Over, or You Win state.

The farming session ends only after:

1. Day 8 reaches Time = 0.
2. The Day 8 growth settlement is completed.
3. All Carrots and Corn mature at that point are automatically harvested.
4. Final Gold and harvest statistics are updated.
5. The game enters `settlement`.

Immature crops remaining after final growth provide no final earnings.

During `settlement`, only R is accepted to restart.

---

# 8. Functional Checkpoints
