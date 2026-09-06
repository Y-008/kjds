namespace KJDS

structure Scope where
  tenant : String
  entity : String
  store : String
  deriving DecidableEq, Repr

def Scope.exact (left right : Scope) : Prop :=
  left = right

theorem Scope.exact_refl (scope : Scope) : scope.exact scope := by
  rfl

theorem Scope.exact_symmetric {left right : Scope} :
    left.exact right → right.exact left := by
  intro h
  exact h.symm

end KJDS
