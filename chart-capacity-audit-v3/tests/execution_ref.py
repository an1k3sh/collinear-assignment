"""Independent per-target option enumeration and Decimal risk accounting."""
from decimal import Decimal
from itertools import product

D = lambda v: Decimal(str(v))


def expected_execution(summaries, p):
    e, order = p["execution"], p["target_order"]
    h = e["horizon"]
    option_sets = []
    for t in order:
        options = [[]]
        if t in e["candidates"] and summaries[t]["rollout_eligible"]:
            for start in range(h):
                end = start+e["durations"][t][0]
                ready = end+e["warmups"][t][0]
                if ready > h or set(range(start,end)) & set(e["blackouts"][t]):
                    continue
                first = {"target":t,"tier":1,"start":start,"finish":end,"ready":ready}
                options.append([first])
                for second in range(max(ready,end+e["region_gap"]),h):
                    end2 = second+e["durations"][t][1]
                    ready2 = end2+e["warmups"][t][1]
                    if ready2 <= h and not set(range(second,end2)) & set(e["blackouts"][t]):
                        options.append([first,{"target":t,"tier":2,"start":second,"finish":end2,"ready":ready2}])
        option_sets.append(options)
    winner, best_key = None, None
    for choices in product(*option_sets):
        jobs = [job for choice in choices for job in choice]
        if len(jobs) > e["max_jobs"]:
            continue
        tiers = {t:len(choice) for t,choice in zip(order,choices)}
        regions = {p["targets"][t]["region"] for t in order if tiers[t]}
        if len(regions) > p["max_active_regions"]:
            continue
        credits = sum(D(p["targets"][t]["cost"][tiers[t]]) for t in order)+sum(D(p["regions"][r]["activation_cost"]) for r in regions)
        power = sum(D(p["targets"][t]["power"][tiers[t]]) for t in order)
        if credits > p["credit_budget"] or power > p["power_budget"]:
            continue
        if any(sum(tiers[t] for t in order if p["targets"][t]["region"] == r) > p["regions"][r]["max_blocks"] for r in regions):
            continue
        sorted_jobs = sorted(jobs,key=lambda j:(j["start"],order.index(j["target"]),j["tier"]))
        by_job = {(j["target"],j["tier"]):j for j in jobs}
        if any((d["requires"],d["requires_tier"]) not in by_job or
               by_job[d["requires"],d["requires_tier"]]["ready"] > by_job[d["target"],d["tier"]]["start"]
               for d in e["dependencies"] if (d["target"],d["tier"]) in by_job):
            continue
        if any(b["start"] < a["finish"]+e["region_gap"]
               for i,a in enumerate(sorted_jobs) for b in sorted_jobs[i+1:]
               if p["targets"][a["target"]]["region"] == p["targets"][b["target"]]["region"]):
            continue
        occupied = [[t for t in order if any(j["target"] == t and slot in range(j["start"],j["finish"]) for j in jobs)] for slot in range(h)]
        if any(len(v) > e["crews"][slot] for slot,v in enumerate(occupied)):
            continue
        live = []
        for slot in range(h):
            live.append({t:0 if t in occupied[slot] else sum(j["target"] == t and j["ready"] <= slot for j in jobs) for t in order})
        cases = []
        for case in e["cases"]:
            factors = dict.fromkeys(order,D(0))
            baseline = D(0)
            for t in order:
                weight = D(p["targets"][t]["risk_weight"])
                for slot in range(h):
                    demand = D(case["exposure"][t][slot])
                    baseline += D(summaries[t]["errors"])*weight*demand
                    reduction = D(p["targets"][t]["reduction"][live[slot][t]])
                    factors[t] += weight*demand*(reduction-(D(e["disruption"]) if t in occupied[slot] else 0))
            for link in e["links"]:
                for slot in range(h):
                    left,right,owner = (link[k] for k in ("left","right","owner"))
                    value = min(D(p["targets"][left]["reduction"][live[slot][left]]),
                                D(p["targets"][right]["reduction"][live[slot][right]]))
                    factors[owner] += value*D(link["factor"])*D(p["targets"][owner]["risk_weight"])*D(case["exposure"][owner][slot])
            net = sum(factors[t]*D(summaries[t]["errors"]) for t in order)
            lower = sum(v*D(summaries[t]["error_bounds"][0 if v >= 0 else 1]) for t,v in factors.items())
            upper = sum(v*D(summaries[t]["error_bounds"][1 if v >= 0 else 0]) for t,v in factors.items())
            cases.append({"id":case["id"],"baseline":baseline,"net":net,"net_bounds":[lower,upper],"residual":baseline-net})
        vector = [by_job[t,k]["start"] if (t,k) in by_job else h+1 for t in order for k in (1,2)]
        worst, total = min(c["net"] for c in cases),sum(c["net"] for c in cases)
        key = (-worst,-total,credits,power,vector)
        if best_key is None or key < best_key:
            best_key = key
            winner = {"actions":sorted_jobs,"slots":[{"slot":s,"occupied":occupied[s],"effective_tiers":live[s]} for s in range(h)],
                      "final_tiers":tiers,"credits":credits,"power":power,"active_regions":sorted(regions),
                      "peak_crews":max(map(len,occupied)),"cases":cases,"worst_case_net":worst,
                      "total_case_net":total,"start_vector":vector}
    return winner
