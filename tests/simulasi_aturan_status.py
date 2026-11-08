import numpy as np
rng=np.random.default_rng(42)
F=5
# correlation: features 0-2 (rate, pause freq, pause dur) correlated 0.6; MATTR & completeness 0.2
C=np.full((F,F),0.2); C[:3,:3]=0.6; np.fill_diagonal(C,1)
L=np.linalg.cholesky(C)
def run(nbase, nsess, onset=None, slope=0.0, sims=4000, need=2, z=1.96, consec=3):
    alarms=0; delays=[]
    for _ in range(sims):
        x=(L@rng.standard_normal((F,nbase+nsess))).T  # within-person noise, SD=1, already "worse" direction positive
        if onset is not None:
            t=np.arange(nsess); drift=np.clip(t-onset,0,None)*slope
            x[nbase:]+=drift[:,None]
        b=x[:nbase]; m=b.mean(0); s=b.std(0,ddof=1)
        zz=(x[nbase:]-m)/s
        hit=(zz>=z).sum(1)>=need
        run_=0; first=None
        for i,h in enumerate(hit):
            run_=run_+1 if h else 0
            if run_>=consec: first=i; break
        if first is not None:
            alarms+=1
            if onset is not None: delays.append(first-onset)
    return alarms/sims, (np.median(delays) if delays else None)
print("False alarm within 52 weekly sessions (no real change):")
for nb in (4,6,8):
    fa,_=run(nb,52); print(f"  baseline {nb} sesi: {fa*100:.1f}%")
print("With SD floor equiv: use baseline 4 but s=max(s,1.0*true)")
print("Detection, gradual decline 0.1 SD/week starting week 10, 52 sessions:")
for nb in (4,6,8):
    p,d=run(nb,52,onset=10,slope=0.1); print(f"  baseline {nb}: terdeteksi {p*100:.0f}%, median {d} minggu setelah mulai")

print("\nRule >=3 of 5 (Disarankan periksa):")
for nb in (4,6,8):
    fa,_=run(nb,52,need=3); p,d=run(nb,52,onset=10,slope=0.1,need=3)
    print(f"  baseline {nb}: alarm palsu {fa*100:.1f}%, deteksi {p*100:.0f}%, median {d} mgg")
print("\nTanpa syarat 3 sesi berturut (1 sesi cukup), baseline 6, >=2:")
fa,_=run(6,52,consec=1); print(f"  alarm palsu {fa*100:.1f}%")

# population cutoff comparison
def pop(sims=4000, sdb=1.5, onset=10, slope=0.1, nsess=52, need=2, consec=3):
    det=[];fa=0;missed=0
    tot=np.sqrt(sdb**2+1)
    for _ in range(sims):
        mu=rng.normal(0,sdb,F)
        x=(L@rng.standard_normal((F,nsess))).T+mu
        # no-change false alarm
        hit=((x/tot)>=1.96).sum(1)>=need
        r=0;f=None
        for i,h in enumerate(hit):
            r=r+1 if h else 0
            if r>=consec: f=i;break
        if f is not None: fa+=1
        t=np.arange(nsess); x2=x+np.clip(t-onset,0,None)[:,None]*slope
        hit=((x2/tot)>=1.96).sum(1)>=need
        r=0;f=None
        for i,h in enumerate(hit):
            r=r+1 if h else 0
            if r>=consec: f=i;break
        if f is None or f<onset: missed+= (f is None)
        else: det.append(f-onset)
    return fa/sims, 1-missed/sims, np.median(det)
fa,p,d=pop()
print(f"\nAmbang populasi (variasi antar-orang 1.5x): alarm palsu {fa*100:.1f}%, terdeteksi {p*100:.0f}%, median {d} mgg")
