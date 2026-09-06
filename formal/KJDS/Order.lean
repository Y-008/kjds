namespace KJDS

structure Order where
  gross : Int
  discount : Int
  refund : Int
  fees : Int
  deriving DecidableEq, Repr

def Order.netSales (order : Order) : Int :=
  order.gross - order.discount - order.refund

theorem Order.netSales_definition (order : Order) :
    order.netSales = order.gross - order.discount - order.refund := by
  rfl

def Order.contribution (order : Order) (fullCost : Int) : Int :=
  order.netSales - fullCost

theorem Order.contribution_definition (order : Order) (fullCost : Int) :
    order.contribution fullCost = order.gross - order.discount - order.refund - fullCost := by
  rfl

end KJDS
