namespace KJDS

structure TemporalTimes where
  event : Nat
  observed : Nat
  effective : Nat
  settled : Option Nat
  deriving DecidableEq, Repr

def TemporalTimes.visibleAt (times : TemporalTimes) (cutoff : Nat) : Prop :=
  times.observed ≤ cutoff

theorem TemporalTimes.visibleAt_monotone
    {times : TemporalTimes} {early late : Nat}
    (hVisible : times.visibleAt early) (hOrder : early ≤ late) :
    times.visibleAt late := by
  exact Nat.le_trans hVisible hOrder

theorem TemporalTimes.visibleAt_refl (times : TemporalTimes) :
    times.visibleAt times.observed := by
  exact Nat.le_refl _

end KJDS
