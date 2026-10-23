// Simulated annealing for constrained QAP reslotting.
// Input (stdin): n, budget, then per SKU: zone fixed move_minutes baseline_slot,
// then per slot: zone, then n*n flow matrix, then n*n distance matrix.
// Args: seed iterations restarts. Output: best cost, labor, slot per SKU.
#include <bits/stdc++.h>
using namespace std;
typedef long long ll;
int n, budget;
vector<int> zoneS, fixedS, mv, base, zoneL;
vector<ll> F, D;
ll cost(const vector<int>& p){ ll c=0; for(int i=0;i<n;i++)for(int j=0;j<n;j++) c+=F[i*n+j]*D[p[i]*n+p[j]]; return c; }
ll swapDelta(const vector<int>& p,int a,int b){
  int pa=p[a],pb=p[b]; ll d=0;
  for(int k=0;k<n;k++){ if(k==a||k==b) continue; int pk=p[k];
    d+=F[a*n+k]*(D[pb*n+pk]-D[pa*n+pk])+F[k*n+a]*(D[pk*n+pb]-D[pk*n+pa])
      +F[b*n+k]*(D[pa*n+pk]-D[pb*n+pk])+F[k*n+b]*(D[pk*n+pa]-D[pk*n+pb]); }
  d+=F[a*n+b]*(D[pb*n+pa]-D[pa*n+pb])+F[b*n+a]*(D[pa*n+pb]-D[pb*n+pa]);
  d+=F[a*n+a]*(D[pb*n+pb]-D[pa*n+pa])+F[b*n+b]*(D[pa*n+pa]-D[pb*n+pb]);
  return d;
}
int lab(int s,int slot){ return slot!=base[s]?mv[s]:0; }
int main(int argc,char**argv){
  unsigned seed=atoi(argv[1]); ll iters=atoll(argv[2]); int restarts=atoi(argv[3]);
  double T0a=argc>4?atof(argv[4]):3000, T1a=argc>5?atof(argv[5]):2;
  cin>>n>>budget; if(getenv("BUDGET")) budget=atoi(getenv("BUDGET")); zoneS.resize(n);fixedS.resize(n);mv.resize(n);base.resize(n);zoneL.resize(n);
  for(int i=0;i<n;i++)cin>>zoneS[i]>>fixedS[i]>>mv[i]>>base[i];
  for(int i=0;i<n;i++)cin>>zoneL[i];
  F.resize(n*n);D.resize(n*n); for(auto&x:F)cin>>x; for(auto&x:D)cin>>x;
  mt19937_64 rng(seed); uniform_real_distribution<double> U(0,1);
  vector<vector<int>> byZone(2); for(int i=0;i<n;i++) if(!fixedS[i]) byZone[zoneS[i]].push_back(i);
  vector<int> best=base; ll bestC=cost(base);
  for(int r=0;r<restarts;r++){
    vector<int> p=base; ll c=cost(base); int L=0;
    if(r%2==1){ p=best; c=bestC; for(int i=0;i<n;i++)L+=lab(i,p[i]); }
    // Soft labor penalty: lambda grows geometrically so the end of each run is
    // effectively hard-constrained; only budget-feasible states update best.
    double T0=T0a,T1=T1a, lam0=20, lam1=50000;
    for(ll it=0;it<iters;it++){
      double f=(double)it/iters, T=T0*pow(T1/T0,f), lam=lam0*pow(lam1/lam0,f);
      auto pen=[&](int l){ return lam*max(0,l-budget); };
      auto& g=byZone[rng()%2]; int m=g.size();
      int a=g[rng()%m], b=g[rng()%m]; if(a==b)continue;
      if(rng()%3==0){ // 3-cycle a->slot(b), b->slot(c), c->slot(a) as two swaps
        int cc=g[rng()%m]; if(cc==a||cc==b)continue;
        int nL=L-lab(a,p[a])-lab(b,p[b])-lab(cc,p[cc])+lab(a,p[b])+lab(b,p[cc])+lab(cc,p[a]);
        ll d1=swapDelta(p,a,b); swap(p[a],p[b]);
        ll d2=swapDelta(p,b,cc); swap(p[b],p[cc]);
        double dd=(d1+d2)+pen(nL)-pen(L);
        if(dd<=0||U(rng)<exp(-dd/T)){ c+=d1+d2; L=nL; if(L<=budget&&c<bestC){bestC=c;best=p;} }
        else { swap(p[b],p[cc]); swap(p[a],p[b]); }
        continue;
      }
      int nL=L-lab(a,p[a])-lab(b,p[b])+lab(a,p[b])+lab(b,p[a]);
      ll d=swapDelta(p,a,b); double dd=d+pen(nL)-pen(L);
      if(dd<=0||U(rng)<exp(-dd/T)){ swap(p[a],p[b]); c+=d; L=nL;
        if(L<=budget&&c<bestC){bestC=c;best=p;} }
    }
  }
  int L=0; for(int i=0;i<n;i++)L+=lab(i,best[i]);
  cout<<cost(best)<<" "<<L<<"\n"; for(int i=0;i<n;i++)cout<<best[i]<<" "; cout<<"\n";
}
