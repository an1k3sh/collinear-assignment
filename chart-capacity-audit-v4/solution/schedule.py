"""Time-indexed oracle search for the executable rollout."""
import itertools
import math
from fractions import Fraction

F = lambda v: Fraction(str(v))


def validate(e, planning):
    def check(ok, message):
        if not ok:
            raise ValueError("execution: "+message)
    h = e["horizon"]
    check(type(h) is int and 3 <= h <= 6, "invalid horizon")
    check(type(e["reveal"]) is int and 0 <= e["reveal"] <= h, "invalid reveal boundary")
    candidates = e["candidates"]
    check(len(candidates) <= 4 and len(set(candidates)) == len(candidates)
          and set(candidates) <= set(planning["target_order"]), "invalid candidates")
    check(len(e["crews"]) == h and all(type(c) is int and 0 <= c <= 2 for c in e["crews"]), "crew vector")
    check(type(e["max_jobs"]) is int and 0 <= e["max_jobs"] <= 4, "job limit")
    check(e["region_gap"] in (0,1), "region gap")
    check(type(e["disruption"]) in (int,float) and math.isfinite(e["disruption"])
          and 0 <= e["disruption"] <= 1, "disruption")
    for t in candidates:
        for name, allowed in (("durations",(1,2)),("warmups",(0,1))):
            check(len(e[name][t]) == 2 and all(type(v) is int and v in allowed for v in e[name][t]), name)
        check(all(type(s) is int and 0 <= s < h for s in e["blackouts"][t]), "blackout")
    check(1 <= len(e["cases"]) <= 3, "case count")
    check(len({c["id"] for c in e["cases"]}) == len(e["cases"]), "duplicate case")
    for c in e["cases"]:
        check(set(c["exposure"]) == set(planning["target_order"]), "exposure targets")
        for values in c["exposure"].values():
            check(len(values) == h and all(type(v) in (int,float) and math.isfinite(v) and v >= 0 for v in values), "exposure values")
    graph = {(t,k): set() for t in candidates for k in (1,2)}
    for t in candidates:
        graph[t,2].add((t,1))
    for d in e["dependencies"]:
        node, pre = (d["target"],d["tier"]), (d["requires"],d["requires_tier"])
        check(node in graph and pre in graph, "dependency target/tier")
        graph[node].add(pre)
    active, done = set(), set()
    def visit(node):
        check(node not in active, "cyclic dependency")
        if node in done:
            return
        active.add(node)
        for pre in graph[node]:
            visit(pre)
        active.remove(node)
        done.add(node)
    for node in graph:
        visit(node)
    for link in e["links"]:
        check(all(link[k] in planning["target_order"] for k in ("left","right","owner")), "link target")
        check(type(link["factor"]) in (int,float) and math.isfinite(link["factor"])
              and 0 <= link["factor"] <= .2, "link factor")


def optimize_execution(summaries, planning):
    e, order = planning["execution"], planning["target_order"]
    validate(e,planning)
    h = e["horizon"]
    candidates = [t for t in order if t in e["candidates"]]
    specs = planning["targets"]
    risk = {t:F(specs[t]["risk_weight"]) for t in order}
    reductions_by_tier = {t:list(map(F,specs[t]["reduction"])) for t in order}
    exposures = [{t:list(map(F,c["exposure"][t])) for t in order} for c in e["cases"]]
    disruption = F(e["disruption"])
    link_factors = list(map(lambda link:F(link["factor"]),e["links"]))
    best_key, best = None, None
    groups = {}

    def evaluate(jobs, tiers, credits, power, regions):
        nonlocal best_key, best
        slots, coefficients = [], [{t:F(0) for t in order} for _ in e["cases"]]
        for s in range(h):
            occupied = [t for t in order if any(j["target"] == t and j["start"] <= s < j["finish"] for j in jobs)]
            effective = {t:max([0]+[j["tier"] for j in jobs if j["target"] == t and j["ready"] <= s]) for t in order}
            for t in occupied:
                effective[t] = 0
            reductions = {t:reductions_by_tier[t][effective[t]] for t in order}
            slots.append({"slot":s,"occupied":occupied,"effective_tiers":effective})
            for exposure, coeff in zip(exposures,coefficients):
                for t in order:
                    coeff[t] += risk[t]*exposure[t][s]*(reductions[t]-(disruption if t in occupied else 0))
                for link, factor in zip(e["links"],link_factors):
                    t = link["owner"]
                    coeff[t] += risk[t]*exposure[t][s]*factor*min(reductions[link["left"]],reductions[link["right"]])
        nets = [sum(c[t]*F(summaries[t]["errors"]) for t in order) for c in coefficients]
        starts = {(j["target"],j["tier"]):j["start"] for j in jobs}
        vector = [starts.get((t,k),h+1) for t in order for k in (1,2)]
        key = (-min(nets),-sum(nets),credits,power,vector)
        prefix = tuple((j["target"],j["tier"],j["start"]) for j in
                       sorted(jobs,key=lambda j:(j["start"],order.index(j["target"]),j["tier"]))
                       if j["start"] < e["reveal"])
        group = groups.setdefault(prefix,[None]*len(nets))
        branch_keys = [(-net,credits,power,vector) for net in nets]
        better_cases = [i for i,bk in enumerate(branch_keys) if group[i] is None or bk < group[i][0]]
        fixed_better = best_key is None or key < best_key
        if not fixed_better and not better_cases:
            return
        cases = []
        for case, coeff, net in zip(e["cases"],coefficients,nets):
            baseline = sum(summaries[t]["errors"]*specs[t]["risk_weight"]*sum(case["exposure"][t]) for t in order)
            bounds = [float(sum(v*F(summaries[t]["error_bounds"][i if v >= 0 else 1-i]) for t,v in coeff.items())) for i in (0,1)]
            cases.append({"id":case["id"],"baseline":baseline,"net":float(net),"net_bounds":bounds,"residual":baseline-float(net)})
        answer = {"actions":sorted(jobs,key=lambda j:(j["start"],order.index(j["target"]),j["tier"])),
                "slots":slots,"final_tiers":tiers.copy(),"credits":credits,"power":power,
                "active_regions":sorted(regions),"peak_crews":max(len(s["occupied"]) for s in slots),
                "cases":cases,"worst_case_net":float(min(nets)),"total_case_net":float(sum(nets)),"start_vector":vector}
        if fixed_better:
            best_key,best = key,answer
        for i in better_cases:
            group[i] = branch_keys[i],answer

    def walk(s, jobs, tiers, ready, region_until, credits, power, regions):
        if s == h:
            evaluate(jobs,tiers,credits,power,regions)
            return
        occupied = [j for j in jobs if j["start"] <= s < j["finish"]]
        available = []
        for t in candidates:
            k, r = tiers[t]+1, specs[t]["region"]
            if k > 2 or not summaries[t]["rollout_eligible"] or ready.get((t,k-1),0) > s or region_until.get(r,0) > s:
                continue
            finish = s+e["durations"][t][k-1]
            live = finish+e["warmups"][t][k-1]
            if live > h or any(v in e["blackouts"][t] for v in range(s,finish)):
                continue
            if any(ready.get((d["requires"],d["requires_tier"]),h+1) > s
                   for d in e["dependencies"] if d["target"] == t and d["tier"] == k):
                continue
            available.append({"target":t,"tier":k,"start":s,"finish":finish,"ready":live})
        for n in range(min(len(available),e["max_jobs"]-len(jobs),e["crews"][s]-len(occupied))+1):
            for extra in itertools.combinations(available,n):
                rs = [specs[j["target"]]["region"] for j in extra]
                if len(set(rs)) != len(rs):
                    continue
                combined = jobs+list(extra)
                if any(sum(j["start"] <= v < j["finish"] for j in combined) > e["crews"][v] for v in range(s,h)):
                    continue
                nt, nr, nu = tiers.copy(),ready.copy(),region_until.copy()
                nc, np, active = credits,power,set(regions)
                for j in extra:
                    t,k = j["target"],j["tier"]
                    r = specs[t]["region"]
                    nc += specs[t]["cost"][k]-specs[t]["cost"][k-1]
                    np += specs[t]["power"][k]-specs[t]["power"][k-1]
                    if r not in active:
                        nc += planning["regions"][r]["activation_cost"]
                        active.add(r)
                    nt[t],nr[t,k],nu[r] = k,j["ready"],j["finish"]+e["region_gap"]
                if nc > planning["credit_budget"] or np > planning["power_budget"] or len(active) > planning["max_active_regions"]:
                    continue
                if any(sum(nt[t] for t in order if specs[t]["region"] == r) > planning["regions"][r]["max_blocks"] for r in active):
                    continue
                walk(s+1,combined,nt,nr,nu,nc,np,active)
    walk(0,[],dict.fromkeys(order,0),{},{},0,0,set())
    selected = min(groups.values(),key=lambda group:(
        max(branch[0][0] for branch in group),sum(branch[0][0] for branch in group),
        sum(branch[0][1] for branch in group),sum(branch[0][2] for branch in group),
        [v for branch in group for v in branch[0][3]]))
    branches = []
    for i,(_,answer) in enumerate(selected):
        branch = {k:answer[k] for k in ("actions","slots","final_tiers","credits","power","active_regions","peak_crews","start_vector")}
        branch["case"] = answer["cases"][i]
        branches.append(branch)
    best["contingency"] = {
        "reveal":e["reveal"],"prefix":[j for j in branches[0]["actions"] if j["start"] < e["reveal"]],
        "branches":branches,"worst_case_net":min(b["case"]["net"] for b in branches),
        "total_case_net":sum(b["case"]["net"] for b in branches),
        "total_credits":sum(b["credits"] for b in branches),"total_power":sum(b["power"] for b in branches)}
    return best
