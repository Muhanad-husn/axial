import json
b = json.load(open("C:/Users/mou97/AppData/Local/Temp/before.json")); a = json.load(open("C:/Users/mou97/AppData/Local/Temp/after.json"))
B, A = b["pages"], a["pages"]
over, sample = b["over"], b["sample"]

moved = [p for p in sample if B[p] != A[p]]
print(f"CONTROL: {len(sample)} pages at or under the limit")
print(f"  changed in any way: {len(moved)}")
if moved:
    for p in moved[:5]:
        print(f"    {p}\n      before {B[p]['ids']}\n      after  {A[p]['ids']}")

print(f"\nOVER-LIMIT: {len(over)} pages")
tot_changed = [p for p in over if B[p]["total"] != A[p]["total"]]
print(f"  `total` (the true pre-cap count) changed on: {len(tot_changed)}")
gained = [p for p in over if len(A[p]["sources"]) > len(B[p]["sources"])]
print(f"  gained at least one source: {len(gained)}")
lost = [p for p in over if set(B[p]["sources"]) - set(A[p]["sources"])]
print(f"  LOST a source that was there before: {len(lost)}")
full = [p for p in over if len(A[p]["sources"]) == len(A[p]["ids"])]
print(f"  now exactly one note per source: {len(full)} of {len(over)}")
prefix = [p for p in over if A[p]["ids"][:len(B[p]["ids"])] == B[p]["ids"]]
print(f"  the old window survives as an exact PREFIX of the new one: {len(prefix)} of {len(over)}")

gb = sum(len(B[p]["ids"]) for p in over); ga = sum(len(A[p]["ids"]) for p in over)
print(f"\n  notes returned across those pages: {gb} -> {ga}  ({ga/gb:.2f}x)")
sb = sum(len(B[p]["ids"]) for p in sample); sa = sum(len(A[p]["ids"]) for p in sample)
print(f"  notes returned across the control:  {sb} -> {sa}")
