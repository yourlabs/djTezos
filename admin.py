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
        'accepted',
        'contract_name',
        'function',
        'updated_at',
    )
    search_fields = (
        'txhash',
        'sender__address',
        'sender__owner__name',
        'sender__owner__contact_name',
        'sender__owner__email',
        'sender__owner__contact_email',
    )
    list_filter = (
        'sender__blockchain',
        'created_at',
        'updated_at',
        'status',
        'accepted',
        'contract_name',
        'function',
    )
    ordering = ['-updated_at']

admin.site.register(Transaction, TransactionAdmin)
