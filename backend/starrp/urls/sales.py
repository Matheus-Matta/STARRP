from starrp.views import commissions, operations, reviews, sale_items, sales


def register(router):
    router.register("sales/items", sale_items.SaleItemViewSet, basename="sale-items")
    router.register("sales", sales.SaleViewSet, basename="sales")
    router.register("returns", operations.SaleReturnViewSet, basename="returns")
    router.register("customer-credits", operations.CustomerCreditViewSet, basename="customer-credits")
    router.register("commissions", commissions.CommissionViewSet, basename="commissions")
    router.register("reviews", reviews.ReviewViewSet, basename="reviews")
