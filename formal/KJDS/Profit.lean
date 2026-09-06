import KJDS.Order

namespace KJDS

def cm3 (netSales fullCost : Int) : Int := netSales - fullCost

theorem cm3_definition (netSales fullCost : Int) :
    cm3 netSales fullCost = netSales - fullCost := by
  rfl

theorem cm3_zero_cost (netSales : Int) : cm3 netSales 0 = netSales := by
  simp [cm3]

theorem order_contribution_is_cm3 (order : Order) (fullCost : Int) :
    cm3 order.netSales fullCost = order.contribution fullCost := by
  rfl

end KJDS
