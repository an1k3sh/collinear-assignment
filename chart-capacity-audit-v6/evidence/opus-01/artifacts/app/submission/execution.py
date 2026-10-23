"""Executable change-window scheduling (standard library only).

Implements execution-policy.md: a fixed max-min schedule, a full-reveal
contingent policy and a staged (coarse then exact signal) policy.  All feasible
complete schedules are enumerated exactly; objective values are compared with
exact rational arithmetic scaled to integers.
"""
import math
from fractions import Fraction

from common import InputError, F, fnum, is_num, is_int

TARGETS = ["AS", "AI", "BS", "BI", "CS", "CI", "DS", "DI"]


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _int_in(v, lo, hi, what):
    if not is_int(v) or v < lo or (hi is not None and v > hi):
        raise InputError("execution: %s must be an integer in %s..%s, got %r" % (what, lo, hi if hi is not None else "inf", v))
    return v


def validate_execution(pl, order):
    ex = pl.get("execution")
    if not isinstance(ex, dict):
        raise InputError("execution: object required")
    H = ex.get("horizon")
    if not is_int(H) or H < 1 or H > 12:
        raise InputError("execution: invalid horizon %r (positive integer required)" % (H,))
    cfg = {"horizon": H}
    if "reveal" in ex:
        r = ex["reveal"]
        if not is_int(r) or r < 0 or r > H:
            raise InputError("execution: invalid reveal %r (integer 0..horizon required)" % (r,))
        cfg["reveal"] = r
    else:
        cfg["reveal"] = None
    cands = ex.get("candidates")
    if not isinstance(cands, list):
        raise InputError("execution: candidates list required")
    for c in cands:
        if c not in TARGETS:
            raise InputError("execution: invalid candidate id %r" % (c,))
    if len(set(cands)) != len(cands):
        raise InputError("execution: duplicate candidate ids")
    if len(cands) > 4:
        raise InputError("execution: at most four candidates supported")
    cfg["candidates"] = [t for t in order if t in cands]
    cfg["max_jobs"] = _int_in(ex.get("max_jobs"), 0, None, "max_jobs")
    crews = ex.get("crews")
    if not isinstance(crews, list) or len(crews) != H:
        raise InputError("execution: crews must list one entry per slot (horizon %d)" % H)
    for c in crews:
        _int_in(c, 0, None, "crew count")
    cfg["crews"] = list(crews)
    cfg["region_gap"] = _int_in(ex.get("region_gap", 0), 0, None, "region_gap")
    d = ex.get("disruption", 0)
    if not is_num(d) or d < 0 or d > 1:
        raise InputError("execution: disruption must be a number in [0,1]")
    cfg["disruption"] = d
    durs, warms, blk = ex.get("durations", {}), ex.get("warmups", {}), ex.get("blackouts", {}) or {}
    if not isinstance(durs, dict) or not isinstance(warms, dict) or not isinstance(blk, dict):
        raise InputError("execution: durations, warmups and blackouts must be objects")
    cfg["durations"], cfg["warmups"], cfg["blackouts"] = {}, {}, {}
    for t, v in durs.items():
        if t not in TARGETS:
            raise InputError("execution: durations for invalid target %r" % t)
    for t, v in blk.items():
        if t not in TARGETS:
            raise InputError("execution: blackouts for invalid target %r" % t)
        if not isinstance(v, list):
            raise InputError("execution: blackouts for %s must be a list" % t)
        for s in v:
            if not is_int(s) or s < 0 or s >= H:
                raise InputError("execution: invalid blackout slot %r for %s" % (s, t))
        cfg["blackouts"][t] = set(v)
    for t in cfg["candidates"]:
        dv = durs.get(t)
        if not isinstance(dv, list) or len(dv) != 2 or not all(is_int(x) and x >= 1 for x in dv):
            raise InputError("execution: invalid job duration for %s: %r" % (t, dv))
        wv = warms.get(t, [0, 0])
        if not isinstance(wv, list) or len(wv) != 2 or not all(is_int(x) and x >= 0 for x in wv):
            raise InputError("execution: invalid warmup for %s: %r" % (t, wv))
        cfg["durations"][t] = list(dv)
        cfg["warmups"][t] = list(wv)
        cfg["blackouts"].setdefault(t, set())
    deps = ex.get("dependencies", []) or []
    if not isinstance(deps, list):
        raise InputError("execution: dependencies must be a list")
    cfg["dependencies"] = []
    for dep in deps:
        if not isinstance(dep, dict):
            raise InputError("execution: dependency must be an object")
        t, rq = dep.get("target"), dep.get("requires")
        if t not in cands or rq not in cands:
            raise InputError("execution: dependency references non-candidate %r/%r" % (t, rq))
        ti, rt = dep.get("tier"), dep.get("requires_tier")
        if ti not in (1, 2) or rt not in (1, 2) or isinstance(ti, bool) or isinstance(rt, bool):
            raise InputError("execution: dependency tiers must be 1 or 2")
        cfg["dependencies"].append((t, ti, rq, rt))
    # cycle check including intrinsic tier-1 -> tier-2 edges
    graph = {}
    for t in cands:
        graph.setdefault((t, 1), set()).add((t, 2))
        graph.setdefault((t, 2), set())
    for (t, ti, rq, rt) in cfg["dependencies"]:
        graph.setdefault((rq, rt), set()).add((t, ti))
    color = {}

    def visit(n):
        color[n] = 1
        for m in graph.get(n, ()):
            if color.get(m) == 1:
                raise InputError("execution: cyclic dependencies involving %s tier %d" % m)
            if color.get(m) is None:
                visit(m)
        color[n] = 2

    for n in sorted(graph):
        if color.get(n) is None:
            visit(n)
    links = ex.get("links", []) or []
    if not isinstance(links, list):
        raise InputError("execution: links must be a list")
    cfg["links"] = []
    for ln in links:
        if not isinstance(ln, dict):
            raise InputError("execution: link must be an object")
        l, r, o, f = ln.get("left"), ln.get("right"), ln.get("owner"), ln.get("factor")
        if l not in TARGETS or r not in TARGETS or o not in TARGETS:
            raise InputError("execution: link references invalid target")
        if not is_num(f) or f < 0:
            raise InputError("execution: link factor must be finite and nonnegative")
        cfg["links"].append((l, r, o, f))
    cases = ex.get("cases")
    if not isinstance(cases, list) or not cases:
        raise InputError("execution: at least one forecast case required")
    ids = []
    cfg["cases"] = []
    for c in cases:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]:
            raise InputError("execution: case needs a string id")
        if c["id"] in ids:
            raise InputError("execution: duplicate case id %s" % c["id"])
        ids.append(c["id"])
        exp = c.get("exposure")
        if not isinstance(exp, dict):
            raise InputError("execution: case %s needs an exposure object" % c["id"])
        e2 = {}
        for t in TARGETS:
            arr = exp.get(t)
            if not isinstance(arr, list) or len(arr) != H:
                raise InputError("execution: case %s exposure for %s must have %d entries" % (c["id"], t, H))
            for x in arr:
                if not is_num(x) or x < 0:
                    raise InputError("execution: case %s has negative or nonfinite exposure for %s" % (c["id"], t))
            e2[t] = list(arr)
        for t in exp:
            if t not in TARGETS:
                raise InputError("execution: case %s exposure for invalid target %r" % (c["id"], t))
        cfg["cases"].append({"id": c["id"], "exposure": e2})
    sig = ex.get("signals")
    if sig is None:
        cfg["signals"] = None
    else:
        if not isinstance(sig, dict):
            raise InputError("execution: signals must be an object")
        ca, ea = sig.get("coarse_at"), sig.get("exact_at")
        if not is_int(ca) or not is_int(ea):
            raise InputError("execution: signal boundaries must be integers")
        if not (0 <= ca <= ea <= H):
            raise InputError("execution: signal boundaries must satisfy 0 <= coarse_at <= exact_at <= horizon")
        g = sig.get("groups")
        if not isinstance(g, list):
            raise InputError("execution: signals.groups list required")
        if len(g) != len(cfg["cases"]):
            raise InputError("execution: signals.groups has %d labels for %d cases" % (len(g), len(cfg["cases"])))
        for lab in g:
            if not isinstance(lab, str) or not lab:
                raise InputError("execution: group labels must be nonempty strings")
        w = sig.get("sum_weight")
        if not is_num(w) or w < 0 or w > 0.5:
            raise InputError("execution: signals.sum_weight must be a number in [0,0.5]")
        cfg["signals"] = {"coarse_at": ca, "exact_at": ea, "groups": list(g), "sum_weight": w}
    return cfg


# --------------------------------------------------------------------------
# Schedule enumeration
# --------------------------------------------------------------------------

def _job(t, tier, start, cfg):
    d = cfg["durations"][t][tier - 1]
    w = cfg["warmups"][t][tier - 1]
    fin = start + d
    return (t, tier, start, fin, fin + w)


def _target_options(t, cfg):
    H = cfg["horizon"]
    blk = cfg["blackouts"].get(t, set())
    crews = cfg["crews"]
    gap = cfg["region_gap"]

    def ok(job):
        if job[4] > H:
            return False
        for s in range(job[2], job[3]):
            if s in blk or crews[s] < 1:
                return False
        return True

    opts = [()]
    for s1 in range(H):
        j1 = _job(t, 1, s1, cfg)
        if not ok(j1):
            continue
        opts.append((j1,))
        for s2 in range(max(j1[4], j1[3] + gap), H):
            j2 = _job(t, 2, s2, cfg)
            if ok(j2):
                opts.append((j1, j2))
    return opts


def _eff_tiers(jobs, H):
    """Per slot: (effective tier, installed tier, occupied flag)."""
    eff, inst, occ = [], [], []
    for s in range(H):
        o = any(j[2] <= s < j[3] for j in jobs)
        ready = 0
        for j in jobs:
            if j[4] <= s:
                ready = max(ready, j[1])
        occ.append(o)
        inst.append(ready)
        eff.append(0 if o else ready)
    return eff, inst, occ


class Model:
    def __init__(self, cfg, pl, order, targets, eligible):
        self.cfg, self.pl, self.order = cfg, pl, order
        self.H = cfg["horizon"]
        self.region = {t: pl["targets"][t]["region"] for t in order}
        self.weight = {t: F(pl["targets"][t]["risk_weight"]) for t in order}
        self.red = {t: [F(x) for x in pl["targets"][t]["reduction"]] for t in order}
        self.errors = {t: F(targets[t]["errors"]) for t in order}
        self.err_bounds = {t: (F(targets[t]["error_bounds"][0]), F(targets[t]["error_bounds"][1])) for t in order}
        self.R = {t: self.errors[t] * self.weight[t] for t in order}
        self.disr = F(cfg["disruption"])
        self.cases = cfg["cases"]
        self.exp = [{t: [F(x) for x in c["exposure"][t]] for t in order} for c in self.cases]
        self.cands = [t for t in cfg["candidates"] if eligible.get(t)]
        self.eligible = eligible
        self.opts = {t: _target_options(t, cfg) for t in self.cands}

    # coefficient of errors_t for target t's own terms, given its jobs, in case k
    def own_coef(self, t, jobs, k):
        eff, _, occ = _eff_tiers(jobs, self.H)
        e = self.exp[k][t]
        tot = Fraction(0)
        for s in range(self.H):
            tot += e[s] * (self.red[t][eff[s]] - (self.disr if occ[s] else 0))
        return self.weight[t] * tot

    def link_coef(self, link, jobs_l, jobs_r, k):
        l, r, o, f = link
        el, _, _ = _eff_tiers(jobs_l, self.H)
        er, _, _ = _eff_tiers(jobs_r, self.H)
        e = self.exp[k][o]
        tot = Fraction(0)
        for s in range(self.H):
            tot += e[s] * min(self.red[l][el[s]], self.red[r][er[s]])
        return self.weight[o] * F(f) * tot

    def resources(self, tiers):
        pl = self.pl
        credits, power = Fraction(0), Fraction(0)
        active, blocks = set(), {}
        for t in self.order:
            k = tiers.get(t, 0)
            credits += F(pl["targets"][t]["cost"][k])
            power += F(pl["targets"][t]["power"][k])
            if k:
                active.add(self.region[t])
            blocks[self.region[t]] = blocks.get(self.region[t], 0) + k
        for r in active:
            credits += F(pl["regions"][r]["activation_cost"])
        return credits, power, sorted(active), blocks

    def static_ok(self, tiers):
        credits, power, active, blocks = self.resources(tiers)
        pl = self.pl
        if credits > F(pl["credit_budget"]) or power > F(pl["power_budget"]):
            return False
        if len(active) > pl["max_active_regions"]:
            return False
        for r, b in blocks.items():
            if b > pl["regions"][r]["max_blocks"]:
                return False
        for t, k in tiers.items():
            if k and (not self.eligible.get(t) or pl["regions"][self.region[t]].get("frozen")):
                return False
        return True

    def enumerate(self):
        cfg, H = self.cfg, self.H
        cands = self.cands
        nC = len(self.cases)
        # exact contributions, then integer scaling
        own = {t: [[self.own_coef(t, op, k) * self.errors[t] for k in range(nC)] for op in self.opts[t]] for t in cands}
        link_tabs = []
        for li, link in enumerate(cfg["links"]):
            l, r, o, f = link
            if l in cands and r in cands:
                tab = {}
                for a, opa in enumerate(self.opts[l]):
                    for b, opb in enumerate(self.opts[r]):
                        tab[(a, b)] = [self.link_coef(link, opa, opb, k) * self.errors[o] for k in range(nC)]
                link_tabs.append((cands.index(l), cands.index(r), tab))
        dens = 1
        for t in cands:
            for row in own[t]:
                for v in row:
                    dens = dens * v.denominator // math.gcd(dens, v.denominator)
        for _, _, tab in link_tabs:
            for row in tab.values():
                for v in row:
                    dens = dens * v.denominator // math.gcd(dens, v.denominator)
        self.scale = dens
        own_i = {t: [[int(v * dens) for v in row] for row in own[t]] for t in cands}
        link_i = [(a, b, {key: [int(v * dens) for v in row] for key, row in tab.items()}) for a, b, tab in link_tabs]

        crews = cfg["crews"]
        gap = cfg["region_gap"]
        maxj = cfg["max_jobs"]
        deps = cfg["dependencies"]
        schedules = []
        used = [0] * H
        chosen = []
        jobs_acc = []

        def conflicts(job):
            reg = self.region[job[0]]
            for j in jobs_acc:
                if j[0] == job[0]:
                    continue  # same-target spacing handled when building options
                if self.region[j[0]] != reg:
                    continue
                if not (j[3] + gap <= job[2] or job[3] + gap <= j[2]):
                    return True
            return False

        def leaf():
            tiers = {}
            ready = {}
            for j in jobs_acc:
                tiers[j[0]] = max(tiers.get(j[0], 0), j[1])
                ready[(j[0], j[1])] = j[4]
            for (t, ti, rq, rt) in deps:
                mine = [j for j in jobs_acc if j[0] == t and j[1] == ti]
                if not mine:
                    continue
                pr = ready.get((rq, rt))
                if pr is None or pr > mine[0][2]:
                    return
            if not self.static_ok(tiers):
                return
            nets = [0] * nC
            for i, t in enumerate(cands):
                row = own_i[t][chosen[i]]
                for k in range(nC):
                    nets[k] += row[k]
            for a, b, tab in link_i:
                row = tab[(chosen[a], chosen[b])]
                for k in range(nC):
                    nets[k] += row[k]
            credits, power, _, _ = self.resources(tiers)
            sv = []
            for t in self.order:
                s1 = s2 = H + 1
                for j in jobs_acc:
                    if j[0] == t:
                        if j[1] == 1:
                            s1 = j[2]
                        else:
                            s2 = j[2]
                sv += [s1, s2]
            schedules.append({"jobs": tuple(sorted(jobs_acc, key=lambda j: (j[2], self.order.index(j[0]), j[1]))),
                              "nets": tuple(nets), "credits": credits, "power": power,
                              "sv": tuple(sv), "tiers": tiers})

        def dfs(i):
            if i == len(cands):
                leaf()
                return
            t = cands[i]
            for oi, op in enumerate(self.opts[t]):
                if len(jobs_acc) + len(op) > maxj:
                    continue
                bad = False
                added = []
                for j in op:
                    if conflicts(j):
                        bad = True
                        break
                    for s in range(j[2], j[3]):
                        if used[s] + 1 > crews[s]:
                            bad = True
                            break
                        used[s] += 1
                        added.append(s)
                    if bad:
                        break
                if not bad:
                    chosen.append(oi)
                    jobs_acc.extend(op)
                    dfs(i + 1)
                    chosen.pop()
                    del jobs_acc[len(jobs_acc) - len(op):]
                for s in added:
                    used[s] -= 1

        dfs(0)
        return schedules

    # ---------------------------------------------------------------
    def describe(self, sched, case_indices):
        H, order = self.H, self.order
        jobs = sched["jobs"]
        per = {t: [j for j in jobs if j[0] == t] for t in order}
        states = {t: _eff_tiers(per[t], H) for t in order}
        actions = [{"target": j[0], "tier": j[1], "start": j[2], "finish": j[3], "ready": j[4]} for j in jobs]
        slots = []
        crews_used = []
        for s in range(H):
            occ = [t for t in order if states[t][2][s]]
            crews_used.append(len(occ))
            slots.append({"slot": s, "occupied": occ,
                          "effective_tiers": {t: states[t][0][s] for t in order},
                          "installed_tiers": {t: states[t][1][s] for t in order},
                          "crews_used": len(occ), "crews_available": self.cfg["crews"][s]})
        tiers = {t: (max([j[1] for j in per[t]]) if per[t] else 0) for t in order}
        credits, power, active, _ = self.resources(tiers)
        case_recs = []
        for k in case_indices:
            coef = {t: Fraction(0) for t in order}
            slot_net = []
            for s in range(H):
                sn = Fraction(0)
                for t in order:
                    eff, _, occ = states[t][0][s], None, states[t][2][s]
                    v = self.weight[t] * self.exp[k][t][s] * (self.red[t][eff] - (self.disr if occ else 0))
                    coef[t] += v
                    sn += v * self.errors[t]
                for (l, r, o, f) in self.cfg["links"]:
                    v = self.weight[o] * F(f) * self.exp[k][o][s] * min(self.red[l][states[l][0][s]], self.red[r][states[r][0][s]])
                    coef[o] += v
                    sn += v * self.errors[o]
                slot_net.append(sn)
            net = sum((coef[t] * self.errors[t] for t in order), Fraction(0))
            lo = hi = Fraction(0)
            for t in order:
                c = coef[t]
                el, eh = self.err_bounds[t]
                if c >= 0:
                    lo += c * el
                    hi += c * eh
                else:
                    lo += c * eh
                    hi += c * el
            base = sum((self.R[t] * sum(self.exp[k][t], Fraction(0)) for t in order), Fraction(0))
            if net * self.scale != sched["nets"][k]:
                raise RuntimeError("internal consistency check failed for case %s" % self.cases[k]["id"])
            for s in range(H):
                slots[s].setdefault("case_net", {})[self.cases[k]["id"]] = fnum(slot_net[s])
            case_recs.append({"id": self.cases[k]["id"], "baseline": fnum(base), "net": fnum(net),
                              "net_bounds": [fnum(lo), fnum(hi)], "residual": fnum(base - net),
                              "error_coefficients": {t: fnum(coef[t]) for t in order}})
        return {"actions": actions, "slots": slots, "final_tiers": tiers,
                "credits": fnum(credits), "power": fnum(power), "active_regions": active,
                "peak_crews": max(crews_used) if crews_used else 0,
                "start_vector": list(sched["sv"]), "_cases": case_recs}


def _prefix(sched, t):
    return tuple(j for j in sched["jobs"] if j[2] < t)


def staged_policy(schedules, nC, coarse, exact, labels, w):
    """Optimal policy: common jobs before `coarse`; same-label cases share jobs before `exact`.

    Objective key: maximize min + w*sum, then min, then sum; minimize sum
    credits, sum power, then concatenated start vectors in case order.
    Returns a list of chosen schedule indices (one per case).
    """
    w = F(w)
    # per exact-prefix, best schedule for each case
    best_p1 = {}
    p0_of = {}
    for i, s in enumerate(schedules):
        p1 = _prefix(s, exact)
        p0 = _prefix(s, coarse)
        p0_of[p1] = p0
        row = best_p1.setdefault(p1, [None] * nC)
        for k in range(nC):
            key = (-s["nets"][k], s["credits"], s["power"], s["sv"])
            if row[k] is None or key < row[k][0]:
                row[k] = (key, i)
    buckets = {}
    for p1, p0 in p0_of.items():
        buckets.setdefault(p0, []).append(p1)
    groups = []
    for k, lab in enumerate(labels):
        for g in groups:
            if g[0] == lab:
                g[1].append(k)
                break
        else:
            groups.append((lab, [k]))
    best = None
    for p0 in sorted(buckets):
        opts_by_group = []
        for lab, ks in groups:
            opts = []
            for p1 in buckets[p0]:
                row = best_p1[p1]
                idx = [row[k][1] for k in ks]
                nets = [schedules[i]["nets"][k] for i, k in zip(idx, ks)]
                opts.append({"min": min(nets), "sum": sum(nets),
                             "cred": sum((schedules[i]["credits"] for i in idx), Fraction(0)),
                             "pow": sum((schedules[i]["power"] for i in idx), Fraction(0)),
                             "lex": tuple(x for i in idx for x in schedules[i]["sv"]),
                             "idx": idx})
            opts.sort(key=lambda o: -o["min"])
            opts_by_group.append(opts)
        taus = sorted({o["min"] for opts in opts_by_group for o in opts}, reverse=True)
        ptr = [0] * len(groups)
        run = [None] * len(groups)
        for tau in taus:
            for gi, opts in enumerate(opts_by_group):
                while ptr[gi] < len(opts) and opts[ptr[gi]]["min"] >= tau:
                    o = opts[ptr[gi]]
                    if run[gi] is None or (-o["sum"], o["cred"], o["pow"], o["lex"]) < \
                            (-run[gi]["sum"], run[gi]["cred"], run[gi]["pow"], run[gi]["lex"]):
                        run[gi] = o
                    ptr[gi] += 1
            if any(r is None for r in run):
                continue
            choice = [None] * nC
            for gi, (lab, ks) in enumerate(groups):
                for k, i in zip(ks, run[gi]["idx"]):
                    choice[k] = i
            nets = [schedules[choice[k]]["nets"][k] for k in range(nC)]
            mn, sm = min(nets), sum(nets)
            key = (-(mn + w * sm), -mn, -sm,
                   sum((schedules[i]["credits"] for i in choice), Fraction(0)),
                   sum((schedules[i]["power"] for i in choice), Fraction(0)),
                   tuple(x for i in choice for x in schedules[i]["sv"]))
            if best is None or key < best[0]:
                best = (key, choice)
    return best[1]


def _actions(jobs):
    return [{"target": j[0], "tier": j[1], "start": j[2], "finish": j[3], "ready": j[4]} for j in jobs]


def solve(cfg, pl, order, targets, eligible):
    model = Model(cfg, pl, order, targets, eligible)
    schedules = model.enumerate()
    nC = len(cfg["cases"])
    scale = model.scale

    def val(x):
        return fnum(Fraction(x, scale))

    # fixed schedule: maximize the minimum whole-window case net
    fixed_i = min(range(len(schedules)), key=lambda i: (
        -min(schedules[i]["nets"]), -sum(schedules[i]["nets"]),
        schedules[i]["credits"], schedules[i]["power"], schedules[i]["sv"]))
    fs = schedules[fixed_i]
    d = model.describe(fs, range(nC))
    cases = d.pop("_cases")
    fixed = dict(d)
    fixed["cases"] = [{k: v for k, v in c.items()} for c in cases]
    fixed["worst_case_net"] = val(min(fs["nets"]))
    fixed["total_case_net"] = val(sum(fs["nets"]))
    fixed["feasible_schedules"] = len(schedules)
    fixed["eligible_candidates"] = list(model.cands)
    fixed["excluded_candidates"] = {t: "not rollout_eligible" for t in cfg["candidates"] if t not in model.cands}

    def policy_block(choice, coarse):
        branches = []
        for k, i in enumerate(choice):
            d = model.describe(schedules[i], [k])
            c = d.pop("_cases")[0]
            d["case"] = c
            branches.append(d)
        nets = [schedules[i]["nets"][k] for k, i in enumerate(choice)]
        prefix = _prefix(schedules[choice[0]], coarse)
        for i in choice:
            assert _prefix(schedules[i], coarse) == prefix
        return branches, nets, prefix

    # full-reveal contingency
    reveal = cfg.get("reveal")
    if reveal is not None:
        choice = staged_policy(schedules, nC, reveal, reveal, ["case-%d" % k for k in range(nC)], 0)
        branches, nets, prefix = policy_block(choice, reveal)
        fixed["contingency"] = {
            "reveal": reveal, "prefix": _actions(prefix), "branches": branches,
            "worst_case_net": val(min(nets)), "total_case_net": val(sum(nets)),
            "total_credits": fnum(sum((schedules[i]["credits"] for i in choice), Fraction(0))),
            "total_power": fnum(sum((schedules[i]["power"] for i in choice), Fraction(0))),
            "information_value": val(min(nets) - min(fs["nets"])),
        }
    else:
        fixed["contingency"] = None

    sig = cfg.get("signals")
    if sig is not None:
        ca, ea, labels, w = sig["coarse_at"], sig["exact_at"], sig["groups"], sig["sum_weight"]
        choice = staged_policy(schedules, nC, ca, ea, labels, w)
        branches, nets, prefix = policy_block(choice, ca)
        gp = []
        for lab in sorted(set(labels)):
            ks = [k for k in range(nC) if labels[k] == lab]
            pf = _prefix(schedules[choice[ks[0]]], ea)
            for k in ks:
                assert _prefix(schedules[choice[k]], ea) == pf
            gp.append({"signal": lab, "case_ids": [cfg["cases"][k]["id"] for k in ks], "actions": _actions(pf)})
        mn, sm = min(nets), sum(nets)
        fixed_value = F(min(fs["nets"])) + F(w) * F(sum(fs["nets"]))
        fixed["staged"] = {
            "coarse_at": ca, "exact_at": ea, "sum_weight": w, "prefix": _actions(prefix),
            "group_prefixes": gp, "branches": branches,
            "policy_value": fnum(Fraction(mn, scale) + F(w) * Fraction(sm, scale)),
            "worst_case_net": val(mn), "total_case_net": val(sm),
            "total_credits": fnum(sum((schedules[i]["credits"] for i in choice), Fraction(0))),
            "total_power": fnum(sum((schedules[i]["power"] for i in choice), Fraction(0))),
            "fixed_schedule_policy_value": fnum(fixed_value / scale),
        }
    else:
        fixed["staged"] = None
    return fixed
