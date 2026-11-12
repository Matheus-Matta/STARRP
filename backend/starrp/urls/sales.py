from starrp.views import background, commissions, market, operations, reviews, sale_items, sales, seo


def register(router):
    router.register("sales/items", sale_items.SaleItemViewSet, basename="sale-items")
    router.register("sales", sales.SaleViewSet, basename="sales")
    router.register("returns", operations.SaleReturnViewSet, basename="returns")
    router.register("customer-credits", operations.CustomerCreditViewSet, basename="customer-credits")
    router.register("commissions", commissions.CommissionViewSet, basename="commissions")
    router.register("reviews", reviews.ReviewViewSet, basename="reviews")
    router.register("price-checks", market.PriceCheckViewSet, basename="price-checks")
    router.register("seo-checks", seo.SeoCheckViewSet, basename="seo-checks")
    router.register("background-tasks", background.BackgroundTaskViewSet, basename="background-tasks")
    router.register("market-offers", market.MarketOfferViewSet, basename="market-offers")
    router.register("competitor-prices", market.CompetitorPriceViewSet, basename="competitor-prices")
