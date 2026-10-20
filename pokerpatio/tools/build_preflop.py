"""Build the 169-class preflop equity table (run once; ~20s)."""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.equity import build_table
t = time.time()
tab = build_table(iters=int(sys.argv[1]) if len(sys.argv) > 1 else 1200)
print(f"built {len(tab)} classes in {time.time()-t:.1f}s")
for k in ("AA", "AKs", "AKo", "72o", "22", "T9s"):
    print(k, {n: tab[k][f"n{n}"] for n in range(1, 6)})
