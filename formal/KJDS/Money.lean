namespace KJDS

structure Money where
  amount : Int
  currency : String
  deriving DecidableEq, Repr

def Money.add (left right : Money) (sameCurrency : left.currency = right.currency) : Money :=
  { amount := left.amount + right.amount, currency := left.currency }

theorem Money.add_amount (left right : Money) (h : left.currency = right.currency) :
    (left.add right h).amount = left.amount + right.amount := by
  rfl

end KJDS
