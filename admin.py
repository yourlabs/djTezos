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
        'address',
    )

admin.site.register(Account, AccountAdmin)
admin.site.register(Block)


class BlockchainAdmin(admin.ModelAdmin):
    list_display = (
        'is_active',
        'name',
        'endpoint',
    )
    list_filter = (
        'provider_class',
    )
    list_display_links = (
        'name',
    )
    list_editable = (
        'is_active',
    )

admin.site.register(Blockchain, BlockchainAdmin)


class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'txhash',
        'status',
        'contract_name',
        'function',
        'sender',
        'args',
        'updated_at'
    )
    search_fields = (
        'txhash',
    )
    list_filter = (
        'status',
        'contract_name',
        'function',
    )
    ordering = ['-updated_at']

admin.site.register(Transaction, TransactionAdmin)
