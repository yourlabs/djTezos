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
    raw_id_fields = (
        'owner',
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

#transaction.sender.blockchain
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'sender',
        'receiver',
        'txhash',
        'status',
        'blockchain',
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
    raw_id_fields = (
        'sender',
        'receiver',
        'contract',
    )
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'status',
        'accepted',
        'sender',
        'receiver',
        'blockchain',
        'txhash',
        'block',
        'gasprice',
        'gas',
        'contract_address',
        'contract_name',
        'contract',
        'function',
        'args',
        'hold',
        'explorer_link',
    )

admin.site.register(Transaction, TransactionAdmin)
