#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <random>
#include <vector>
using namespace std;

int main(int argc, char** argv) {
    int n, budget;
    long long target;
    cin >> n >> budget >> target;
    vector<int> zone(n), fixed(n), minutes(n), base(n);
    for (auto* values : {&zone, &fixed, &minutes, &base})
        for (int& value : *values) cin >> value;
    vector<vector<long long>> c(n, vector<long long>(n)), d = c;
    for (auto* matrix : {&c, &d})
        for (auto& row : *matrix)
            for (auto& value : row) cin >> value;
    auto cost = [&](const vector<int>& p) {
        long long value = 0;
        for (int i = 0; i < n; ++i)
            for (int j = 0; j < i; ++j) value += c[i][j] * d[p[i]][p[j]];
        return value;
    };
    auto change = [&](const vector<int>& p, int i, int j) {
        long long delta = 0;
        for (int k = 0; k < n; ++k)
            if (k != i && k != j)
                delta += (c[i][k] - c[j][k]) * (d[p[j]][p[k]] - d[p[i]][p[k]]);
        return delta;
    };
    vector<int> movable;
    for (int i = 0; i < n; ++i) if (!fixed[i]) movable.push_back(i);
    unsigned seed = argc > 1 ? stoul(argv[1]) : 7341;
    int restarts = argc > 2 ? stoi(argv[2]) : 384;
    int steps = argc > 3 ? stoi(argv[3]) : 600000;
    mt19937 rng(seed);
    uniform_real_distribution<double> uniform(0.0, 1.0);
    vector<int> best = base;
    long long best_cost = cost(base);
    int best_labor = 0;
    for (int restart = 0; restart < restarts; ++restart) {
        vector<int> p = restart % 3 == 0 ? base : best;
        long long value = cost(p);
        int labor = 0;
        for (int i = 0; i < n; ++i) if (p[i] != base[i]) labor += minutes[i];
        double initial = 7000.0 * (1 + (restart % 4));
        double cooling = log(initial / 1.0) / steps;
        for (int step = 0; step < steps; ++step) {
            double temperature = initial * exp(-cooling * step);
            int i = movable[rng() % movable.size()], j = movable[rng() % movable.size()];
            if (i == j || zone[i] != zone[j]) continue;
            int next_labor = labor
                - (p[i] != base[i] ? minutes[i] : 0) - (p[j] != base[j] ? minutes[j] : 0)
                + (p[j] != base[i] ? minutes[i] : 0) + (p[i] != base[j] ? minutes[j] : 0);
            if (next_labor > budget) continue;
            long long delta = change(p, i, j);
            if (delta <= 0 || uniform(rng) < exp(-double(delta) / temperature)) {
                swap(p[i], p[j]);
                value += delta;
                labor = next_labor;
                if (value < best_cost) {
                    best = p;
                    best_cost = value;
                    best_labor = labor;
                }
            }
        }
        // Exact steepest descent makes the saved certificate independent of the
        // cooling tail and validates incremental delta accounting.
        bool improved = true;
        while (improved) {
            improved = false;
            long long best_delta = 0;
            int bi = -1, bj = -1, bl = labor;
            for (int i : movable) for (int j : movable) {
                if (i >= j || zone[i] != zone[j]) continue;
                int nl = labor - (p[i] != base[i] ? minutes[i] : 0) - (p[j] != base[j] ? minutes[j] : 0)
                    + (p[j] != base[i] ? minutes[i] : 0) + (p[i] != base[j] ? minutes[j] : 0);
                if (nl > budget) continue;
                long long delta = change(p, i, j);
                if (delta < best_delta) { best_delta = delta; bi = i; bj = j; bl = nl; }
            }
            if (bi >= 0) {
                swap(p[bi], p[bj]);
                labor = bl;
                value += best_delta;
                improved = true;
            }
        }
        if (cost(p) != value) { cerr << "Delta accounting error\n"; return 2; }
        if (value < best_cost) { best = p; best_cost = value; best_labor = labor; }
        cerr << "restart " << restart << " best " << best_cost << " labor " << best_labor << "\n";
        if (best_cost <= target) break;
    }
    if (cost(best) != best_cost) return 3;
    cout << best_cost << " " << best_labor << "\n";
    for (int value : best) cout << value << " ";
    cout << "\n";
    return best_cost <= target ? 0 : 1;
}
