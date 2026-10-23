# Weekend reslotting plan — report

## Result

| Metric | Baseline | Target / limit | Submitted layout |
|---|---|---|---|
| Travel (ticks) | 2,430,286 | ≤ 2,381,680 | **2,369,356** (−60,930, **−2.51 %**) |
| Relocation minutes | 0 | ≤ 200 | **196** |
| SKUs moved | 0 | — | 57 of 80 (all 8 fixed SKUs unchanged) |

The public scorer gives `"valid": true` with no errors.

## Reproduce

```sh
cd /app/submission
python reslot.py            # default: --seeds 1 2 3 4 5 6 7 8 --iters 20000000 --restarts 2 --t0 10000 --t1 2
python /app/tools/evaluate.py --data /app/data --layout /app/submission/layout.json
```

Runtime is about 70 s on one core. `reslot.py` compiles `sa.cpp` with `g++ -O2`, writes the solver input to
`sa_input.txt`, runs each seed, keeps the best budget-feasible result, recomputes both metrics in
Python from the CSV files, and writes `layout.json`. The search parameters are also stored in
`layout.json` under `search`. The winning seed is **4**. It is deterministic (`std::mt19937_64`), so
`./sa 4 20000000 2 10000 2 < sa_input.txt` reproduces `2369356 196`.

## Method

* **Model.** This is a quadratic assignment problem. Flow `F[i][j]` is the sum of directed traversals,
  and `D` is the supplied slot distance matrix, used exactly as given. The objective is
  `Σ F[i][j]·D[slot(i)][slot(j)]`, so every transitions row is counted once.
* **Data structure.** The strong flows (≥ 60 traversals in total for a pair) form 8 clusters of 10 SKUs,
  each with 5 SKUs per zone. Zones alternate by aisle, and walking uses both a front and a back
  cross-aisle. Each cluster therefore wants a compact block across neighbouring zone-0 and zone-1
  aisles. One cluster is mostly fixed and spread out, which pushes the other clusters out of the
  ideal blocks.
* **Search.** The search is simulated annealing over moves that keep feasibility. It uses swaps and
  3-cycles of movable SKUs within the same zone, so fixed SKUs and zones are never violated. Each move
  is scored with an O(n) delta.
* **Labor.** A SKU's `move_minutes` is charged when its slot differs from its baseline slot. Moving it
  back costs nothing. During the run, labor is a soft penalty `λ·max(0, L−200)`, with λ rising
  geometrically from 20 to 50,000. Only states with `L ≤ 200` can become the incumbent.
* **Schedule.** Temperature cools geometrically from 10,000 to 2. Restart 1 starts from the baseline.
  Restart 2 starts again from the incumbent.

## Notes on the search

* A cold schedule (T0 = 3000) always stops at 2,395,388 (−1.44 %), even without a labor cap. That is a
  local optimum where whole clusters would have to move, and every single move in that direction
  costs about 10⁴ ticks. Raising T0 to 10,000 lets the search swap whole cluster blocks.
* With T0 = 10,000, 7 of the 8 seeds meet the target (2,369,356 to 2,379,452). Seed 5 does not: it ends
  with no feasible improvement and returns the baseline. Hotter schedules (T0 ≥ 30,000) are less
  reliable.
* The solution is not claimed to be globally optimal.

## Validation

* `python /app/tools/evaluate.py --data /app/data --layout /app/submission/layout.json` returns
  `valid: true`, travel 2,369,356, relocation 196, and no errors.
* The driver checks the C++ objective against a separate Python recomputation (`assert`). The
  reported metrics are integers computed from the saved assignment.
* `/app/data`, `/app/POLICY.md` and `/app/tools` were not modified.
