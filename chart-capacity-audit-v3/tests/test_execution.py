import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"solution"))
from schedule import optimize_execution, validate
from grade import probes, invalid_probes
from reference import summarize, convert, close
from execution_ref import expected_execution


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = ROOT/"environment/app"
        cls.data = tuple(json.loads(p.read_text()) for p in
            (ROOT/"solution/readings.json",app/"export-manifest.json",app/"operations.json",app/"planning.json"))
        cls.cases = []
        for i,data in enumerate(probes(*cls.data)):
            summaries = convert(summarize(*data))["targets"]
            cls.cases.append((i,summaries,data[3],convert(expected_execution(summaries,data[3]))))

    def test_independent_solvers_all_valid_inputs(self):
        for i,summaries,p,wanted in self.cases:
            with self.subTest(probe=i):
                self.assertTrue(close(optimize_execution(summaries,p),wanted))

    def test_original_hand_witness(self):
        result = self.cases[0][3]
        self.assertEqual([(a["target"],a["start"],a["ready"]) for a in result["actions"]],
                         [("BS",0,2),("DS",0,1),("BI",3,5)])
        self.assertEqual(result["worst_case_net"],121050)
        self.assertEqual(result["total_case_net"],449910)
        self.assertEqual(result["cases"][0]["net"],157170)
        # Weekday: BS 94,000 + DS 58,850 + BI(-7,200+9,600+1,920).
        self.assertEqual(94000+58850-7200+9600+1920,157170)
        self.assertEqual(result["cases"][1]["net_bounds"],[120529.5,121570.5])
        self.assertEqual(result["slots"][4]["effective_tiers"]["BI"],0)
        self.assertEqual(result["slots"][5]["effective_tiers"]["BI"],1)
        self.assertEqual(result["slots"][1]["effective_tiers"]["BS"],0)

    def test_empty_and_no_crews(self):
        for index in (20,26):
            result = self.cases[index][3]
            self.assertEqual(result["actions"],[])
            self.assertEqual(result["worst_case_net"],0)
            self.assertEqual(result["credits"],0)

    def test_ready_boundary_and_upgrade(self):
        result = self.cases[27][3]
        self.assertEqual(result["final_tiers"]["AS"],2)
        self.assertEqual(len(result["actions"]),2)
        self.assertEqual(result["credits"],8)
        self.assertEqual(result["actions"][1]["start"],result["actions"][0]["ready"])
        self.assertEqual(result["slots"][1]["effective_tiers"]["AS"],0)

    def test_invalid_execution_inputs(self):
        for index,data in enumerate(invalid_probes(*self.data)):
            if index < 10:
                continue
            with self.subTest(probe=index), self.assertRaises(ValueError):
                validate(data[3]["execution"],data[3])

    def test_scheduling_faults_are_rejected(self):
        source = (ROOT/"solution/schedule.py").read_text()
        mutations = {
            "ignore-warmup":('live = finish+e["warmups"][t][k-1]','live = finish'),
            "keep-benefit-during-upgrade":('effective[t] = 0','effective[t] = max(0,tiers[t]-1)'),
            "ignore-region-gap":('j["finish"]+e["region_gap"]','j["finish"]'),
            "ignore-prerequisite":('if any(ready.get((d["requires"],d["requires_tier"]),h+1) > s',
                                    'if False and any(ready.get((d["requires"],d["requires_tier"]),h+1) > s'),
            "ignore-disruption":('disruption = F(e["disruption"])','disruption = F(0)'),
            "optimize-case-sum":('key = (-min(nets),-sum(nets),credits,power,vector)',
                                'key = (-sum(nets),-min(nets),credits,power,vector)'),
            "add-endpoint-benefits":('min(reductions[link["left"]],reductions[link["right"]])',
                                    '(reductions[link["left"]]+reductions[link["right"]])'),
            "double-charge-upgrade":('specs[t]["cost"][k]-specs[t]["cost"][k-1]','specs[t]["cost"][k]'),
            "ignore-crew-limit":('e["crews"][s]-len(occupied)','2'),
            "ignore-blackouts":('if live > h or any(v in e["blackouts"][t] for v in range(s,finish)):','if live > h:'),
            "incorrect-bound-sign":('i if v >= 0 else 1-i','i'),
        }
        for name,(old,new) in mutations.items():
            with self.subTest(mutation=name):
                self.assertEqual(source.count(old),1)
                namespace = {}
                mutated = source.replace(old,new)
                if name == "ignore-crew-limit":
                    mutated = mutated.replace('> e["crews"][v]', '> 2')
                exec(compile(mutated,name,"exec"),namespace)
                rejected = []
                for i,summaries,p,wanted in self.cases:
                    if i not in (0,21,22,23,24,27,28,29,31,32,33):
                        continue
                    got = namespace["optimize_execution"](summaries,p)
                    if not close(got,wanted):
                        rejected.append(i)
                        break
                print("control",name,"rejected by",rejected,flush=True)
                self.assertTrue(rejected,name)


if __name__ == "__main__":
    unittest.main()
