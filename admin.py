from django.contrib import admin

from .models import (
    Account,
    Block,
    Blockchain,
    Transaction,
)


class AccountAdmin(admin.ModelAdmin):
    list_display = (
        'address',
        'blockchain',
        'owner',
    )
    list_filter = (
        'blockchain',
    )
    search_fields = (
        'owner__email',
    )

admin.site.register(Account, AccountAdmin)
admin.site.register(Block)


class BlockchainAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'endpoint',
    )
    list_filter = (
        'provider_class',
    )

admin.site.register(Blockchain, BlockchainAdmin)

admin.site.register(Transaction)
