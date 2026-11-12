from starrp.views import modules, registry, rules


def register(router):
    router.register("stores/rules", rules.StoreRuleViewSet, basename="store-rules")  # antes de stores/{id}
    router.register("stores", registry.StoreViewSet, basename="stores")
    router.register("terminals", registry.TerminalViewSet, basename="terminals")
    router.register("users", registry.UserProfileViewSet, basename="users")
    router.register("roles", registry.RoleViewSet, basename="roles")
    router.register("permissions", registry.PermissionViewSet, basename="permissions")
    router.register("integrations", modules.IntegrationViewSet, basename="integrations")
